#!/usr/bin/env python3
"""Pipeline orchestration helper for autodocs.

Handles pre-Call-1 operations that were previously in sync.sh bash:
discovery, PR state checking, correction detection, stale management,
and open PR limit checking. All platform CLI calls happen here.

Usage:
  python3 pipeline-helper.py pre-sync <output_dir> <repo_dir> <platform>
  python3 pipeline-helper.py copy-sources <output_dir> <repo_dir>

pre-sync: Run all pre-Call-1 operations. Writes pre-sync-result.json.
copy-sources: Copy mapped source files to source-context/ for suggest prompt.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Warning: pyyaml not installed, skipping pre-sync", file=sys.stderr)
    sys.exit(0)

UNMAPPED = "UNMAPPED"
STALE_LABEL = "autodocs:stale"
BRANCH_PREFIX = "autodocs/"


# ---------------------------------------------------------------------------
# Platform CLI wrappers
# ---------------------------------------------------------------------------

def _run_cli(args, timeout=30):
    """Run a CLI command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _gh(args, repo):
    """Run a gh CLI command for a specific repo."""
    return _run_cli(["gh"] + args + ["-R", repo])


def _parse_json(text):
    """Parse JSON safely, return None on failure."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _ado_parts(repo_id):
    """Parse ADO repo_id 'org/project/repo' into (org_url, project, repo) or None."""
    parts = repo_id.split("/") if repo_id else []
    if len(parts) < 3:
        return None
    return f"https://dev.azure.com/{parts[0]}", parts[1], parts[2]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(output_dir):
    """Load config.yaml from output directory."""
    config_path = Path(output_dir) / "config.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def get_platform_repo(config, platform):
    """Get the platform-specific repo identifier."""
    if platform == "github":
        gh = config.get("github", {})
        owner, repo = gh.get("owner", ""), gh.get("repo", "")
        return f"{owner}/{repo}" if owner and repo else None
    if platform == "gitlab":
        return config.get("gitlab", {}).get("project_path")
    if platform == "bitbucket":
        bb = config.get("bitbucket", {})
        ws, repo = bb.get("workspace", ""), bb.get("repo", "")
        return f"{ws}/{repo}" if ws and repo else None
    if platform == "ado":
        ado = config.get("ado", {})
        org, project = ado.get("org", ""), ado.get("project", "")
        repo = ado.get("repo_id") or ado.get("repo", "")
        return f"{org}/{project}/{repo}" if org and project else None
    return None


# ---------------------------------------------------------------------------
# Feedback operations
# ---------------------------------------------------------------------------

def load_feedback(output_dir):
    """Load open-prs.json."""
    path = Path(output_dir) / "feedback" / "open-prs.json"
    if not path.exists():
        return []
    text = path.read_text().strip()
    return json.loads(text) if text else []


def save_feedback(output_dir, data):
    """Save open-prs.json."""
    path = Path(output_dir) / "feedback" / "open-prs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def discover_prs(platform, repo_id):
    """Discover existing autodocs PRs not yet tracked."""
    if not repo_id:
        return []
    if platform == "github":
        output = _gh(
            ["pr", "list", "--search", f"head:{BRANCH_PREFIX} is:open",
             "--json", "number,createdAt", "--limit", "50"],
            repo_id,
        )
        return _parse_json(output) or []
    if platform == "gitlab":
        output = _run_cli(
            ["glab", "mr", "list", "-R", repo_id, "--source-branch", BRANCH_PREFIX,
             "--state", "opened", "-F", "json", "--per-page", "50"],
        )
        mrs = _parse_json(output) or []
        return [{"number": mr.get("iid"), "createdAt": mr.get("created_at", "")}
                for mr in mrs if mr.get("iid")]
    if platform == "bitbucket":
        token = os.environ.get("BITBUCKET_TOKEN", "")
        if token:
            output = _run_cli([
                "curl", "-s", "-H", f"Authorization: Bearer {token}",
                f"https://api.bitbucket.org/2.0/repositories/{repo_id}/pullrequests"
                f"?state=OPEN&q=source.branch.name+%7E+%22autodocs%2F%22&pagelen=50",
            ])
            data = _parse_json(output)
            if data and "values" in data:
                return [{"number": pr.get("id"), "createdAt": pr.get("created_on", "")}
                        for pr in data["values"] if pr.get("id")]
    if platform == "ado":
        ado = _ado_parts(repo_id)
        if ado:
            org_url, project, _repo = ado
            output = _run_cli([
                "az", "repos", "pr", "list",
                "--org", org_url, "-p", project,
                "--source-branch", BRANCH_PREFIX, "--status", "active",
                "--query", "[].{number:pullRequestId, createdAt:creationDate}",
                "-o", "json",
            ])
            return _parse_json(output) or []
    return []


def check_pr_state(platform, repo_id, pr_number):
    """Check if a PR has been merged or closed. Returns MERGED, CLOSED, or None."""
    if platform == "github" and repo_id:
        output = _gh(
            ["pr", "view", str(pr_number), "--json", "state", "--jq", ".state"],
            repo_id
        )
        if output == "MERGED":
            return "MERGED"
        if output == "CLOSED":
            return "CLOSED"
    elif platform == "gitlab" and repo_id:
        output = _run_cli(
            ["glab", "mr", "view", str(pr_number), "-R", repo_id, "-F", "json"]
        )
        data = _parse_json(output)
        if data:
            state = data.get("state", "")
            if state == "merged":
                return "MERGED"
            if state == "closed":
                return "CLOSED"
    elif platform == "bitbucket" and repo_id:
        token = os.environ.get("BITBUCKET_TOKEN", "")
        if token:
            output = _run_cli([
                "curl", "-s", "-H", f"Authorization: Bearer {token}",
                f"https://api.bitbucket.org/2.0/repositories/{repo_id}/pullrequests/{pr_number}"
            ])
            data = _parse_json(output)
            if data:
                state = data.get("state", "")
                if state == "MERGED":
                    return "MERGED"
                if state in ("DECLINED", "SUPERSEDED"):
                    return "CLOSED"
    elif platform == "ado" and repo_id:
        ado = _ado_parts(repo_id)
        if ado:
            org_url, project, _repo = ado
            output = _run_cli([
                "az", "repos", "pr", "show", "--id", str(pr_number),
                "--org", org_url, "-p", project,
                "--query", "status", "-o", "tsv",
            ])
            if output == "completed":
                return "MERGED"
            if output == "abandoned":
                return "CLOSED"
    return None


def _stale_warn_body(reason):
    return (f"**autodocs**: {reason}. This PR will be auto-closed in 7 days "
            f"if no activity. Add label `autodocs:keep-open` to prevent.")


def _stale_close_body(reason):
    return (f"**autodocs**: Closing — {reason}. A fresh PR will be generated "
            f"if changes are still needed.")


def execute_stale_action(platform, repo_id, pr_number, action, reason):
    """Execute a stale PR action (warn or close)."""
    if not repo_id:
        return
    pr = str(pr_number)
    if platform == "github":
        body = _stale_warn_body(reason) if action == "warn" else _stale_close_body(reason)
        _gh(["pr", "comment", pr, "--body", body], repo_id)
        if action == "warn":
            _gh(["pr", "edit", pr, "--add-label", STALE_LABEL], repo_id)
        elif action == "close":
            _gh(["pr", "close", pr], repo_id)
    elif platform == "gitlab":
        body = _stale_warn_body(reason) if action == "warn" else _stale_close_body(reason)
        _run_cli(["glab", "mr", "note", pr, "-R", repo_id, "-m", body])
        if action == "warn":
            _run_cli(["glab", "mr", "update", pr, "-R", repo_id, "--label-add", STALE_LABEL])
        elif action == "close":
            _run_cli(["glab", "mr", "close", pr, "-R", repo_id])
    elif platform == "bitbucket":
        token = os.environ.get("BITBUCKET_TOKEN", "")
        if not token:
            return
        body = _stale_warn_body(reason) if action == "warn" else _stale_close_body(reason)
        comment_json = json.dumps({"content": {"raw": body}})
        _run_cli([
            "curl", "-s", "-X", "POST",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "-d", comment_json,
            f"https://api.bitbucket.org/2.0/repositories/{repo_id}/pullrequests/{pr}/comments",
        ])
        if action == "close":
            _run_cli([
                "curl", "-s", "-X", "POST",
                "-H", f"Authorization: Bearer {token}",
                "-H", "Content-Type: application/json",
                "-d", '{"state": "DECLINED"}',
                f"https://api.bitbucket.org/2.0/repositories/{repo_id}/pullrequests/{pr}/decline",
            ])
    elif platform == "ado":
        ado = _ado_parts(repo_id)
        if not ado:
            return
        org_url, project, repo_name = ado
        body = _stale_warn_body(reason) if action == "warn" else _stale_close_body(reason)
        # Post comment via REST (az CLI lacks a thread-create command).
        # Auth: az CLI token injected via credential helper.
        token = _run_cli(["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"])
        if token:
            thread_json = json.dumps({
                "comments": [{"content": body, "commentType": 1}],
                "status": 1,
            })
            _run_cli([
                "curl", "-s", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {token}",
                "-d", thread_json,
                f"{org_url}/{project}/_apis/git/repositories/{repo_name}"
                f"/pullRequests/{pr}/threads?api-version=7.0",
            ])
        if action == "close":
            _run_cli([
                "az", "repos", "pr", "update", "--id", pr,
                "--org", org_url, "-p", project,
                "--status", "abandoned",
            ])


def _build_doc_paths(config, repo_dir):
    """Build doc name → repo Path mapping from config."""
    doc_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = Path(repo_dir) / doc["repo_path"]
    return doc_paths


def _all_finds_expired(pr, doc_paths):
    """Check if all of a PR's find_text entries no longer match the doc on main."""
    find_texts = [s for s in pr.get("suggestions", []) if s.get("find_text")]
    if not find_texts:
        return False
    for s in find_texts:
        doc_path = doc_paths.get(s.get("doc", ""))
        if doc_path and doc_path.exists() and s["find_text"] in doc_path.read_text():
            return False
    return True


