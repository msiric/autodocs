#!/usr/bin/env python3
"""Deterministic sync engine for autodocs.

Replaces the LLM sync call with pure Python. Fetches PRs, classifies by
file path matching, extracts diffs, and writes daily-report.md + activity-log.md.

The only part that still needs an LLM is telemetry (Kusto queries) — handled
separately by the orchestrator if configured.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

# Files to skip during diff analysis (noise)
NOISE_PATTERNS = {
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "*.test.*", "*.spec.*", "*.generated.*", "*.min.*", "*.map", "*.d.ts",
}
NOISE_DIRS = {"dist/", "build/", ".next/", "out/", "node_modules/", "vendor/", ".venv/", "__pycache__/"}

DIFF_BUDGET_PER_PR = 150  # max diff lines per PR


# ---------------------------------------------------------------------------
# PR fetching (multi-platform)
# ---------------------------------------------------------------------------

def fetch_prs(config: dict, output_dir: Path, lookback: str) -> list[dict] | None:
    """Fetch merged PRs from the platform. Returns list of PR dicts, or None on failure."""
    platform = config.get("platform", "")

    if platform == "github":
        return _fetch_github(output_dir, config, lookback)
    if platform == "gitlab":
        return _fetch_gitlab(config, lookback)
    if platform == "bitbucket":
        return _fetch_bitbucket(config, lookback)
    if platform == "ado":
        return _fetch_ado(config, lookback)
    return None


def _fetch_github(output_dir: Path, config: dict, lookback: str) -> list[dict] | None:
    """Read pre-fetched GitHub PRs (already fetched by orchestrator)."""
    prefetch = output_dir / "fetched-prs.json"
    if prefetch.exists():
        try:
            raw = json.loads(prefetch.read_text())
        except (json.JSONDecodeError, ValueError):
            return None
        return [_normalize_github_pr(pr) for pr in raw if _in_window(pr.get("mergedAt", ""), lookback)]
    # Fallback: fetch directly
    owner = config.get("github", {}).get("owner", "")
    repo = config.get("github", {}).get("repo", "")
    if not owner or not repo:
        return None
    result = subprocess.run(
        ["gh", "pr", "list", "-R", f"{owner}/{repo}", "--state", "merged",
         "--search", f"merged:>={lookback}",
         "--json", "number,title,body,mergedAt,mergeCommit,files,author,reviews",
         "--limit", "1000"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return [_normalize_github_pr(pr) for pr in raw if _in_window(pr.get("mergedAt", ""), lookback)]


def _normalize_github_pr(pr: dict) -> dict:
    body = pr.get("body") or ""
    return {
        "number": pr.get("number", 0),
        "title": _sanitize_title(pr.get("title", "")),
        "description": body[:500] + ("..." if len(body) > 500 else ""),
        "author": pr.get("author", {}).get("login", ""),
        "merged_at": pr.get("mergedAt", ""),
        "merge_commit": (pr.get("mergeCommit") or {}).get("oid", ""),
        "files": [{"path": f.get("path", ""), "additions": f.get("additions", 0),
                   "deletions": f.get("deletions", 0)}
                  for f in (pr.get("files") or [])],
        "reviews": pr.get("reviews") or [],
    }


def _fetch_gitlab(config: dict, lookback: str) -> list[dict] | None:
    project = config.get("gitlab", {}).get("project_path", "")
    if not project:
        return None
    result = subprocess.run(
        ["glab", "mr", "list", "--merged", "-F", "json", "-R", project,
         "--updated-after", lookback, "--per-page", "100"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    prs = []
    for mr in raw:
        if not _in_window(mr.get("merged_at", ""), lookback):
            continue
        desc = mr.get("description") or ""
        prs.append({
            "number": mr.get("iid", 0),
            "title": _sanitize_title(mr.get("title", "")),
            "description": desc[:500] + ("..." if len(desc) > 500 else ""),
            "author": mr.get("author", {}).get("username", ""),
            "merged_at": mr.get("merged_at", ""),
            "merge_commit": mr.get("merge_commit_sha", ""),
            "files": [],
            "reviews": [],
        })
    return prs


def _fetch_bitbucket(config: dict, lookback: str) -> list[dict] | None:
    ws = config.get("bitbucket", {}).get("workspace", "")
    repo = config.get("bitbucket", {}).get("repo", "")
    token = os.environ.get("BITBUCKET_TOKEN", "")
    if not ws or not repo or not token:
        return None
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {token}",
         f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}"
         f"/pullrequests?state=MERGED&pagelen=50&sort=-updated_on"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    prs = []
    for pr in data.get("values", []):
        updated = pr.get("updated_on", "")
        if not _in_window(updated, lookback):
            continue
        desc = pr.get("description") or ""
        prs.append({
            "number": pr.get("id", 0),
            "title": _sanitize_title(pr.get("title", "")),
            "description": desc[:500] + ("..." if len(desc) > 500 else ""),
            "author": pr.get("author", {}).get("nickname", ""),
            "merged_at": updated,
            "merge_commit": (pr.get("merge_commit") or {}).get("hash", ""),
            "files": [],
            "reviews": [],
        })
    return prs


def _fetch_ado(config: dict, lookback: str) -> list[dict] | None:
    ado = config.get("ado", {})
    org, project = ado.get("org", ""), ado.get("project", "")
    if not org or not project:
        return None
    result = subprocess.run(
        ["az", "repos", "pr", "list", "--org", f"https://dev.azure.com/{org}",
         "-p", project, "--status", "completed",
         "--query", "[].{number:pullRequestId, title:title, description:description, "
                    "author:createdBy.uniqueName, mergedAt:closedDate, "
                    "mergeCommit:lastMergeCommit.commitId}",
         "-o", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    prs = []
    for pr in raw:
        if not _in_window(pr.get("mergedAt", ""), lookback):
            continue
        desc = pr.get("description") or ""
        prs.append({
            "number": pr.get("number", 0),
            "title": _sanitize_title(pr.get("title", "")),
            "description": desc[:500] + ("..." if len(desc) > 500 else ""),
            "author": pr.get("author", ""),
            "merged_at": pr.get("mergedAt", ""),
            "merge_commit": pr.get("mergeCommit", ""),
            "files": [],
            "reviews": [],
        })
    return prs


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def get_change_types(repo_dir: Path, merge_commit: str) -> list[dict]:
    """Get file change types (M/A/D/R) via git diff-tree."""
    if not merge_commit:
        return []
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-M", "-r", merge_commit],
        capture_output=True, text=True, cwd=str(repo_dir),
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            change_type = parts[0][0]  # M, A, D, or R (strip similarity %)
            path = parts[-1]  # last element is the new path for renames
            files.append({"change_type": change_type, "path": path})
    return files


def get_targeted_diffs(
    repo_dir: Path, merge_commit: str, files: list[dict], config: dict,
) -> dict[str, str]:
    """Get diffs for mapped files only, within budget. Returns {path: diff_text}."""
    if not merge_commit or not files:
        return {}

    package_map_keys = set()
    for doc in config.get("docs") or []:
        for key in (doc.get("package_map") or {}).keys():
            package_map_keys.add(key)
    exclude = set(config.get("exclude_patterns") or [])

    diffs: dict[str, str] = {}
    total_lines = 0

    for f in files:
        path = f["path"]
        if _is_noise_file(path, exclude):
            continue
        if not _is_mapped_file(path, package_map_keys):
            continue
        if total_lines >= DIFF_BUDGET_PER_PR:
            break

        result = subprocess.run(
            ["git", "diff", "-U3", f"{merge_commit}^..{merge_commit}", "--", path],
            capture_output=True, text=True, cwd=str(repo_dir),
        )
        if result.returncode == 0 and result.stdout:
            diff_lines = result.stdout.splitlines()
            remaining = DIFF_BUDGET_PER_PR - total_lines
            if len(diff_lines) > remaining:
                diff_lines = diff_lines[:remaining]
                diff_lines.append(f"... (truncated, {DIFF_BUDGET_PER_PR} line budget)")
            diffs[path] = "\n".join(diff_lines)
            total_lines += len(diff_lines)

    return diffs


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_prs(prs: list[dict], config: dict) -> list[dict]:
    """Classify PRs by file path matching. Purely deterministic."""
    relevant_paths = config.get("relevant_paths") or []
    relevant_pattern = (config.get("relevant_pattern") or "").lower()
    feature_name = config.get("feature_name", "Feature")

    for pr in prs:
        files = pr.get("change_types") or pr.get("files") or []
        file_paths = [f.get("path", "") for f in files]

        if not file_paths:
            pr["classification"] = _classify_by_fallback(pr, relevant_pattern)
            pr["classification_label"] = feature_name
            continue

        matched_prefix = ""
        for fp in file_paths:
            for rp in relevant_paths:
                if fp.startswith(rp):
                    matched_prefix = rp
                    break
            if matched_prefix:
                break

        if matched_prefix:
            pr["classification"] = "YES"
            pr["matched_prefix"] = matched_prefix
        elif relevant_pattern and any(relevant_pattern in fp.lower() for fp in file_paths):
            pr["classification"] = "MAYBE"
        else:
            pr["classification"] = "NO"
        pr["classification_label"] = feature_name

    return prs


def _classify_by_fallback(pr: dict, pattern: str) -> str:
    """Classify by title when file paths are unavailable."""
    if not pattern:
        return "NO"
    title = pr.get("title", "").lower()
    if pattern in title:
        return "MAYBE"
    return "NO"


def extract_owner_activity(prs: list[dict], config: dict) -> dict:
    """Extract owner's review and authoring activity."""
    owner_username = ""
    owner_config = config.get("owner") or {}
    for field in ("github_username", "gitlab_username", "bitbucket_username", "ado_id"):
        val = owner_config.get(field, "")
        if val:
            owner_username = val
            break

    reviewed = []
    authored = []
    for pr in prs:
        if pr.get("author") == owner_username:
            authored.append(pr["number"])
        for review in pr.get("reviews") or []:
            reviewer = review.get("author", {}).get("login", "") if isinstance(review.get("author"), dict) else ""
            if reviewer == owner_username:
                reviewed.append(pr["number"])
                break

    return {
        "name": owner_config.get("name", "Owner"),
        "reviewed": reviewed,
        "authored": authored,
    }


