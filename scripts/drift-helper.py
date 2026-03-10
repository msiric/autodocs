#!/usr/bin/env python3
"""Deterministic pre-processing for autodocs drift detection and suggest dedup.

Extracts algorithmic logic from LLM prompts into testable Python code.
The LLM reads the output and focuses on generating natural language descriptions.

Usage:
  python3 drift-helper.py pre-process <output_dir>
  python3 drift-helper.py suggest-dedup <output_dir>

pre-process: Reads daily-report.md, drift-status.md, resolved-mappings.md, config.yaml,
             and doc files. Writes drift-context.json with grouped alerts, dedup results,
             and lifecycle actions.

suggest-dedup: Reads drift-status.md, changelog-*.md, feedback/open-prs.json.
               Writes suggest-context.json with actionable alerts after dedup.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    # Graceful degradation: write empty context so LLM falls back to its own logic
    print("Warning: pyyaml not installed", file=sys.stderr)
    sys.exit(0)

UNMAPPED = "UNMAPPED"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_report(report_path):
    """Parse daily-report.md into structured data."""
    if not report_path.exists():
        return {"date": "", "prs": [], "anomalies": []}

    text = report_path.read_text()
    result = {"date": "", "prs": [], "anomalies": []}

    # Extract date from YAML frontmatter
    fm = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r"date:\s*(.+)", line)
            if m:
                result["date"] = m.group(1).strip()
                break

    # Extract PRs
    current_pr = None
    in_files = False
    for line in text.splitlines():
        # PR header: - PR #123: "Title" by Author — merged (accepts any dash/quote variant)
        pr_match = re.match(r'- PR #(\d+):\s*["\u201c\u201d\']*(.+?)["\u201c\u201d\']*\s*by\s+(.+?)\s*[\u2014\u2013\-]', line)
        if pr_match:
            if current_pr:
                result["prs"].append(current_pr)
            current_pr = {
                "number": int(pr_match.group(1)),
                "title": pr_match.group(2),
                "author": pr_match.group(3),
                "classification": "",
                "files": [],
            }
            in_files = False
            continue

        if current_pr:
            # Classification line: "  <feature_name>: YES|MAYBE|NO|REFACTOR"
            # Feature name can be multi-word (e.g., "Channel Pages: YES")
            cls_match = re.search(r":\s*(YES|MAYBE|NO|REFACTOR)\b", line)
            if cls_match and line.startswith((" ", "\t")):
                current_pr["classification"] = cls_match.group(1)
                continue

            # Files section start
            if re.match(r"\s+Files:", line):
                in_files = True
                continue

            # File entry: M src/auth/handler.ts or R100 src/old.ts → src/new.ts
            if in_files:
                file_match = re.match(r"\s+([MADR])\s+(.+)", line)
                if file_match:
                    current_pr["files"].append({
                        "change_type": file_match.group(1),
                        "path": file_match.group(2).strip(),
                    })
                    continue
                # Renamed file with similarity: R100 src/old.ts → src/new.ts
                rename_match = re.match(r"\s+R\d*\s+.+?→\s*(.+)", line)
                if rename_match:
                    current_pr["files"].append({
                        "change_type": "R",
                        "path": rename_match.group(1).strip(),
                    })
                    continue
                # Non-file line ends the files section
                if not line.strip().startswith(("M ", "A ", "D ", "R")):
                    in_files = False

    if current_pr:
        result["prs"].append(current_pr)

    # Extract anomalies (lines with "NEW")
    in_anomalies = False
    for line in text.splitlines():
        if "### Anomalies" in line:
            in_anomalies = True
            continue
        if in_anomalies:
            if line.startswith("##"):
                break
            if re.search(r'\bNEW\b', line):
                result["anomalies"].append(line.strip().lstrip("- "))

    return result


def parse_status(status_path):
    """Parse drift-status.md into unchecked and checked entries."""
    unchecked = []
    checked = []
    if not status_path.exists():
        return unchecked, checked

    for line in status_path.read_text().splitlines():
        # - [ ] 2026-03-04 | doc | section | trigger | confidence
        m = re.match(
            r"- \[([ x])\]\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\w+)(.*)",
            line,
        )
        if not m:
            continue
        entry = {
            "date": m.group(2),
            "doc": m.group(3).strip(),
            "section": m.group(4).strip(),
            "trigger": m.group(5).strip(),
            "confidence": m.group(6).strip(),
        }
        resolution = m.group(7).strip().lstrip("| ") if m.group(7) else ""
        if m.group(1) == " ":
            unchecked.append(entry)
        else:
            entry["resolution"] = resolution
            checked.append(entry)

    return unchecked, checked


def apply_lifecycle(output_dir):
    """Post-process drift-status.md: expire LOW entries >7 days, trim checked >30 days.

    Called after Call 2 (drift) to enforce lifecycle rules that the LLM cannot apply.
    Rewrites drift-status.md in place with filtered entries.
    """
    output_dir = Path(output_dir)
    status_path = output_dir / "drift-status.md"
    if not status_path.exists():
        return

    unchecked, checked = parse_status(status_path)
    today_str = datetime.now().strftime("%Y-%m-%d")
    kept_unchecked, kept_checked, expired, trimmed = manage_lifecycle(
        unchecked, checked, today_str
    )

    # Only rewrite if something was actually removed
    if not expired and not trimmed:
        return

    lines = []
    for entry in kept_unchecked:
        lines.append(
            f"- [ ] {entry['date']} | {entry['doc']} | {entry['section']} "
            f"| {entry['trigger']} | {entry['confidence']}"
        )
    for entry in kept_checked:
        res = f" | {entry.get('resolution', '')}" if entry.get("resolution") else ""
        lines.append(
            f"- [x] {entry['date']} | {entry['doc']} | {entry['section']} "
            f"| {entry['trigger']} | {entry['confidence']}{res}"
        )

    status_path.write_text("\n".join(lines) + "\n" if lines else "")


def parse_resolved_mappings(mappings_path):
    """Parse resolved-mappings.md into a dict of {path: (section, doc)}."""
    mappings = {}
    if not mappings_path.exists():
        return mappings

    for line in mappings_path.read_text().splitlines():
        # M src/auth/handler.ts → Authentication
        m = re.match(r"([MADR])\s+(.+?)\s+→\s+(.+)", line)
        if m:
            mappings[m.group(2).strip()] = m.group(3).strip()

    return mappings


def parse_doc_sections(doc_path):
    """Extract ## headers from a doc, with breadcrumb disambiguation."""
    if not doc_path.exists():
        return []

    headers = []
    parent_h2 = ""
    for line in doc_path.read_text().splitlines():
        if line.startswith("## ") and not line.startswith("###"):
            parent_h2 = line[3:].strip()
            headers.append({"name": parent_h2, "level": 2})
        elif line.startswith("### "):
            headers.append({"name": line[4:].strip(), "level": 3, "parent": parent_h2})

    # Disambiguate duplicate names
    name_counts = {}
    for h in headers:
        name_counts[h["name"]] = name_counts.get(h["name"], 0) + 1

    result = []
    for h in headers:
        if name_counts[h["name"]] > 1 and h.get("parent"):
            result.append({
                "name": h["name"],
                "disambiguated": f"{h['parent']} > {h['name']}",
            })
        else:
            result.append({
                "name": h["name"],
                "disambiguated": h["name"],
            })

    return result


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------

