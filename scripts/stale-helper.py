#!/usr/bin/env python3
"""Detect stale autodocs PRs for automated cleanup.

Usage: python3 stale-helper.py <open-prs.json> <config.yaml> <repo_dir> list-stale

Staleness conditions (all deterministic, no LLM):
  SUPERSEDED:    All suggestion sections covered by a newer open autodocs PR
  EXPIRED_FIND:  All find_text entries no longer match doc on main
  STALE_WARNING: Open > warn_after_days with no autodocs:stale label yet
  STALE_CLOSE:   Has autodocs:stale label and open > close_after_days

Output: pr_num|action|reason (one per line)
  action: warn | close
"""

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)


def load_json(path):
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text().strip()
    return json.loads(text) if text else []


def load_config(path):
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def get_open_prs(data):
    return [pr for pr in data if pr.get("state") == "open"]


def check_superseded(pr, all_open):
    """Check if all of this PR's sections are covered by a newer open PR."""
    sections = {
        (s.get("doc", ""), s.get("section", ""))
        for s in pr.get("suggestions", [])
        if s.get("doc") and s.get("section")
    }
    if not sections:
        return False

    pr_date = pr.get("date", "")
    for other in all_open:
        if other.get("pr_number") == pr.get("pr_number"):
            continue
        if other.get("date", "") <= pr_date:
            continue
        other_sections = {
            (s.get("doc", ""), s.get("section", ""))
            for s in other.get("suggestions", [])
            if s.get("doc") and s.get("section")
        }
        if sections <= other_sections:
            return True
    return False


def check_expired_find(pr, config, repo_dir):
    """Check if all find_text entries no longer match the doc on main."""
    suggestions = pr.get("suggestions", [])
    find_texts = [s for s in suggestions if s.get("find_text")]
    if not find_texts:
        return False

    doc_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = Path(repo_dir) / doc["repo_path"]

    all_expired = True
    for s in find_texts:
        doc_path = doc_paths.get(s.get("doc", ""))
        if not doc_path or not doc_path.exists():
            continue
        if s["find_text"] in doc_path.read_text():
            all_expired = False
            break

    return all_expired


def list_stale(data, config, repo_dir, today_str=None, stale_labels=None):
    """Find stale PRs and return actions to take.

    Args:
        stale_labels: dict of {pr_number: bool} — True if PR has autodocs:stale label
    """
    if today_str is None:
        today_str = datetime.now().strftime("%Y-%m-%d")
    if stale_labels is None:
        stale_labels = {}

    today = datetime.strptime(today_str, "%Y-%m-%d")
    stale_config = config.get("stale_pr") or {}
    warn_days = stale_config.get("warn_after_days", 14)
    close_days = stale_config.get("close_after_days", 21)
    max_actions = stale_config.get("max_actions_per_run", 5)

    open_prs = get_open_prs(data)
    actions = []

    for pr in open_prs:
        if len(actions) >= max_actions:
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

        # Immediate close: SUPERSEDED
        if check_superseded(pr, open_prs):
            newer = next(
                (o for o in open_prs
                 if o.get("date", "") > pr_date_str
                 and o.get("pr_number") != pr_num),
                None,
            )
            newer_num = newer.get("pr_number", "?") if newer else "?"
            actions.append(
                f"{pr_num}|close|Superseded by PR #{newer_num}"
            )
            continue

        # Immediate close: EXPIRED_FIND
        if check_expired_find(pr, config, repo_dir):
            actions.append(
                f"{pr_num}|close|All FIND texts no longer match doc on main"
            )
            continue

        # Two-phase age: warn then close
        has_stale_label = stale_labels.get(str(pr_num), False)

        if age_days >= close_days and has_stale_label:
            actions.append(
                f"{pr_num}|close|Open for {age_days} days with no activity after warning"
            )
        elif age_days >= warn_days and not has_stale_label:
            actions.append(
                f"{pr_num}|warn|Open for {age_days} days with no activity"
            )

    return actions


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    prs_path = sys.argv[1]
    config_path = sys.argv[2]
    repo_dir = sys.argv[3]
    operation = sys.argv[4]

    data = load_json(prs_path)
    config = load_config(config_path)

    if operation == "list-stale":
        today_str = sys.argv[5] if len(sys.argv) > 5 else None
        stale_labels = {}
        if len(sys.argv) > 6:
            try:
                stale_labels = json.loads(sys.argv[6])
            except (json.JSONDecodeError, ValueError):
                pass
        results = list_stale(data, config, repo_dir, today_str, stale_labels)
        for line in results:
            print(line)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
