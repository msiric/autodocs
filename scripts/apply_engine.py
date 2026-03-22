#!/usr/bin/env python3
"""Deterministic apply engine for autodocs.

Replaces the LLM apply call with pure Python. Parses verified suggestions,
applies FIND/REPLACE edits to doc files, creates a git branch, opens a PR,
and records tracking data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Suggestion:
    doc: str
    section: str
    operation: str        # "REPLACE" or "INSERT_AFTER"
    find_text: str
    replace_text: str
    confidence: str       # "CONFIDENT" or "REVIEW"
    verified: str         # "YES" or "NO"
    triggered_by: str
    reasoning: str


@dataclass
class ApplyResult:
    success: bool
    pr_number: int | None = None
    applied: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Suggestion parsing
# ---------------------------------------------------------------------------

def parse_suggestions(text: str) -> list[Suggestion]:
    """Parse drift-suggestions.md into structured Suggestion objects.

    Follows the same parsing patterns as verify-helper.py but extracts
    all fields needed for apply.
    """
    suggestions: list[Suggestion] = []
    current_doc = ""
    current_section = ""
    confidence = ""
    triggered_by = ""
    verified = ""
    reasoning = ""
    operation = ""
    find_lines: list[str] = []
    replace_lines: list[str] = []
    in_find = False
    in_replace = False

    def _flush():
        if find_lines and current_doc:
            suggestions.append(Suggestion(
                doc=current_doc,
                section=current_section,
                operation=operation or "REPLACE",
                find_text="\n".join(find_lines),
                replace_text="\n".join(replace_lines),
                confidence=confidence,
                verified=verified,
                triggered_by=triggered_by,
                reasoning=reasoning,
            ))

    for line in text.splitlines():
        # Doc + section header: ## doc.md — Section Name
        doc_match = re.match(r"## (\S+\.\w+)\s*[\u2014\u2013\-]\s*(.*)", line)
        if doc_match:
            _flush()
            find_lines, replace_lines = [], []
            in_find = in_replace = False
            current_doc = doc_match.group(1)
            current_section = doc_match.group(2).strip()
            confidence = verified = triggered_by = reasoning = operation = ""
            continue

        # Metadata fields
        if line.startswith("**Triggered by:**"):
            triggered_by = line.split("**Triggered by:**", 1)[1].strip()
            continue
        if line.startswith("**Confidence:**"):
            confidence = "CONFIDENT" if "CONFIDENT" in line else "REVIEW"
            continue
        if line.startswith("**Verified:**"):
            verified = "YES" if "YES" in line else "NO"
            continue

        # Reasoning section
        if line.startswith("### Reasoning"):
            continue
        if not in_find and not in_replace and not line.startswith("#") and line.strip() and \
                reasoning == "" and verified and not line.startswith("---") and not line.startswith(">") and \
                not line.startswith("**"):
            reasoning = line.strip()
            continue

        # FIND block start
        if "### FIND" in line:
            _flush()
            find_lines, replace_lines = [], []
            in_find = True
            in_replace = False
            if "anchor" in line.lower() or "insert after" in line.lower():
                operation = "INSERT_AFTER"
            else:
                operation = "REPLACE"
            continue

        # REPLACE/INSERT block start
        if "### REPLACE WITH:" in line:
            in_find = False
            in_replace = True
            operation = "REPLACE"
            continue
        if "### INSERT AFTER:" in line:
            in_find = False
            in_replace = True
            operation = "INSERT_AFTER"
            continue

        # Quoted content lines ("> text" or bare ">" for empty blockquote lines)
        if in_find:
            if line.startswith("> "):
                find_lines.append(line[2:])
            elif line.rstrip() == ">":
                find_lines.append("")
            elif line.strip() == "":
                continue
            else:
                in_find = False
            continue

        if in_replace:
            if line.startswith("> "):
                replace_lines.append(line[2:])
            elif line.rstrip() == ">":
                replace_lines.append("")
            elif line.strip() == "":
                continue
            else:
                in_replace = False
            continue

    _flush()
    return suggestions


# ---------------------------------------------------------------------------
# Filtering (gate logic from apply-prompt.md Step 1)
# ---------------------------------------------------------------------------

def filter_suggestions(
    suggestions: list[Suggestion],
    output_dir: Path,
) -> tuple[list[Suggestion], list[dict]]:
    """Apply gate logic. Returns (applicable, skipped_with_reasons)."""
    # Load verification results if available
    verified_json = _load_json(output_dir / "verified-suggestions.json")
    replace_json = _load_json(output_dir / "replace-verification.json")

    applicable: list[Suggestion] = []
    skipped: list[dict] = []

    for i, s in enumerate(suggestions):
        reason = None

        # Gate 1: Must be CONFIDENT + Verified: YES
        if s.confidence != "CONFIDENT":
            reason = "REVIEW confidence"
        elif s.verified != "YES":
            reason = "Verified: NO"

        # Gate 2: FIND verification (if available)
        if not reason and verified_json:
            entry = verified_json[i] if i < len(verified_json) else None
            if entry and entry.get("status") == "FAIL":
                reason = "FIND verification failed"

        # Gate 3: REPLACE verification (if available)
        if not reason and replace_json:
            entry = replace_json[i] if i < len(replace_json) else None
            if entry:
                gate = entry.get("gate", "")
                if gate == "BLOCK":
                    reason = f"REPLACE blocked: {_first_mismatch(entry)}"
                elif gate == "REVIEW":
                    reason = "REPLACE values unverified"

        if reason:
            skipped.append({"suggestion": s, "reason": reason})
        else:
            applicable.append(s)

    return applicable, skipped


def _first_mismatch(entry: dict) -> str:
    """Extract first MISMATCH reason from replace-verification entry."""
    for v in entry.get("values", []):
        if v.get("status") == "MISMATCH":
            return v.get("reason", "value mismatch")
    return "value mismatch"


def _load_json(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------

def apply_edits(
    applicable: list[Suggestion],
    doc_paths: dict[str, Path],
) -> tuple[list[dict], list[dict]]:
    """Apply FIND/REPLACE and INSERT AFTER to doc files.

    Returns (applied, expired) where expired are suggestions whose FIND
    text was not found in the current doc.
    """
    applied: list[dict] = []
    expired: list[dict] = []

    for s in applicable:
        doc_path = doc_paths.get(s.doc)
        if not doc_path or not doc_path.exists():
            expired.append({"suggestion": s, "reason": f"doc file not found: {s.doc}"})
            continue

        content = doc_path.read_text(encoding="utf-8", errors="replace")

        if s.operation == "REPLACE":
            if s.find_text in content:
                new_content = content.replace(s.find_text, s.replace_text, 1)
                doc_path.write_text(new_content)
                applied.append({"doc": s.doc, "section": s.section, "operation": "REPLACE",
                                "triggered_by": s.triggered_by})
            elif _normalize_ws(s.find_text) in _normalize_ws(content):
                # Whitespace-normalized match
                new_content = _replace_normalized(content, s.find_text, s.replace_text)
                doc_path.write_text(new_content)
                applied.append({"doc": s.doc, "section": s.section, "operation": "REPLACE",
                                "triggered_by": s.triggered_by, "note": "whitespace-normalized"})
            else:
                reason = _diagnose_expired(content, s.section)
                expired.append({"suggestion": s, "reason": reason})

        elif s.operation == "INSERT_AFTER":
            if s.find_text in content:
                insertion_point = content.index(s.find_text) + len(s.find_text)
                new_content = content[:insertion_point] + "\n" + s.replace_text + content[insertion_point:]
                doc_path.write_text(new_content)
                applied.append({"doc": s.doc, "section": s.section, "operation": "INSERT_AFTER",
                                "triggered_by": s.triggered_by})
            else:
                reason = _diagnose_expired(content, s.section)
                expired.append({"suggestion": s, "reason": reason})

    return applied, expired


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _replace_normalized(content: str, find: str, replace: str) -> str:
    """Replace find_text in content using whitespace-flexible regex matching.

    Builds a regex from the find text where whitespace runs become \\s+
    patterns, then replaces the first match in the original content.
    """
    tokens = find.split()
    if not tokens:
        return content
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    return re.sub(pattern, replace, content, count=1)


def _diagnose_expired(content: str, section: str) -> str:
    """Diagnose why FIND text wasn't found."""
    if section and f"## {section}" in content:
        return f"EXPIRED: FIND text not found but section '{section}' exists"
    if section:
        return f"SECTION REMOVED: section '{section}' not found in doc"
    return "EXPIRED: FIND text not found in doc"


