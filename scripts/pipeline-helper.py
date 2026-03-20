#!/usr/bin/env python3
"""Pipeline orchestration helper for autodocs.

Orchestrates pre-Call-1 operations and source file copying. Platform-specific
CLI operations are in platform-helper.py.

Usage:
  python3 pipeline-helper.py pre-sync <output_dir> <repo_dir> <platform>
  python3 pipeline-helper.py copy-sources <output_dir> <repo_dir>

pre-sync: Run all pre-Call-1 operations. Writes pre-sync-result.json.
copy-sources: Copy mapped source files to source-context/ for suggest prompt.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Warning: pyyaml not installed, skipping pre-sync", file=sys.stderr)
    sys.exit(0)

from platform_helper import (
    _all_finds_expired,
    _build_doc_paths,
    backfill_discovered,
    check_pr_states,
    detect_corrections,
    manage_stale,
)

UNMAPPED = "UNMAPPED"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(output_dir: str | Path) -> dict:
    """Load config.yaml from output directory."""
    config_path = Path(output_dir) / "config.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def get_platform_repo(config: dict, platform: str) -> str | None:
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
# Feedback I/O
# ---------------------------------------------------------------------------

def load_feedback(output_dir: str | Path) -> list[dict]:
    """Load open-prs.json."""
    path = Path(output_dir) / "feedback" / "open-prs.json"
    if not path.exists():
        return []
    text = path.read_text().strip()
    return json.loads(text) if text else []


def save_feedback(output_dir: str | Path, data: list[dict]) -> None:
    """Save open-prs.json."""
    path = Path(output_dir) / "feedback" / "open-prs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Pre-sync orchestration
# ---------------------------------------------------------------------------

def pre_sync(output_dir: str | Path, repo_dir: str | Path, platform: str) -> None:
    """Run all pre-Call-1 operations. Write pre-sync-result.json."""
    output_dir = Path(output_dir)
    config = load_config(output_dir)
    repo_id = get_platform_repo(config, platform)
    feedback = load_feedback(output_dir)
    log_entries: list[str] = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    new_discovered = backfill_discovered(feedback, platform, repo_id)

    state_updates, state_log = check_pr_states(feedback, platform, repo_id, today_str)
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

    corrections, correction_log = detect_corrections(feedback, config, str(repo_dir))
    log_entries.extend(correction_log)

    stale_actions, stale_log = manage_stale(
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


def copy_sources(output_dir: str | Path, repo_dir: str | Path) -> int:
    """Copy mapped source files to source-context/ for suggest prompt.

    Guards against monorepo blowup: stops at MAX_SOURCE_FILES or MAX_SOURCE_BYTES.
    """
    import shutil

    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)
    source_dir = output_dir / "source-context"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True)

    mappings_path = output_dir / "resolved-mappings.md"
    if not mappings_path.exists():
        return 0

    copied = 0
    total_bytes = 0
    seen: set[str] = set()
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

def main() -> None:
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
