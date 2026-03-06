#!/usr/bin/env python3
"""Feedback tracking helper for autodocs. Manages PR outcome data in JSON.

Usage: python3 feedback-helper.py <file> <operation> [args...]

Operations:
  add-pr <number> <platform> <date> <suggestions_json>   Add a PR entry
  list-prs [--open-only]                                  List PR numbers
  has-pr <number>                                         Exit 0 if exists, 1 if not
  update-pr <number> <state> [<date>]                     Update PR state
  pending-sections                                        List (doc|section) pairs from open PRs
  acceptance-rate                                         Print acceptance rate of resolved PRs
"""

import json
import sys
from pathlib import Path


def load_data(path):
    if not path.exists():
        return []
    text = path.read_text().strip()
    if not text:
        return []
    return json.loads(text)


def save_data(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def handle_add_pr(data, args):
    number = int(args[0])
    # Idempotent: don't add if already exists
    if any(pr.get("pr_number") == number for pr in data):
        return
    platform = args[1]
    date = args[2]
    suggestions = json.loads(args[3]) if len(args) > 3 else []
    data.append({
        "pr_number": number,
        "platform": platform,
        "date": date,
        "state": "open",
        "suggestions": suggestions,
    })


def handle_list_prs(data, args):
    open_only = "--open-only" in args
    for pr in data:
        if open_only and pr.get("state") != "open":
            continue
        print(pr.get("pr_number", ""))


def handle_has_pr(data, args):
    number = int(args[0])
    return any(pr.get("pr_number") == number for pr in data)


def handle_update_pr(data, args):
    number = int(args[0])
    new_state = args[1]
    merged_date = args[2] if len(args) > 2 else None
    for pr in data:
        if pr.get("pr_number") == number:
            pr["state"] = new_state
            if merged_date:
                pr["merged_date"] = merged_date
            break


def handle_pending_sections(data):
    for pr in data:
        if pr.get("state") != "open":
            continue
        for s in pr.get("suggestions", []):
            doc = s.get("doc", "")
            section = s.get("section", "")
            if doc and section:
                print(f"{doc}|{section}")


def handle_acceptance_rate(data):
    resolved = [pr for pr in data if pr.get("state") in ("merged", "closed")]
    if not resolved:
        print("n/a")
        return
    merged = sum(1 for pr in resolved if pr.get("state") == "merged")
    rate = merged / len(resolved)
    print(f"{rate:.2f}")


def handle_detect_corrections(data, args):
    """Detect post-merge edits that may indicate incorrect autodocs suggestions.

    Scans merged autodocs PRs from the last 14 days. For each, checks if
    non-autodocs commits edited the same doc files within 7 days of merge.
    Outputs: pr_number|strength|detail (one per line).
    """
    import subprocess
    from datetime import datetime as dt, timedelta

    repo_dir = args[0] if args else "."
    today = dt.now()

    for pr in data:
        if pr.get("state") != "merged":
            continue
        merged_date_str = pr.get("merged_date", "")
        if not merged_date_str:
            continue
        try:
            merged_date = dt.strptime(merged_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if (today - merged_date).days > 14:
            continue

        # Check for human edits to doc files within 7 days of merge
        since = merged_date_str
        until = (merged_date + timedelta(days=7)).strftime("%Y-%m-%d")

        for s in pr.get("suggestions", []):
            doc = s.get("doc", "")
            if not doc:
                continue
            try:
                result = subprocess.run(
                    ["git", "-C", repo_dir, "log", "--oneline",
                     f"--since={since}", f"--until={until}",
                     "--", f"docs/{doc}"],
                    capture_output=True, text=True, timeout=10
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
            commits = [l for l in result.stdout.strip().splitlines()
                       if l and "autodocs" not in l.lower()]
            if commits:
                print(f"{pr['pr_number']}|SECTION_EDIT|{doc} edited by {len(commits)} commit(s) within 7 days of merge")
                break  # One signal per PR is enough


def handle_discover(data, args):
    """Backfill open-prs.json from platform PR search results (JSON string)."""
    try:
        discovered = json.loads(args[0])
    except (json.JSONDecodeError, IndexError):
        return
    platform = args[1] if len(args) > 1 else "github"
    for pr in discovered:
        number = pr.get("number")
        if not number:
            continue
        if any(p.get("pr_number") == number for p in data):
            continue
        data.append({
            "pr_number": number,
            "platform": platform,
            "date": str(pr.get("createdAt", ""))[:10],
            "state": "open",
            "suggestions": [],
        })


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    operation = sys.argv[2]
    args = sys.argv[3:]

    data = load_data(path)

    if operation == "add-pr":
        handle_add_pr(data, args)
        save_data(path, data)
    elif operation == "list-prs":
        handle_list_prs(data, args)
    elif operation == "has-pr":
        sys.exit(0 if handle_has_pr(data, args) else 1)
    elif operation == "update-pr":
        handle_update_pr(data, args)
        save_data(path, data)
    elif operation == "pending-sections":
        handle_pending_sections(data)
    elif operation == "acceptance-rate":
        handle_acceptance_rate(data)
    elif operation == "discover":
        handle_discover(data, args)
        save_data(path, data)
    elif operation == "detect-corrections":
        handle_detect_corrections(data, args)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