def build_section_to_doc(config):
    """Build a {section_name: doc_name} index from all docs' package_maps."""
    index = {}
    for doc in config.get("docs") or []:
        doc_name = doc["name"]
        for value in (doc.get("package_map") or {}).values():
            if isinstance(value, str):
                index[value] = doc_name
            elif isinstance(value, dict):
                if value.get("default"):
                    index[value["default"]] = doc_name
                for section in (value.get("title_hints") or {}).values():
                    index[section] = doc_name
    return index


def generate_alerts(report, mappings, config):
    """Generate new alerts from today's PRs using mappings and change types."""
    alerts = []
    docs = config.get("docs") or []
    ignore_packages = set()
    for doc in docs:
        for pkg in doc.get("ignore_packages") or []:
            ignore_packages.add(pkg)

    section_to_doc = build_section_to_doc(config)

    for pr in report.get("prs", []):
        cls = pr.get("classification", "")
        if cls == "NO":
            continue

        if cls == "REFACTOR":
            alerts.append({
                "doc": "",
                "section": "",
                "prs": [pr["number"]],
                "confidence": "LOW",
                "description_hint": f"Large refactoring PR ({len(pr['files'])} files) — manual review recommended",
            })
            continue

        if cls in ("YES", "MAYBE") and not pr.get("files"):
            alerts.append({
                "doc": "",
                "section": "",
                "prs": [pr["number"]],
                "confidence": "LOW",
                "description_hint": "Feature PR merged but file paths unavailable — manual review required",
            })
            continue

        for f in pr.get("files", []):
            section = mappings.get(f["path"], UNMAPPED)
            ct = f["change_type"]

            if section == UNMAPPED:
                is_in_feature = any(
                    f["path"].startswith(rp)
                    for rp in config.get("relevant_paths") or []
                )
                path_parts = f["path"].split("/")
                pkg_name = path_parts[1] if len(path_parts) > 2 else path_parts[0]
                if is_in_feature and pkg_name not in ignore_packages:
                    alerts.append({
                        "doc": docs[0]["name"] if docs else "",
                        "section": UNMAPPED,
                        "prs": [pr["number"]],
                        "confidence": "CRITICAL",
                        "description_hint": f"New file {f['path']} in unmapped package — doc index may need update",
                    })
                continue

            doc_name = section_to_doc.get(section, "")

            # Map change type to confidence and description
            hints = {
                "M": f"Modified {f['path']}",
                "A": f"Added {f['path']}",
                "D": f"Deleted {f['path']} — remove doc references",
                "R": f"Renamed to {f['path']} — update doc path references",
            }

            alerts.append({
                "doc": doc_name,
                "section": section,
                "prs": [pr["number"]],
                "confidence": "HIGH",
                "description_hint": hints.get(ct, f"Changed {f['path']}"),
            })

    return alerts


