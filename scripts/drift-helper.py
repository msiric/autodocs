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
        # PR header: - PR #123: "Title" by Author — merged
        pr_match = re.match(r"- PR #(\d+):\s*\"(.+?)\"\s*by\s+(.+?)\s*—", line)
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
            # Classification line (various formats)
            cls_match = re.match(r"\s+\S+:\s*(YES|MAYBE|NO|REFACTOR)", line)
            if cls_match:
                current_pr["classification"] = cls_match.group(1)
                continue

            # Files section start
            if re.match(r"\s+Files:", line):
                in_files = True
                continue

            # File entry: M src/auth/handler.ts
            if in_files:
                file_match = re.match(r"\s+([MADR])\s+(.+)", line)
                if file_match:
                    current_pr["files"].append({
                        "change_type": file_match.group(1),
                        "path": file_match.group(2).strip(),
                    })
                    continue
                # Renamed file: R src/old.ts → src/new.ts
                rename_match = re.match(r"\s+R\s+.+?→\s*(.+)", line)
                if rename_match:
                    current_pr["files"].append({
                        "change_type": "R",
                        "path": rename_match.group(1).strip(),
                    })
                    continue
                # Non-file line ends the files section
                if not line.strip().startswith(("M ", "A ", "D ", "R ")):
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
            if "NEW" in line:
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
            section = mappings.get(f["path"], "UNMAPPED")
            ct = f["change_type"]

            if section == "UNMAPPED":
                is_in_feature = any(
                    f["path"].startswith(rp)
                    for rp in config.get("relevant_paths") or []
                )
                path_parts = f["path"].split("/")
                pkg_name = path_parts[1] if len(path_parts) > 2 else path_parts[0]
                if is_in_feature and pkg_name not in ignore_packages:
                    alerts.append({
                        "doc": docs[0]["name"] if docs else "",
                        "section": "UNMAPPED",
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

    context = {
        "actionable_alerts": actionable,
        "skipped": skipped,
    }

    (output_dir / "suggest-context.json").write_text(
        json.dumps(context, indent=2) + "\n"
    )


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    operation = sys.argv[1]
    output_dir = sys.argv[2]

    if operation == "pre-process":
        pre_process(output_dir)
    elif operation == "suggest-dedup":
        suggest_dedup(output_dir)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