def _detect_stale_prs(feedback, config, repo_dir, today_str, stale_labels):
    """Detect stale PRs. Returns list of 'pr_num|action|reason' strings."""
    today = datetime.strptime(today_str, "%Y-%m-%d")
    stale_config = config.get("stale_pr", {})
    warn_days = stale_config.get("warn_after_days", 14)
    close_days = stale_config.get("close_after_days", 21)
    max_actions = stale_config.get("max_actions_per_run", 5)

    open_prs = [pr for pr in feedback if pr.get("state") == "open"]
    results = []
    doc_paths = _build_doc_paths(config, repo_dir)

    for pr in open_prs:
        if len(results) >= max_actions:
            break

        pr_num = pr.get("pr_number")
        pr_date_str = pr.get("date", "")
        if not pr_date_str:
            continue
        try:
            pr_date = datetime.strptime(pr_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        age_days = (today - pr_date).days

        # SUPERSEDED: all sections covered by a newer PR
        sections = {(s.get("doc", ""), s.get("section", ""))
                    for s in pr.get("suggestions", []) if s.get("doc") and s.get("section")}
        if sections:
            for other in open_prs:
                if other.get("pr_number") == pr_num or other.get("date", "") <= pr_date_str:
                    continue
                other_sections = {(s.get("doc", ""), s.get("section", ""))
                                  for s in other.get("suggestions", []) if s.get("doc") and s.get("section")}
                if sections <= other_sections:
                    results.append(f"{pr_num}|close|Superseded by PR #{other['pr_number']}")
                    break
            else:
                pass  # Not superseded, check other conditions below
            if any(f"{pr_num}|close" in r for r in results):
                continue

        # EXPIRED_FIND: all find_text entries don't match doc
        if _all_finds_expired(pr, doc_paths):
            results.append(f"{pr_num}|close|All FIND texts no longer match doc on main")
            continue

        # AGE: two-phase warn/close
        has_stale_label = stale_labels.get(str(pr_num), False)
        if age_days >= close_days and has_stale_label:
            results.append(f"{pr_num}|close|Open for {age_days} days with no activity after warning")
        elif age_days >= warn_days and not has_stale_label:
            results.append(f"{pr_num}|warn|Open for {age_days} days with no activity")

    return results


def get_stale_labels(platform, repo_id):
    """Get PR numbers that have the autodocs:stale label."""
    labels = {}
    if not repo_id:
        return labels
    if platform == "github":
        output = _gh(
            ["pr", "list", "--label", STALE_LABEL, "--state", "open",
             "--json", "number", "--limit", "50"],
            repo_id,
        )
        prs = _parse_json(output) or []
        for pr in prs:
            labels[str(pr.get("number", ""))] = True
    elif platform == "gitlab":
        output = _run_cli(
            ["glab", "mr", "list", "-R", repo_id, "--label", STALE_LABEL,
             "--state", "opened", "-F", "json", "--per-page", "50"],
        )
        mrs = _parse_json(output) or []
        for mr in mrs:
            labels[str(mr.get("iid", ""))] = True
    elif platform == "bitbucket":
        # Bitbucket doesn't have labels; stale tracking uses age-only fallback.
        # The two-phase warn/close still works — warn comments are visible,
        # close happens after close_after_days regardless of label.
        pass
    elif platform == "ado":
        ado = _ado_parts(repo_id)
        if ado:
            org_url, project, _repo = ado
            output = _run_cli([
                "az", "repos", "pr", "list",
                "--org", org_url, "-p", project,
                "--status", "active", "--label", STALE_LABEL,
                "--query", "[].pullRequestId", "-o", "json",
            ])
            prs = _parse_json(output) or []
            for pr_id in prs:
                labels[str(pr_id)] = True
    return labels


# ---------------------------------------------------------------------------
# Pre-sync orchestration
# ---------------------------------------------------------------------------

def _backfill_discovered(feedback, platform, repo_id):
    """Discover existing autodocs PRs on the platform and backfill any not yet tracked."""
    discovered = discover_prs(platform, repo_id)
    new_count = 0
    for pr in discovered:
        number = pr.get("number")
        if not number or any(p.get("pr_number") == number for p in feedback):
            continue
        feedback.append({
            "pr_number": number,
            "platform": platform,
            "date": str(pr.get("createdAt", ""))[:10],
            "state": "open",
            "suggestions": [],
        })
        new_count += 1
    return new_count


def _check_pr_states(feedback, platform, repo_id, today_str):
    """Check platform state of all tracked open PRs. Returns (state_updates, log_entries)."""
    state_updates = []
    log_entries = []
    for pr in feedback:
        if pr.get("state") != "open":
            continue
        new_state = check_pr_state(platform, repo_id, pr["pr_number"])
        if new_state == "MERGED":
            pr["state"] = "merged"
            pr["merged_date"] = today_str
            state_updates.append({"pr": pr["pr_number"], "state": "merged"})
            log_entries.append(f"FEEDBACK: PR #{pr['pr_number']} merged")
        elif new_state == "CLOSED":
            pr["state"] = "closed"
            state_updates.append({"pr": pr["pr_number"], "state": "closed"})
            log_entries.append(f"FEEDBACK: PR #{pr['pr_number']} closed")
    return state_updates, log_entries


def _detect_corrections(feedback, config, repo_dir):
    """Detect post-merge human edits to doc files (signals incorrect suggestions).

    Scans merged PRs from the last 14 days. For each, checks if non-autodocs
    commits edited the same doc files within 7 days of merge.
    """
    doc_repo_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_repo_paths[doc["name"]] = doc["repo_path"]

    corrections = []
    log_entries = []
    for pr in feedback:
        if pr.get("state") != "merged" or not pr.get("merged_date"):
            continue
        try:
            merged_date = datetime.strptime(pr["merged_date"], "%Y-%m-%d")
        except ValueError:
            continue
        if (datetime.now() - merged_date).days > 14:
            continue
        for s in pr.get("suggestions", []):
            doc = s.get("doc", "")
            if not doc or doc not in doc_repo_paths:
                continue
            since = pr["merged_date"]
            until = (merged_date + timedelta(days=7)).strftime("%Y-%m-%d")
            result = _run_cli([
                "git", "-C", str(repo_dir), "log", "--oneline",
                f"--since={since}", f"--until={until}",
                "--", doc_repo_paths[doc],
            ])
            if result:
                commits = [l for l in result.splitlines() if "autodocs" not in l.lower()]
                if commits:
                    corrections.append({
                        "pr": pr["pr_number"],
                        "strength": "SECTION_EDIT",
                        "detail": f"{doc} edited by {len(commits)} commit(s) within 7 days of merge",
                    })
                    log_entries.append(
                        f"CORRECTION SIGNAL: PR #{pr['pr_number']} (SECTION_EDIT) — "
                        f"{doc} edited by {len(commits)} commit(s)"
                    )
                    break
    return corrections, log_entries


def _manage_stale(feedback, config, repo_dir, platform, repo_id, today_str):
    """Detect and execute stale PR actions. Returns (stale_actions, log_entries)."""
    stale_labels = get_stale_labels(platform, repo_id)
    stale_results = _detect_stale_prs(feedback, config, repo_dir, today_str, stale_labels)

    stale_actions = []
    log_entries = []
    for line in stale_results:
        parts = line.split("|")
        if len(parts) < 3:
            continue
        pr_num, action, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
        execute_stale_action(platform, repo_id, int(pr_num), action, reason)
        if action == "close":
            # Determine close reason from stale action reason text
            close_reason = "age_stale"
            if "Superseded" in reason:
                close_reason = "superseded"
            elif "FIND texts" in reason:
                close_reason = "expired_find"
            for pr in feedback:
                if pr.get("pr_number") == int(pr_num):
                    pr["state"] = "closed"
                    pr["close_reason"] = close_reason
        stale_actions.append({"pr": int(pr_num), "action": action, "reason": reason})
        log_entries.append(f"STALE: {action} PR #{pr_num} ({reason})")
    return stale_actions, log_entries


def pre_sync(output_dir, repo_dir, platform):
    """Run all pre-Call-1 operations. Write pre-sync-result.json."""
    output_dir = Path(output_dir)
    config = load_config(output_dir)
    repo_id = get_platform_repo(config, platform)
    feedback = load_feedback(output_dir)
    log_entries = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    new_discovered = _backfill_discovered(feedback, platform, repo_id)

    state_updates, state_log = _check_pr_states(feedback, platform, repo_id, today_str)
    log_entries.extend(state_log)

    # Determine close_reason for PRs that were just detected as closed on the platform.
    # If all FIND texts are expired, the human likely applied changes manually.
    doc_paths = _build_doc_paths(config, str(repo_dir))
    for update in state_updates:
        if update["state"] != "closed":
            continue
        for pr in feedback:
            if pr.get("pr_number") == update["pr"] and pr.get("state") == "closed":
                if _all_finds_expired(pr, doc_paths):
                    pr["close_reason"] = "changes_applied"
                else:
                    pr["close_reason"] = "human"
                break

    corrections, correction_log = _detect_corrections(feedback, config, str(repo_dir))
    log_entries.extend(correction_log)

    stale_actions, stale_log = _manage_stale(
        feedback, config, str(repo_dir), platform, repo_id, today_str
    )
    log_entries.extend(stale_log)

    open_count = sum(1 for pr in feedback if pr.get("state") == "open")
    max_open = config.get("limits", {}).get("max_open_prs", 10)

    save_feedback(output_dir, feedback)

    result = {
        "proceed": open_count < max_open,
        "skip_reason": f"open PR limit ({open_count}/{max_open})" if open_count >= max_open else None,
        "discovered": new_discovered,
        "state_updates": state_updates,
        "corrections": corrections,
        "stale_actions": stale_actions,
        "open_count": open_count,
        "log": log_entries,
    }

    (output_dir / "pre-sync-result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


# ---------------------------------------------------------------------------
# Source file copy
# ---------------------------------------------------------------------------

MAX_SOURCE_FILES = 200
MAX_SOURCE_BYTES = 10 * 1024 * 1024  # 10 MB


def copy_sources(output_dir, repo_dir):
    """Copy mapped source files to source-context/ for suggest prompt.

    Guards against monorepo blowup: stops at MAX_SOURCE_FILES or MAX_SOURCE_BYTES.
    """
    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)
    source_dir = output_dir / "source-context"
    import shutil
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True)

    mappings_path = output_dir / "resolved-mappings.md"
    if not mappings_path.exists():
        return 0

    copied = 0
    total_bytes = 0
    seen = set()
    for line in mappings_path.read_text().splitlines():
        m = re.match(r"[MADR]\d*\s+(\S+)\s+→\s+(.+)", line)
        if m and m.group(2).strip() != UNMAPPED:
            src_path = m.group(1).strip()
            if src_path in seen:
                continue
            seen.add(src_path)
            full_path = repo_dir / src_path
            if full_path.exists() and full_path.is_file():
                file_size = full_path.stat().st_size
                if copied >= MAX_SOURCE_FILES or total_bytes + file_size > MAX_SOURCE_BYTES:
                    print(
                        f"source-context: stopped at {copied} files / "
                        f"{total_bytes // 1024}KB (limits: {MAX_SOURCE_FILES} files / "
                        f"{MAX_SOURCE_BYTES // 1024 // 1024}MB)",
                        file=sys.stderr,
                    )
                    break
                dest = source_dir / src_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full_path, dest)
                copied += 1
                total_bytes += file_size

    return copied


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    operation = sys.argv[1]

    if operation == "pre-sync":
        output_dir = sys.argv[2]
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else "."
        platform = sys.argv[4] if len(sys.argv) > 4 else "github"
        pre_sync(output_dir, repo_dir, platform)
    elif operation == "copy-sources":
        output_dir = sys.argv[2]
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else "."
        copy_sources(output_dir, repo_dir)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