# ---------------------------------------------------------------------------
# Changelog copy
# ---------------------------------------------------------------------------

def copy_changelogs(
    output_dir: Path,
    repo_dir: Path,
    applied: list[dict],
    doc_paths: dict[str, Path],
) -> list[Path]:
    """Merge new changelog entries into repo changelogs (append-only).

    The output directory's changelog may have been rewritten by the LLM.
    The repo's changelog is the authoritative history. We extract new
    entries (by PR number) from the output version and insert them into
    the repo version, preserving all existing entries.
    """
    copied: list[Path] = []
    docs_with_changes = {a["doc"] for a in applied}

    for doc_name in docs_with_changes:
        stem = doc_name.replace(".md", "")
        source = output_dir / f"changelog-{stem}.md"
        if not source.exists():
            continue
        doc_path = doc_paths.get(doc_name)
        if not doc_path:
            continue
        dest = doc_path.parent / f"changelog-{stem}.md"

        if dest.exists():
            # Merge: only add entries whose PR# is new to the repo version
            _merge_changelog_into(source, dest)
        else:
            # No existing changelog in repo — copy the full file
            shutil.copy2(source, dest)
        copied.append(dest)

    return copied


def _merge_changelog_into(source: Path, dest: Path) -> None:
    """Merge new entries from source changelog into dest (append-only).

    Parses both files by section. For each section, inserts entries whose
    PR number doesn't already exist in dest. Preserves dest's existing
    entries and section order.
    """
    source_text = source.read_text(encoding="utf-8", errors="replace")
    dest_text = dest.read_text(encoding="utf-8", errors="replace")

    # Extract header from dest
    header = ""
    for line in dest_text.splitlines():
        if line.startswith("# "):
            header = line
            break

    source_sections = _parse_changelog_for_merge(source_text)
    dest_sections = _parse_changelog_for_merge(dest_text)

    # Build index of existing PR numbers per section in dest
    dest_prs: dict[str, set[int]] = {}
    for section_name, entries in dest_sections:
        dest_prs[section_name] = {e["pr"] for e in entries if e["pr"]}

    # Find new entries from source
    changed = False
    for section_name, source_entries in source_sections:
        existing_prs = dest_prs.get(section_name, set())
        new_entries = [e for e in source_entries if e["pr"] and e["pr"] not in existing_prs]
        if not new_entries:
            continue
        changed = True
        # Find or create section in dest
        found = False
        for i, (name, entries) in enumerate(dest_sections):
            if name == section_name:
                for entry in reversed(new_entries):
                    entries.insert(0, entry)
                found = True
                break
        if not found:
            dest_sections.append((section_name, new_entries))

    if not changed:
        return  # Nothing new — keep dest as-is

    # Write merged result
    lines = []
    if header:
        lines.extend([header, ""])
    for section_name, entries in dest_sections:
        lines.append(f"## {section_name}")
        lines.append("")
        for entry in entries:
            lines.append(entry["text"])
            lines.append("")
        lines.append("---")
        lines.append("")

    dest.write_text("\n".join(lines))


