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
import subprocess
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

    branch_prefix = config.get("auto_pr", {}).get("branch_prefix", "autodocs/")
    new_discovered = backfill_discovered(feedback, platform, repo_id, branch_prefix)

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


def _origin_ref_exists(repo_dir: Path, ref: str) -> bool:
    """Check whether a git ref (e.g., 'origin/master') exists locally."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=str(repo_dir), capture_output=True,
    )
    return result.returncode == 0


def _fetch_file_from_ref(repo_dir: Path, ref: str, path: str) -> bytes | None:
    """Fetch a file's content at a specific git ref. Returns bytes or None.

    Uses `git show <ref>:<path>`. Returns None if the file doesn't exist at
    that ref (e.g., it was deleted on origin or never existed there). Binary-
    safe — caller writes raw bytes to preserve fidelity for any file type.
    """
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=str(repo_dir), capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def copy_sources(output_dir: str | Path, repo_dir: str | Path) -> int:
    """Copy mapped source files to source-context/ for the suggest prompt.

    Fetches each file's content from origin/<target_branch> via `git show`,
    NOT from the working tree. This ensures the LLM always sees the canonical
    mainline state regardless of which branch the user has checked out.

    Falls back to the working tree if origin/<target_branch> doesn't exist
    (e.g., shallow clones, non-standard remote setups).

    Skips files with change_type 'D' (deleted) — the file no longer exists
    on the target branch, so including stale content would mislead the LLM.

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

    # Determine the canonical ref to read from
    config = load_config(output_dir)
    target_branch = (config.get("auto_pr") or {}).get("target_branch") or "main"
    ref = f"origin/{target_branch}"
    use_ref = _origin_ref_exists(repo_dir, ref)
    if not use_ref:
        print(
            f"source-context: {ref} not found locally; falling back to working tree",
            file=sys.stderr,
        )

    copied = 0
    total_bytes = 0
    seen: set[str] = set()
    for line in mappings_path.read_text().splitlines():
        m = re.match(r"([MADR])\d*\s+(\S+)\s+→\s+(.+)", line)
        if not m or m.group(3).strip() == UNMAPPED:
            continue

        change_type = m.group(1)
        src_path = m.group(2).strip()
        if src_path in seen:
            continue
        seen.add(src_path)

        # Skip deleted files — they no longer exist on the target branch.
        # Including stale content would make the LLM think old code is current.
        if change_type == "D":
            continue

        # Fetch content from origin/<target_branch> (primary) or working tree (fallback)
        content: bytes | None = None
        if use_ref:
            content = _fetch_file_from_ref(repo_dir, ref, src_path)
        if content is None:
            # Fallback: read from working tree
            full_path = repo_dir / src_path
            if full_path.exists() and full_path.is_file():
                content = full_path.read_bytes()
        if content is None:
            continue  # file unavailable in both ref and working tree

        file_size = len(content)
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
        dest.write_bytes(content)
        copied += 1
        total_bytes += file_size

    return copied


def sync_canonical_docs(output_dir: str | Path, repo_dir: str | Path) -> None:
    """Refresh output_dir's mirror of each documented file (doc + changelog)
    from origin/<target_branch>.

    The suggest LLM is sandboxed to output_dir (`add_dirs=[output_dir]`), so it
    reads doc and changelog files from there. Both are master-derived state:

      - The doc body is INPUT — the LLM compares it against current source to
        detect drift. A stale local copy means the LLM compares fresh source
        against an old doc snapshot, which produces either false positives
        (proposing edits that already shipped) or false negatives (missing
        drift the local doc happens to already describe).
      - The changelog is INPUT for `suggest_dedup` (which PRs are already
        documented?) AND output (the LLM appends new entries each run). If
        the local changelog is a pure accumulator, every autodocs PR that
        gets abandoned still leaves changelog entries locally, suppressing
        future alerts for those same PRs. Real drift gets quietly skipped.

    Sync semantics, per doc entry in `config.docs`:
      - DOC: refresh if master has it. If master does not, leave the local
        copy alone (bootstrap case — user may be staging a new doc that
        autodocs's first PR will create on master).
      - CHANGELOG: refresh if master has it. If master does not, REMOVE the
        local copy. The changelog has no bootstrap case: until autodocs
        ships a PR that adds one, master has none, and any local content is
        phantom state from abandoned runs.

    Falls back to no-op if origin/<target_branch> is unreachable (e.g.,
    shallow clones); the local files are left unchanged. Matches the
    fallback semantics of `copy_sources`.
    """
    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)

    config = load_config(output_dir)
    target_branch = (config.get("auto_pr") or {}).get("target_branch") or "main"
    ref = f"origin/{target_branch}"

    if not _origin_ref_exists(repo_dir, ref):
        print(
            f"sync-canonical-docs: {ref} not found locally; skipping refresh",
            file=sys.stderr,
        )
        return

    for doc in config.get("docs") or []:
        name = doc.get("name")
        repo_path = doc.get("repo_path")
        if not name or not repo_path:
            continue

        # Doc body: refresh from master if present; preserve local when absent.
        doc_content = _fetch_file_from_ref(repo_dir, ref, repo_path)
        if doc_content is not None:
            (output_dir / name).write_bytes(doc_content)

        # Companion changelog (`changelog-<stem>.md` next to the doc):
        # refresh from master if present; REMOVE local copy when absent.
        stem = Path(name).stem
        changelog_filename = f"changelog-{stem}.md"
        changelog_local = output_dir / changelog_filename
        changelog_repo_path = str(Path(repo_path).parent / changelog_filename)
        changelog_content = _fetch_file_from_ref(repo_dir, ref, changelog_repo_path)
        if changelog_content is not None:
            changelog_local.write_bytes(changelog_content)
        else:
            changelog_local.unlink(missing_ok=True)


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
    elif operation == "sync-canonical-docs":
        output_dir = sys.argv[2]
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else "."
        sync_canonical_docs(output_dir, repo_dir)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