def filter_team_prs(prs: list[dict], config: dict) -> list[dict]:
    """Filter PRs to team members only (owner + team_members)."""
    usernames = set()
    owner = config.get("owner") or {}
    for field in ("github_username", "gitlab_username", "bitbucket_username", "ado_id"):
        val = owner.get(field, "")
        if val:
            usernames.add(val)
    for member in config.get("team_members") or []:
        for field in ("github_username", "gitlab_username", "bitbucket_username", "ado_id"):
            val = member.get(field, "")
            if val:
                usernames.add(val)

    if not usernames:
        return prs  # No filter if no usernames configured

    return [pr for pr in prs if pr.get("author") in usernames]


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_daily_report(
    output_dir: Path, today: str, prs: list[dict], owner_activity: dict,
    feature_name: str,
) -> None:
    """Write daily-report.md in the exact format downstream helpers expect."""
    feature_prs = [p for p in prs if p.get("classification") in ("YES", "MAYBE")]
    lines = [
        "---",
        f"date: {today}",
        "sync_status: success",
        f"pr_count: {len(prs)}",
        f"feature_prs: {len(feature_prs)}",
        f"owner_reviews: {len(owner_activity['reviewed'])}",
        f"owner_authored: {len(owner_activity['authored'])}",
        "anomaly_count: 0",
        "---",
        f"# Work Report — {today}",
        "",
        "## Team PRs",
    ]

    if not prs:
        lines.append("No PRs merged in the lookback window.")
    else:
        for pr in prs:
            cls = pr.get("classification", "NO")
            label = pr.get("classification_label", "Feature")
            prefix = pr.get("matched_prefix", "")

            lines.append(f'- PR #{pr["number"]}: "{pr["title"]}" by {pr["author"]} — merged')
            desc = pr.get("description", "")
            if desc:
                lines.append(f"  Description: {desc}")

            if cls == "YES" and prefix:
                lines.append(f"  {label}: YES ({prefix})")
            elif cls == "MAYBE":
                lines.append(f"  {label}: MAYBE — review")
            elif cls == "REFACTOR":
                lines.append(f"  {label}: REFACTOR")
            else:
                lines.append(f"  {label}: NO")

            # File list for YES/MAYBE PRs
            if cls in ("YES", "MAYBE"):
                change_types = pr.get("change_types") or []
                if change_types:
                    lines.append("  Files:")
                    for f in change_types:
                        lines.append(f"    {f['change_type']} {f['path']}")

                # Diffs
                diffs = pr.get("diffs") or {}
                if diffs:
                    lines.append("  Diff:")
                    for path, diff_text in diffs.items():
                        lines.append(f"    {diff_text}")

                # Review threads
                threads_summary = _format_review_threads(pr.get("reviews") or [])
                if threads_summary:
                    lines.append(f"  Threads: {threads_summary}")

    lines.extend([
        "",
        f"## Owner Activity ({owner_activity['name']})",
    ])
    if owner_activity["reviewed"]:
        reviewed_str = ", ".join(f"PR #{n}" for n in owner_activity["reviewed"])
        lines.append(f"- Reviewed: {reviewed_str}")
    if owner_activity["authored"]:
        authored_str = ", ".join(f"PR #{n}" for n in owner_activity["authored"])
        lines.append(f"- Authored/Merged: {authored_str}")
    if not owner_activity["reviewed"] and not owner_activity["authored"]:
        lines.append("- No activity in this window")

    (output_dir / "daily-report.md").write_text("\n".join(lines) + "\n")