def _parse_changelog_for_merge(text: str) -> list[tuple[str, list[dict]]]:
    """Parse a changelog into [(section_name, [{"pr": int, "text": str}])]."""
    sections: list[tuple[str, list[dict]]] = []
    section_index: dict[str, list[dict]] = {}
    current_section = ""
    current_lines: list[str] = []
    current_pr: int | None = None

    def _flush():
        if current_lines and current_section:
            if current_section not in section_index:
                entries: list[dict] = []
                sections.append((current_section, entries))
                section_index[current_section] = entries
            section_index[current_section].append({
                "pr": current_pr,
                "text": "\n".join(current_lines),
            })

    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            _flush()
            current_lines = []
            current_pr = None
            current_section = line[3:].strip()
            continue
        if line.startswith("### "):
            _flush()
            current_lines = [line]
            pr_match = re.search(r"PR #(\d+)", line)
            current_pr = int(pr_match.group(1)) if pr_match else None
            continue
        if line.strip() == "---":
            _flush()
            current_lines = []
            current_pr = None
            continue
        if current_lines is not None:
            current_lines.append(line)

    _flush()
    return sections


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def git_branch_commit_push(
    repo_dir: Path,
    branch: str,
    target_branch: str,
    files: list[Path],
    message: str,
) -> bool:
    """Create branch, add files, commit, push. Returns True on success."""
    def _git(*args: str) -> bool:
        result = subprocess.run(
            ["git"] + list(args), capture_output=True, text=True, cwd=str(repo_dir),
        )
        return result.returncode == 0

    # Check if branch already exists on remote
    result = subprocess.run(
        ["git", "branch", "-r", "--list", f"origin/{branch}"],
        capture_output=True, text=True, cwd=str(repo_dir),
    )
    if result.stdout.strip():
        return False  # Branch already exists

    if not _git("checkout", "-b", branch):
        return False

    for f in files:
        _git("add", str(f))

    if not _git("commit", "-m", message):
        _git("checkout", "-")
        return False

    success = _git("push", "origin", branch)
    _git("checkout", "-")  # Always return to previous branch
    return success