def generate_anomaly_alerts(report, config):
    """Generate alerts from NEW telemetry anomalies."""
    alerts = []
    docs = config.get("docs") or []
    for anomaly in report.get("anomalies", []):
        for doc in docs:
            kps = doc.get("known_patterns_section")
            if kps:
                alerts.append({
                    "doc": doc["name"],
                    "section": kps,
                    "prs": [],
                    "confidence": "HIGH",
                    "description_hint": f"New telemetry pattern: {anomaly}",
                })
                break
    return alerts


# ---------------------------------------------------------------------------
# Grouping, dedup, lifecycle
# ---------------------------------------------------------------------------

def group_alerts(alerts):
    """Group alerts by (doc, section), merge PR lists."""
    grouped = {}
    for a in alerts:
        key = (a["doc"], a["section"])
        if key in grouped:
            grouped[key]["prs"] = list(set(grouped[key]["prs"] + a["prs"]))
            # Escalate confidence: CRITICAL > HIGH > LOW
            rank = {"CRITICAL": 3, "HIGH": 2, "LOW": 1}
            if rank.get(a["confidence"], 0) > rank.get(grouped[key]["confidence"], 0):
                grouped[key]["confidence"] = a["confidence"]
            # Append description hints
            if a["description_hint"] not in grouped[key]["description_hint"]:
                grouped[key]["description_hint"] += f"; {a['description_hint']}"
        else:
            grouped[key] = dict(a)
    return list(grouped.values())


def dedup_against_status(new_alerts, unchecked):
    """Dedup new alerts against existing unchecked status entries.

    Returns (final_alerts, dedup_actions) where:
    - final_alerts: new alerts not already in status
    - dedup_actions: updates to apply to existing entries
    """
    existing = {(e["doc"], e["section"]) for e in unchecked}
    final = []
    actions = []
    for a in new_alerts:
        key = (a["doc"], a["section"])
        if key in existing:
            pr_str = ", ".join(f"PR #{p}" for p in a["prs"])
            actions.append({
                "action": "append",
                "doc": a["doc"],
                "section": a["section"],
                "append_prs": pr_str,
            })
        else:
            final.append(a)
    return final, actions