def write_activity_log(output_dir: Path, today: str, prs: list[dict], owner_activity: dict) -> None:
    """Append to activity-log.md, trimming entries older than 14 days."""
    log_path = output_dir / "activity-log.md"

    # Build today's entry
    entry_lines = [f"## {today}"]
    if owner_activity["reviewed"]:
        for n in owner_activity["reviewed"]:
            pr = next((p for p in prs if p["number"] == n), None)
            title = pr["title"] if pr else ""
            entry_lines.append(f'- Reviewed: PR #{n} "{title}"')
    if owner_activity["authored"]:
        for n in owner_activity["authored"]:
            pr = next((p for p in prs if p["number"] == n), None)
            title = pr["title"] if pr else ""
            entry_lines.append(f'- Merged: PR #{n} "{title}"')
    entry_lines.append("- Telemetry: not configured")

    # Read existing entries (skip header)
    existing = ""
    if log_path.exists():
        text = log_path.read_text()
        # Remove header line
        lines = text.splitlines()
        start = 0
        for i, line in enumerate(lines):
            if line.startswith("## "):
                start = i
                break
        existing = "\n".join(lines[start:])

    # Trim entries older than 14 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    trimmed_lines = []
    include = True
    for line in existing.splitlines():
        date_match = re.match(r"## (\d{4}-\d{2}-\d{2})", line)
        if date_match:
            include = date_match.group(1) >= cutoff
        if include:
            trimmed_lines.append(line)

    parts = ["# Activity Log", "", "\n".join(entry_lines), ""]
    if trimmed_lines:
        parts.append("\n".join(trimmed_lines))

    log_path.write_text("\n".join(parts) + "\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def deterministic_sync(
    config: dict,
    output_dir: Path,
    repo_dir: Path,
) -> bool:
    """Run deterministic sync. Returns True on success, False on platform failure."""
    today_file = output_dir / "current-date.txt"
    lookback_file = output_dir / "lookback-date.txt"
    if not today_file.exists() or not lookback_file.exists():
        return False

    today = today_file.read_text().strip()
    lookback = lookback_file.read_text().strip()
    feature_name = config.get("feature_name", "Feature")

    # Fetch PRs
    prs = fetch_prs(config, output_dir, lookback)
    if prs is None:
        _write_partial_report(output_dir, today, feature_name)
        return True  # Partial is still a success (graceful degradation)

    # Filter to team members
    prs = filter_team_prs(prs, config)

    # Get change types for each PR (git diff-tree, falling back to API file list)
    for pr in prs:
        if pr.get("merge_commit"):
            pr["change_types"] = get_change_types(repo_dir, pr["merge_commit"])
        # Fallback: use files from platform API if git diff-tree returned nothing
        if not pr.get("change_types") and pr.get("files"):
            pr["change_types"] = [
                {"change_type": "M", "path": f["path"]}
                for f in pr["files"] if f.get("path")
            ]

    # Classify
    prs = classify_prs(prs, config)

    # Get diffs for relevant PRs
    for pr in prs:
        if pr.get("classification") in ("YES", "MAYBE") and pr.get("merge_commit"):
            change_types = pr.get("change_types") or []
            pr["diffs"] = get_targeted_diffs(repo_dir, pr["merge_commit"], change_types, config)

    # Extract owner activity
    owner_activity = extract_owner_activity(prs, config)

    # Write outputs
    write_daily_report(output_dir, today, prs, owner_activity, feature_name)
    write_activity_log(output_dir, today, prs, owner_activity)

    return True