# ---------------------------------------------------------------------------
# PR creation (multi-platform)
# ---------------------------------------------------------------------------

def create_pr(config: dict, branch: str, title: str, body: str) -> int | None:
    """Create PR via platform CLI. Returns PR number or None."""
    platform = config.get("platform", "")
    target = config.get("auto_pr", {}).get("target_branch", "main")

    if platform == "github":
        owner = config.get("github", {}).get("owner", "")
        repo = config.get("github", {}).get("repo", "")
        if not owner or not repo:
            return None
        result = subprocess.run(
            ["gh", "pr", "create", "-R", f"{owner}/{repo}",
             "--title", title, "--body", body,
             "--base", target, "--head", branch, "--label", "autodocs"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            # gh pr create prints the PR URL; extract number
            url = result.stdout.strip()
            m = re.search(r"/(\d+)$", url)
            return int(m.group(1)) if m else None

    elif platform == "gitlab":
        project = config.get("gitlab", {}).get("project_path", "")
        if not project:
            return None
        result = subprocess.run(
            ["glab", "mr", "create", "-R", project,
             "--title", title, "--description", body,
             "--target-branch", target, "--source-branch", branch, "--no-editor"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            m = re.search(r"!(\d+)", result.stdout)
            return int(m.group(1)) if m else None

    elif platform == "bitbucket":
        ws = config.get("bitbucket", {}).get("workspace", "")
        repo = config.get("bitbucket", {}).get("repo", "")
        token = os.environ.get("BITBUCKET_TOKEN", "")
        if not ws or not repo or not token:
            return None
        pr_json = json.dumps({
            "title": title,
            "source": {"branch": {"name": branch}},
            "destination": {"branch": {"name": target}},
            "description": body,
        })
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "-H", f"Authorization: Bearer {token}",
             "-H", "Content-Type: application/json",
             "-d", pr_json,
             f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}/pullrequests"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return data.get("id")
            except (json.JSONDecodeError, ValueError):
                pass

    elif platform == "ado":
        ado = config.get("ado", {})
        org, project = ado.get("org", ""), ado.get("project", "")
        repo_name = ado.get("repo", "")
        if not org or not project:
            return None
        work_items = config.get("auto_pr", {}).get("work_item_ids", "")
        cmd = [
            "az", "repos", "pr", "create",
            "--org", f"https://dev.azure.com/{org}",
            "-p", project, "--repository", repo_name,
            "--source-branch", branch, "--target-branch", target,
            "--title", title, "--description", body,
            "--query", "pullRequestId", "-o", "tsv",
        ]
        if work_items:
            cmd.extend(["--work-items", work_items])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())

    return None


# ---------------------------------------------------------------------------
# PR body builder
# ---------------------------------------------------------------------------

def build_pr_body(
    applied: list[dict],
    skipped: list[dict],
    expired: list[dict],
    date: str,
) -> str:
    """Build PR description markdown."""
    lines = ["## autodocs — automated documentation updates", ""]

    if applied:
        lines.append("### Applied (verified)")
        lines.append(f"Applied {len(applied)} suggestions to documentation:")
        lines.append("")
        for a in applied:
            lines.append(f"**{a['doc']} — {a['section']}**")
            lines.append(f"Triggered by: {a.get('triggered_by', 'N/A')}")
            lines.append(f"Operation: {a['operation']}")
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("### Applied (verified)")
        lines.append("No suggestions were auto-applied.")
        lines.append("")

    if skipped or expired:
        lines.append("### Needs Manual Review")
        lines.append("")
        for s in skipped:
            sug = s.get("suggestion") or s
            if isinstance(sug, Suggestion):
                lines.append(f"**{sug.doc} — {sug.section}** ({s['reason']})")
                lines.append(f"Triggered by: {sug.triggered_by}")
            else:
                lines.append(f"**Skipped** ({s['reason']})")
            lines.append("")
        for e in expired:
            sug = e.get("suggestion") or e
            if isinstance(sug, Suggestion):
                lines.append(f"**{sug.doc} — {sug.section}** ({e['reason']})")
            else:
                lines.append(f"**Expired** ({e['reason']})")
            lines.append("")

    lines.append(f"Generated by [autodocs](https://github.com/msiric/autodocs)")
    lines.append("")
    sections = [f'"{a["doc"]}|{a["section"]}"' for a in applied]
    lines.append(f'<!-- autodocs:meta {{"date":"{date}","sections":[{",".join(sections)}]}} -->')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

def record_tracking(
    output_dir: Path,
    pr_number: int,
    platform: str,
    date: str,
    applied: list[dict],
) -> None:
    """Append PR tracking data to feedback/open-prs.json."""
    path = output_dir / "feedback" / "open-prs.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            data = []

    # Idempotent: don't add if already tracked
    if any(p.get("pr_number") == pr_number for p in data):
        return

    data.append({
        "pr_number": pr_number,
        "platform": platform,
        "date": date,
        "state": "open",
        "suggestions": [
            {"doc": a["doc"], "section": a["section"], "type": a["operation"],
             "find_text": ""}
            for a in applied
        ],
    })
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def deterministic_apply(config: dict, output_dir: Path, repo_dir: Path) -> ApplyResult:
    """Apply verified suggestions and open PR. No LLM needed."""
    # Read suggestions
    suggestions_path = output_dir / "drift-suggestions.md"
    if not suggestions_path.exists():
        return ApplyResult(success=True)

    text = suggestions_path.read_text(encoding="utf-8", errors="replace")
    suggestions = parse_suggestions(text)
    if not suggestions:
        return ApplyResult(success=True)

    # Filter by verification gates
    applicable, skipped = filter_suggestions(suggestions, output_dir)

    # Build doc name → repo path mapping
    doc_paths: dict[str, Path] = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = repo_dir / doc["repo_path"]

    if not applicable and not skipped:
        return ApplyResult(success=True)

    # Apply edits to doc files
    applied: list[dict] = []
    expired: list[dict] = []
    if applicable:
        applied, expired = apply_edits(applicable, doc_paths)

    # Copy changelogs
    changelog_paths = copy_changelogs(output_dir, repo_dir, applied, doc_paths)

    # Collect all modified files
    modified_files = [doc_paths[a["doc"]] for a in applied if a["doc"] in doc_paths]
    modified_files.extend(changelog_paths)

    if not applied and not skipped and not expired:
        return ApplyResult(success=True)

    # Git + PR
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = config.get("auto_pr", {}).get("branch_prefix", "autodocs/")
    branch = f"{prefix}{date}"
    target = config.get("auto_pr", {}).get("target_branch", "main")
    platform = config.get("platform", "")

    body = build_pr_body(applied, skipped, expired, date)
    title = f"docs: autodocs suggested updates — {date}"

    pr_number = None
    if modified_files:
        commit_msg = f"docs: autodocs suggested updates for {date}\n\n"
        commit_msg += f"Applied {len(applied)} verified suggestions:\n"
        for a in applied:
            commit_msg += f"- {a['doc']}: {a['section']} ({a.get('triggered_by', '')})\n"

        if not git_branch_commit_push(repo_dir, branch, target, modified_files, commit_msg):
            return ApplyResult(success=False, applied=applied, skipped=[s for s in skipped],
                               error="git branch/commit/push failed")

        pr_number = create_pr(config, branch, title, body)
    elif skipped or expired:
        # No file changes but suggestions need review — create PR with description only
        # This requires at least one commit, so skip PR creation in this case
        pass

    if pr_number:
        record_tracking(output_dir, pr_number, platform, date, applied)

    return ApplyResult(success=True, pr_number=pr_number, applied=applied,
                       skipped=[s for s in skipped])