def manage_lifecycle(unchecked, checked, today_str):
    """Apply lifecycle rules to drift-status entries.

    Returns (kept_unchecked, kept_checked, expired, trimmed).
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    expired = []
    trimmed = []
    kept_unchecked = []
    kept_checked = []

    for entry in unchecked:
        entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        age_days = (today - entry_date).days
        if entry["confidence"] == "LOW" and age_days > 7:
            expired.append(entry)
        else:
            kept_unchecked.append(entry)

    for entry in checked:
        entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        age_days = (today - entry_date).days
        if age_days > 30:
            trimmed.append(entry)
        else:
            kept_checked.append(entry)

    return kept_unchecked, kept_checked, expired, trimmed


# ---------------------------------------------------------------------------
# Changelog merger
# ---------------------------------------------------------------------------

def _parse_changelog_sections(text):
    """Parse a changelog file into an ordered list of (section_name, entries).

    Each entry is a dict with 'pr_number' (int) and 'text' (raw lines including header).
    Preserves section and entry order from the file.
    """
    sections = []
    current_section = ""
    current_entry_lines = []
    current_entry_pr = None

    def _flush_entry():
        if current_entry_lines and current_section:
            sections_dict = dict(sections)
            if current_section not in sections_dict:
                sections.append((current_section, []))
                sections_dict = dict(sections)
            sections_dict[current_section].append({
                "pr_number": current_entry_pr,
                "text": "\n".join(current_entry_lines),
            })
            # Update in-place (sections list shares refs with dict values)

    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            _flush_entry()
            current_entry_lines = []
            current_entry_pr = None
            current_section = line[3:].strip()
            continue

        if line.startswith("### "):
            _flush_entry()
            current_entry_lines = [line]
            pr_match = re.search(r"PR #(\d+)", line)
            current_entry_pr = int(pr_match.group(1)) if pr_match else None
            continue

        if line.strip() == "---":
            # Section separator — flush but don't start new section
            _flush_entry()
            current_entry_lines = []
            current_entry_pr = None
            continue

        if current_entry_lines is not None:
            current_entry_lines.append(line)

    _flush_entry()
    return sections


def merge_changelogs(output_dir):
    """Merge new changelog entries from LLM output into original files, preserving order.

    For each changelog-*.md that has a .bak backup (saved before Call 3):
    1. Parse both the backup (original) and the LLM-written version
    2. Find entries in the LLM version whose PR# is new for that section
    3. Insert new entries at the top of the section in the original
    4. Write the merged result back
    """
    output_dir = Path(output_dir)

    for bak_path in output_dir.glob("changelog-*.md.bak"):
        changelog_path = bak_path.with_suffix("")  # Remove .bak
        if not changelog_path.exists():
            bak_path.unlink()
            continue

        original_text = bak_path.read_text(encoding="utf-8", errors="replace")
        llm_text = changelog_path.read_text(encoding="utf-8", errors="replace")

        # Extract H1 header from original (e.g., "# doc.md — Changelog")
        header = ""
        for line in original_text.splitlines():
            if line.startswith("# "):
                header = line
                break

        original_sections = _parse_changelog_sections(original_text)
        llm_sections = _parse_changelog_sections(llm_text)

        # Build index of existing PR numbers per section in original
        original_prs = {}
        for section_name, entries in original_sections:
            original_prs[section_name] = {e["pr_number"] for e in entries if e["pr_number"]}

        # Find and insert new entries
        changed = False
        for section_name, llm_entries in llm_sections:
            existing_prs = original_prs.get(section_name, set())
            new_entries = [e for e in llm_entries
                          if e["pr_number"] and e["pr_number"] not in existing_prs]
            if not new_entries:
                continue
            changed = True
            # Find or create section in original
            section_found = False
            for i, (name, entries) in enumerate(original_sections):
                if name == section_name:
                    # Insert new entries at top of section (newest first)
                    for entry in reversed(new_entries):
                        entries.insert(0, entry)
                    section_found = True
                    break
            if not section_found:
                original_sections.append((section_name, new_entries))

        if not changed:
            # No new entries — restore original (undo LLM reordering)
            changelog_path.write_text(original_text)
            bak_path.unlink()
            continue

        # Write merged result
        lines = []
        if header:
            lines.append(header)
            lines.append("")
        for section_name, entries in original_sections:
            lines.append(f"## {section_name}")
            lines.append("")
            for entry in entries:
                lines.append(entry["text"])
                lines.append("")
            lines.append("---")
            lines.append("")

        changelog_path.write_text("\n".join(lines))
        bak_path.unlink()


# ---------------------------------------------------------------------------
# Suggest dedup
# ---------------------------------------------------------------------------

def parse_changelog_entries(output_dir):
    """Extract (doc, section, PR) tuples from existing changelog files."""
    entries = set()
    for f in output_dir.glob("changelog-*.md"):
        doc_stem = f.stem.replace("changelog-", "") + ".md"
        current_section = ""
        for line in f.read_text().splitlines():
            if line.startswith("## "):
                current_section = line[3:].strip()
            pr_match = re.search(r"PR #(\d+)", line)
            if pr_match and current_section:
                entries.add((doc_stem, current_section, int(pr_match.group(1))))
    return entries


def get_pending_sections(output_dir):
    """Get (doc, section) pairs from open PRs in feedback/open-prs.json."""
    pending = set()
    prs_file = output_dir / "feedback" / "open-prs.json"
    if not prs_file.exists():
        return pending
    try:
        data = json.loads(prs_file.read_text())
    except (json.JSONDecodeError, ValueError):
        return pending
    for pr in data:
        if pr.get("state") != "open":
            continue
        for s in pr.get("suggestions", []):
            doc = s.get("doc", "")
            section = s.get("section", "")
            if doc and section:
                pending.add((doc, section))
    return pending


# ---------------------------------------------------------------------------
# Main operations
# ---------------------------------------------------------------------------

def pre_process(output_dir):
    """Run full drift pre-processing. Write drift-context.json."""
    output_dir = Path(output_dir)
    config_path = output_dir / "config.yaml"
    if not config_path.exists():
        return

    config = yaml.safe_load(config_path.read_text()) or {}

    # Parse inputs
    report = parse_report(output_dir / "daily-report.md")
    unchecked, checked = parse_status(output_dir / "drift-status.md")
    mappings = parse_resolved_mappings(output_dir / "resolved-mappings.md")

    # Parse doc sections for breadcrumb disambiguation
    doc_sections = {}
    for doc in config.get("docs") or []:
        doc_path = output_dir / doc["name"]
        doc_sections[doc["name"]] = parse_doc_sections(doc_path)

    # Generate and group alerts
    today = report.get("date") or datetime.now().strftime("%Y-%m-%d")
    pr_alerts = generate_alerts(report, mappings, config)
    anomaly_alerts = generate_anomaly_alerts(report, config)
    all_alerts = group_alerts(pr_alerts + anomaly_alerts)

    # Dedup against existing status
    new_alerts, dedup_actions = dedup_against_status(all_alerts, unchecked)

    # Lifecycle management
    kept_unchecked, kept_checked, expired, trimmed = manage_lifecycle(
        unchecked, checked, today
    )

    # Count relevant PRs (YES/MAYBE classification) for liveness guard
    relevant_count = sum(
        1 for pr in report.get("prs", [])
        if pr.get("classification") in ("YES", "MAYBE")
    )

    context = {
        "date": today,
        "prs": report["prs"],
        "anomalies": report["anomalies"],
        "new_alerts": new_alerts,
        "existing_status": {
            "unchecked": kept_unchecked,
            "checked": kept_checked,
        },
        "dedup_actions": dedup_actions,
        "lifecycle": {
            "auto_expired": expired,
            "trimmed": trimmed,
        },
        "doc_sections": doc_sections,
        "summary": {
            "pr_count": len(report.get("prs", [])),
            "relevant_count": relevant_count,
        },
    }

    (output_dir / "drift-context.json").write_text(
        json.dumps(context, indent=2) + "\n"
    )


def suggest_dedup(output_dir):
    """Run suggest dedup. Write suggest-context.json."""
    output_dir = Path(output_dir)

    unchecked, _ = parse_status(output_dir / "drift-status.md")
    changelog_entries = parse_changelog_entries(output_dir)
    pending = get_pending_sections(output_dir)

    actionable = []
    skipped = []

    for entry in unchecked:
        if entry["confidence"] not in ("HIGH", "CRITICAL"):
            continue

        doc = entry["doc"]
        section = entry["section"]

        # Check if all triggering PRs already have changelog entries
        trigger_prs = re.findall(r"#(\d+)", entry.get("trigger", ""))
        all_in_changelog = trigger_prs and all(
            (doc, section, int(pr)) in changelog_entries for pr in trigger_prs
        )
        if all_in_changelog:
            skipped.append({
                "doc": doc,
                "section": section,
                "reason": "changelog entries exist for all triggering PRs",
            })
            continue

        # Check if pending open PR
        if (doc, section) in pending:
            skipped.append({
                "doc": doc,
                "section": section,
                "reason": "open autodocs PR pending review",
            })
            continue

        actionable.append({
            "doc": doc,
            "section": section,
            "trigger": entry.get("trigger", ""),
            "confidence": entry["confidence"],
        })

    # Detect changelog supersession (warn when later PRs touch same files)
    changelog_warnings = _detect_changelog_supersession(output_dir, changelog_entries)

    context = {
        "actionable_alerts": actionable,
        "skipped": skipped,
        "changelog_warnings": changelog_warnings,
    }

    (output_dir / "suggest-context.json").write_text(
        json.dumps(context, indent=2) + "\n"
    )


def _detect_changelog_supersession(output_dir, changelog_entries):
    """Flag changelog entries whose files were modified by later PRs."""
    warnings = []
    report = parse_report(output_dir / "daily-report.md")

    # Build pr_number → file paths mapping
    pr_files = {}
    for pr in report.get("prs", []):
        pr_files[pr["number"]] = [f["path"] for f in pr.get("files", [])]

    # For each changelog entry, check if a later PR touched the same files
    seen = set()
    for (doc, section, pr_num) in changelog_entries:
        files_for_pr = pr_files.get(pr_num, [])
        if not files_for_pr:
            continue
        for other_pr, other_files in pr_files.items():
            if other_pr <= pr_num:
                continue
            shared = set(files_for_pr) & set(other_files)
            if shared:
                key = (doc, section, pr_num)
                if key not in seen:
                    seen.add(key)
                    warnings.append({
                        "doc": doc,
                        "section": section,
                        "pr": pr_num,
                        "superseded_by": other_pr,
                        "shared_files": sorted(shared),
                    })
                break

    return warnings


# ---------------------------------------------------------------------------
# Verification functions have been extracted to verify-helper.py
# drift-helper.py retains backward-compatible CLI dispatch below
# ---------------------------------------------------------------------------


def _run_verify_helper(operation, output_dir, repo_dir=None):
    """Delegate to verify-helper.py for backward compatibility."""
    import subprocess
    helper = Path(__file__).parent / "verify-helper.py"
    cmd = ["python3", str(helper), operation, str(output_dir)]
    if repo_dir:
        cmd.append(str(repo_dir))
    return subprocess.run(cmd).returncode == 0


def verify_finds(output_dir, repo_dir):
    """Delegates to verify-helper.py."""
    return _run_verify_helper("verify-finds", output_dir, repo_dir)


def verify_replaces(output_dir, repo_dir=None):
    """Delegates to verify-helper.py."""
    return _run_verify_helper("verify-replaces", output_dir, repo_dir)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    operation = sys.argv[1]
    output_dir = sys.argv[2]

    if operation == "pre-process":
        pre_process(output_dir)
    elif operation == "apply-lifecycle":
        apply_lifecycle(output_dir)
    elif operation == "merge-changelogs":
        merge_changelogs(output_dir)
    elif operation == "suggest-dedup":
        suggest_dedup(output_dir)
    elif operation == "verify-finds":
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else "."
        ok = verify_finds(output_dir, repo_dir)
        sys.exit(0 if ok else 1)
    elif operation == "verify-replaces":
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else None
        verify_replaces(output_dir, repo_dir)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
