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

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_data(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text().strip()
    if not text:
        return []
    return json.loads(text)


def save_data(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def handle_add_pr(data: list[dict], args: list[str]) -> None:
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


def handle_list_prs(data: list[dict], args: list[str]) -> None:
    open_only = "--open-only" in args
    for pr in data:
        if open_only and pr.get("state") != "open":
            continue
        print(pr.get("pr_number", ""))


def handle_has_pr(data: list[dict], args: list[str]) -> bool:
    number = int(args[0])
    return any(pr.get("pr_number") == number for pr in data)


def handle_update_pr(data: list[dict], args: list[str]) -> None:
    number = int(args[0])
    new_state = args[1]
    merged_date = args[2] if len(args) > 2 else None
    for pr in data:
        if pr.get("pr_number") == number:
            pr["state"] = new_state
            if merged_date:
                pr["merged_date"] = merged_date
            break


def handle_pending_sections(data: list[dict]) -> None:
    for pr in data:
        if pr.get("state") != "open":
            continue
        for s in pr.get("suggestions", []):
            doc = s.get("doc", "")
            section = s.get("section", "")
            if doc and section:
                print(f"{doc}|{section}")


AUTOMATED_CLOSE_REASONS = {"superseded", "expired_find", "age_stale", "changes_applied"}


def handle_acceptance_rate(data: list[dict]) -> None:
    merged = [pr for pr in data if pr.get("state") == "merged"]
    # Human rejections: closed without an automated close_reason
    rejected = [pr for pr in data if pr.get("state") == "closed"
                and pr.get("close_reason") not in AUTOMATED_CLOSE_REASONS]
    auto_closed = [pr for pr in data if pr.get("state") == "closed"
                   and pr.get("close_reason") in AUTOMATED_CLOSE_REASONS]

    denominator = len(merged) + len(rejected)
    if denominator == 0:
        print("n/a")
        return
    rate = len(merged) / denominator
    print(f"{rate:.2f} ({len(merged)} merged, {len(rejected)} rejected, {len(auto_closed)} auto-closed)")


def handle_detect_corrections(data: list[dict], args: list[str]) -> None:
    """Deprecated: correction detection now lives in pipeline-helper.py (_detect_corrections).

    Called automatically during pre-sync. This CLI subcommand is retained for
    backward compatibility but prints a deprecation notice.
    """
    print("detect-corrections has moved to pipeline-helper.py (runs automatically during pre-sync)",
          file=sys.stderr)


def handle_discover(data: list[dict], args: list[str]) -> None:
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


def main() -> None:
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