def _write_partial_report(output_dir: Path, today: str, feature_name: str) -> None:
    """Write a partial report when platform is unavailable."""
    (output_dir / "daily-report.md").write_text(
        f"---\ndate: {today}\nsync_status: partial\npr_count: 0\n"
        f"feature_prs: 0\nowner_reviews: 0\nowner_authored: 0\nanomaly_count: 0\n---\n"
        f"# Work Report — {today}\n\n## Team PRs\nPlatform unavailable — skipped\n\n"
        f"## Owner Activity\nPlatform unavailable — skipped\n"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_review_threads(reviews: list[dict]) -> str:
    """Format PR review comments into a concise summary for the daily report.

    Filters out bot reviews and empty bodies. Truncates each comment and
    caps total output. Returns empty string if no human reviews.
    """
    human_reviews = []
    for r in reviews:
        body = (r.get("body") or "").strip()
        if not body:
            continue
        author = r.get("author", {})
        login = author.get("login", "") if isinstance(author, dict) else str(author)
        # Skip bots (common patterns: name[bot], dependabot, etc.)
        if "[bot]" in login or login.endswith("-bot"):
            continue
        # Truncate individual comments
        if len(body) > 200:
            body = body[:200] + "..."
        state = r.get("state", "")
        prefix = f"({state}) " if state and state != "COMMENTED" else ""
        human_reviews.append(f"{login}: {prefix}{body}")

    if not human_reviews:
        return ""

    # Cap at 3 reviews, 500 chars total
    summary = " | ".join(human_reviews[:3])
    if len(human_reviews) > 3:
        summary += f" (+{len(human_reviews) - 3} more)"
    if len(summary) > 500:
        summary = summary[:497] + "..."
    return summary


def _in_window(date_str: str, lookback: str) -> bool:
    """Check if a date string is within the lookback window."""
    if not date_str:
        return False
    return date_str[:10] >= lookback


def _sanitize_title(title: str) -> str:
    """Sanitize PR title to prevent markdown injection."""
    title = title.replace("---", "--")
    title = title.replace("### ", "## ")
    if title.startswith("> "):
        title = "- " + title[2:]
    return title


def _is_noise_file(path: str, extra_exclude: set[str]) -> bool:
    """Check if a file should be skipped during diff analysis."""
    for d in NOISE_DIRS:
        if d in path:
            return True
    basename = path.split("/")[-1] if "/" in path else path
    for pattern in NOISE_PATTERNS:
        if pattern.startswith("*") and basename.endswith(pattern[1:]):
            return True
        if basename == pattern:
            return True
    for pattern in extra_exclude:
        if pattern in path:
            return True
    return False


def _is_mapped_file(path: str, package_map_keys: set[str]) -> bool:
    """Check if a file's directory matches a package_map key."""
    for key in package_map_keys:
        if "/" in key:
            if path.endswith(key) or key in path:
                return True
        elif f"/{key}/" in f"/{path}":
            return True
    return False
