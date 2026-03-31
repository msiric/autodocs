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
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _http_get_json(url: str, token: str) -> dict | list | None:
    """HTTP GET with Bearer auth. Returns parsed JSON or None on failure.

    Uses urllib instead of curl subprocess to avoid leaking the token
    in the process list (visible via ps aux on shared systems).
    """
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def _http_post_json(url: str, token: str, body: dict) -> dict | None:
    """HTTP POST with Bearer auth. Returns parsed JSON or None on failure."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


@dataclass
class FetchResult:
    """Result of a PR fetch operation."""
    prs: list[dict] | None = None   # None = failed
    error: str | None = None         # Human-readable error message
    retryable: bool = False          # Whether a retry might help


# PR classification labels
CLASS_YES = "YES"       # PR definitely relevant (path match)
CLASS_MAYBE = "MAYBE"   # PR possibly relevant (pattern match)
CLASS_NO = "NO"         # PR not relevant

# Files to skip during diff analysis (noise)
NOISE_PATTERNS = {
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "*.test.*", "*.spec.*", "*.generated.*", "*.min.*", "*.map", "*.d.ts",
}
NOISE_DIRS = {"dist/", "build/", ".next/", "out/", "node_modules/", "vendor/", ".venv/", "__pycache__/"}

DIFF_BUDGET_PER_PR = 150   # max diff lines per PR
DESC_MAX_CHARS = 500       # max PR description length
REVIEW_MAX_CHARS = 200     # max chars per review comment
REVIEW_MAX_COUNT = 3       # max review comments shown
REVIEW_SUMMARY_MAX = 500   # max total review summary length


def _truncate_desc(text: str) -> str:
    """Truncate PR description to DESC_MAX_CHARS."""
    if len(text) <= DESC_MAX_CHARS:
        return text
    return text[:DESC_MAX_CHARS] + "..."


# ---------------------------------------------------------------------------
# PR discovery (git-first, universal across all platforms)
# ---------------------------------------------------------------------------

# Patterns to extract PR/MR numbers from merge commit messages.
# Order matters: try most specific patterns first.
PR_NUMBER_PATTERNS = [
    re.compile(r"Merge pull request #(\d+)"),      # GitHub merge
    re.compile(r"Merged PR (\d+)"),                 # ADO (all strategies)
    re.compile(r"\(pull request #(\d+)\)"),          # Bitbucket
    re.compile(r"(?<!\d)!(\d+)\b"),                    # GitLab (See merge request ...!NNN)
    re.compile(r"\(#(\d+)\)"),                       # GitHub squash
]


def expand_relevant_paths(repo_dir: Path, relevant_paths: list[str]) -> list[str]:
    """Expand glob patterns in relevant_paths against the repo filesystem.

    Exact paths pass through unchanged. Paths containing '*' or '?' are
    expanded using glob. This allows configs like:
        packages/components/components-channel-pages-*/
    which automatically includes new packages matching the pattern.
    """
    expanded: list[str] = []
    seen: set[str] = set()

    repo_resolved = repo_dir.resolve()
    for rp in relevant_paths:
        if "*" in rp or "?" in rp:
            # Glob pattern — expand against filesystem
            for match in sorted(repo_dir.glob(rp.rstrip("/"))):
                # Validate expanded path stays within repo (prevent traversal)
                if not str(match.resolve()).startswith(str(repo_resolved)):
                    continue
                try:
                    rel = str(match.relative_to(repo_dir))
                except ValueError:
                    continue
                if rel in seen:
                    continue
                if match.is_dir():
                    expanded.append(rel + "/")
                    seen.add(rel)
                elif match.is_file():
                    expanded.append(rel)
                    seen.add(rel)
        else:
            if rp not in seen:
                expanded.append(rp)
                seen.add(rp)

    return expanded


def discover_cross_cutting_files(
    repo_dir: Path,
    config: dict,
) -> list[str]:
    """Discover files in cross-cutting packages that reference the tracked feature.

    Greps cross_cutting_packages for cross_cutting_identifiers at runtime.
    Returns repo-relative file paths. This eliminates the need for a static
    file list — new integration points are discovered automatically.
    """
    packages = config.get("cross_cutting_packages") or []
    identifiers = config.get("cross_cutting_identifiers") or []
    if not packages or not identifiers:
        return []

    # Build search directories (only existing ones)
    search_dirs = []
    for pkg in packages:
        pkg_path = repo_dir / pkg.rstrip("/")
        if pkg_path.is_dir():
            search_dirs.append(str(pkg_path))
    if not search_dirs:
        return []

    # grep -rl with fixed strings (-F) — no regex escaping needed
    grep_cmd = ["grep", "-rlF"]
    for ident in identifiers:
        grep_cmd.extend(["-e", ident])
    grep_cmd.extend(search_dirs)
    result = subprocess.run(grep_cmd, capture_output=True, text=True)
    if result.returncode not in (0, 1):  # 1 = no matches (not an error)
        return []

    skip = {".test.", ".spec.", "__tests__", "__generated__", "node_modules"}
    files: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        if any(s in line for s in skip):
            continue
        try:
            rel = str(Path(line).relative_to(repo_dir))
        except ValueError:
            continue
        if rel not in seen:
            files.append(rel)
            seen.add(rel)

    return sorted(files)


def discover_prs_from_git(
    repo_dir: Path,
    relevant_paths: list[str],
    lookback: str,
) -> list[dict]:
    """Discover merged PRs that touched relevant paths via git log.

    Uses the local git history — works identically across all platforms.
    Returns [{number, merge_commit, merged_at}] with minimal data.
    Supports glob patterns in relevant_paths (expanded before use).
    """
    if not relevant_paths:
        return []

    # git log --first-parent: follow only the main branch lineage
    # -- paths: only commits that touched these paths
    # Use a delimiter to separate commits (body can span multiple lines).
    # This is needed for GitLab where the MR number is in the body,
    # not the subject: "See merge request group/project!99"
    DELIM = "---AUTODOCS-COMMIT---"
    cmd = [
        "git", "log", "--first-parent",
        f"--since={lookback}",
        f"--format={DELIM}%n%H %aI%n%B",  # delimiter, hash+date, full message
        "--",
    ] + relevant_paths

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_dir))
    if result.returncode != 0:
        return []

    prs: list[dict] = []
    seen_numbers: set[int] = set()

    for block in result.stdout.split(DELIM):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if not lines:
            continue

        # First line: hash + date
        header_parts = lines[0].split(" ", 1)
        if len(header_parts) < 2:
            continue
        commit_hash = header_parts[0]
        date_str = header_parts[1][:10]  # YYYY-MM-DD

        # Remaining lines: full commit message (subject + body)
        full_message = "\n".join(lines[1:]) if len(lines) > 1 else ""
        subject = lines[1] if len(lines) > 1 else ""

        # Extract PR number from full message (checks subject first, then body)
        pr_number = _extract_pr_number(full_message)
        if not pr_number or pr_number in seen_numbers:
            continue
        seen_numbers.add(pr_number)

        prs.append({
            "number": pr_number,
            "merge_commit": commit_hash,
            "merged_at": date_str,
            "title": _sanitize_title(subject),
            "description": "",
            "author": "",
            "files": [],
            "reviews": [],
        })

    return prs


def _extract_pr_number(subject: str) -> int | None:
    """Extract PR/MR number from a commit message subject line."""
    for pattern in PR_NUMBER_PATTERNS:
        m = pattern.search(subject)
        if m:
            return int(m.group(1))
    return None


def fetch_pr_details(config: dict, pr_number: int) -> dict | None:
    """Fetch title, description, author for a single PR from platform API.

    Best-effort: returns None if the CLI is unavailable or the call fails.
    The pipeline can proceed with git-only data (number, files, diffs).
    """
    platform = config.get("platform", "")

    if platform == "github":
        owner = config.get("github", {}).get("owner", "")
        repo = config.get("github", {}).get("repo", "")
        if not owner or not repo:
            return None
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}",
                 "--jq", '{title: .title, body: .body, author: .user.login}'],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return {
                "title": _sanitize_title(data.get("title", "")),
                "description": _truncate_desc(data.get("body") or ""),
                "author": data.get("author", ""),
            }
        except (json.JSONDecodeError, ValueError):
            return None

    if platform == "ado":
        ado = config.get("ado", {})
        org, project = ado.get("org", ""), ado.get("project", "")
        if not org or not project:
            return None
        try:
            result = subprocess.run(
                ["az", "repos", "pr", "show", "--id", str(pr_number),
                 "--org", f"https://dev.azure.com/{org}", "-p", project,
                 "--query", "{title:title, description:description, author:createdBy.uniqueName}",
                 "-o", "json"],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return {
                "title": _sanitize_title(data.get("title", "")),
                "description": _truncate_desc(data.get("description") or ""),
                "author": data.get("author", ""),
            }
        except (json.JSONDecodeError, ValueError):
            return None

    if platform == "gitlab":
        project_path = config.get("gitlab", {}).get("project_path", "")
        if not project_path:
            return None
        encoded = project_path.replace("/", "%2F")
        try:
            result = subprocess.run(
                ["glab", "api", f"projects/{encoded}/merge_requests/{pr_number}"],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return {
                "title": _sanitize_title(data.get("title", "")),
                "description": _truncate_desc(data.get("description") or ""),
                "author": data.get("author", {}).get("username", ""),
            }
        except (json.JSONDecodeError, ValueError):
            return None

    if platform == "bitbucket":
        ws = config.get("bitbucket", {}).get("workspace", "")
        repo = config.get("bitbucket", {}).get("repo", "")
        token = os.environ.get("BITBUCKET_TOKEN", "")
        if not ws or not repo or not token:
            return None
        data = _http_get_json(
            f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}/pullrequests/{pr_number}",
            token,
        )
        if not data or not isinstance(data, dict):
            return None
        return {
            "title": _sanitize_title(data.get("title", "")),
            "description": _truncate_desc(data.get("description") or ""),
            "author": data.get("author", {}).get("nickname", ""),
        }

    return None


# ---------------------------------------------------------------------------
# PR fetching — platform API (fallback when git discovery returns nothing)
# ---------------------------------------------------------------------------

def fetch_prs(config: dict, output_dir: Path, lookback: str) -> FetchResult:
    """Fetch merged PRs from the platform API. Used as fallback."""
    platform = config.get("platform", "")

    if platform == "github":
        return _fetch_github(output_dir, config, lookback)
    if platform == "gitlab":
        return _fetch_gitlab(config, lookback)
    if platform == "bitbucket":
        return _fetch_bitbucket(config, lookback)
    if platform == "ado":
        return _fetch_ado(config, lookback)
    return FetchResult(error=f"unknown platform: {platform}")


def _fetch_github(output_dir: Path, config: dict, lookback: str) -> FetchResult:
    """Read pre-fetched GitHub PRs (already fetched by orchestrator)."""
    prefetch = output_dir / "fetched-prs.json"
    if prefetch.exists():
        try:
            raw = json.loads(prefetch.read_text())
        except (json.JSONDecodeError, ValueError):
            return FetchResult(error="fetched-prs.json is malformed JSON")
        prs = [_normalize_github_pr(pr) for pr in raw if _in_window(pr.get("mergedAt", ""), lookback)]
        return FetchResult(prs=prs)
    # Fallback: fetch directly
    owner = config.get("github", {}).get("owner", "")
    repo = config.get("github", {}).get("repo", "")
    if not owner or not repo:
        return FetchResult(error="github.owner and github.repo required in config")
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "-R", f"{owner}/{repo}", "--state", "merged",
             "--search", f"merged:>={lookback}",
             "--json", "number,title,body,mergedAt,mergeCommit,files,author,reviews",
             "--limit", "1000"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return FetchResult(error="gh CLI not found. Install: https://cli.github.com/", retryable=False)
    if result.returncode != 0:
        return _classify_cli_error("gh", result)
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return FetchResult(error="gh returned malformed JSON")
    prs = [_normalize_github_pr(pr) for pr in raw if _in_window(pr.get("mergedAt", ""), lookback)]
    return FetchResult(prs=prs)


def _normalize_github_pr(pr: dict) -> dict:
    body = pr.get("body") or ""
    return {
        "number": pr.get("number", 0),
        "title": _sanitize_title(pr.get("title", "")),
        "description": _truncate_desc(body),
        "author": pr.get("author", {}).get("login", ""),
        "merged_at": pr.get("mergedAt", ""),
        "merge_commit": (pr.get("mergeCommit") or {}).get("oid", ""),
        "files": [{"path": f.get("path", ""), "additions": f.get("additions", 0),
                   "deletions": f.get("deletions", 0)}
                  for f in (pr.get("files") or [])],
        "reviews": pr.get("reviews") or [],
    }


def _fetch_gitlab(config: dict, lookback: str) -> FetchResult:
    project = config.get("gitlab", {}).get("project_path", "")
    if not project:
        return FetchResult(error="gitlab.project_path required in config")
    try:
        result = subprocess.run(
            ["glab", "mr", "list", "--merged", "-F", "json", "-R", project,
             "--updated-after", lookback, "--per-page", "100"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return FetchResult(error="glab CLI not found. Install: https://gitlab.com/gitlab-org/cli", retryable=False)
    if result.returncode != 0:
        return _classify_cli_error("glab", result)
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return FetchResult(error="glab returned malformed JSON")
    prs = []
    for mr in raw:
        if not _in_window(mr.get("merged_at", ""), lookback):
            continue
        desc = mr.get("description") or ""
        prs.append({
            "number": mr.get("iid", 0),
            "title": _sanitize_title(mr.get("title", "")),
            "description": _truncate_desc(desc),
            "author": mr.get("author", {}).get("username", ""),
            "merged_at": mr.get("merged_at", ""),
            "merge_commit": mr.get("merge_commit_sha", ""),
            "files": [],
            "reviews": [],
        })
    return FetchResult(prs=prs)


def _fetch_bitbucket(config: dict, lookback: str) -> FetchResult:
    ws = config.get("bitbucket", {}).get("workspace", "")
    repo = config.get("bitbucket", {}).get("repo", "")
    token = os.environ.get("BITBUCKET_TOKEN", "")
    if not ws or not repo:
        return FetchResult(error="bitbucket.workspace and bitbucket.repo required in config")
    if not token:
        return FetchResult(error="BITBUCKET_TOKEN environment variable not set")
    data = _http_get_json(
        f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}"
        f"/pullrequests?state=MERGED&pagelen=50&sort=-updated_on",
        token,
    )
    if data is None:
        return FetchResult(error="Bitbucket API request failed", retryable=True)
    if not isinstance(data, dict):
        return FetchResult(error="Bitbucket API returned malformed JSON")
    prs = []
    for pr in data.get("values", []):
        updated = pr.get("updated_on", "")
        if not _in_window(updated, lookback):
            continue
        desc = pr.get("description") or ""
        prs.append({
            "number": pr.get("id", 0),
            "title": _sanitize_title(pr.get("title", "")),
            "description": _truncate_desc(desc),
            "author": pr.get("author", {}).get("nickname", ""),
            "merged_at": updated,
            "merge_commit": (pr.get("merge_commit") or {}).get("hash", ""),
            "files": [],
            "reviews": [],
        })
    return FetchResult(prs=prs)


def _fetch_ado(config: dict, lookback: str) -> FetchResult:
    ado = config.get("ado", {})
    org, project = ado.get("org", ""), ado.get("project", "")
    if not org or not project:
        return FetchResult(error="ado.org and ado.project required in config")
    try:
        result = subprocess.run(
            ["az", "repos", "pr", "list", "--org", f"https://dev.azure.com/{org}",
             "-p", project, "--status", "completed",
             "--query", "[].{number:pullRequestId, title:title, description:description, "
                        "author:createdBy.uniqueName, mergedAt:closedDate, "
                        "mergeCommit:lastMergeCommit.commitId}",
             "-o", "json"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return FetchResult(error="az CLI not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli", retryable=False)
    if result.returncode != 0:
        return _classify_cli_error("az", result)
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return FetchResult(error="az returned malformed JSON")
    prs = []
    for pr in raw:
        if not _in_window(pr.get("mergedAt", ""), lookback):
            continue
        desc = pr.get("description") or ""
        prs.append({
            "number": pr.get("number", 0),
            "title": _sanitize_title(pr.get("title", "")),
            "description": _truncate_desc(desc),
            "author": pr.get("author", ""),
            "merged_at": pr.get("mergedAt", ""),
            "merge_commit": pr.get("mergeCommit", ""),
            "files": [],
            "reviews": [],
        })
    return FetchResult(prs=prs)


def _classify_cli_error(cli_name: str, result: subprocess.CompletedProcess) -> FetchResult:
    """Classify a CLI error as retryable (network) or permanent (auth, config)."""
    stderr = (result.stderr or "").strip()[:200]
    lower = stderr.lower()
    retryable = any(w in lower for w in ("timeout", "connection", "network", "temporary", "503", "502"))
    return FetchResult(
        error=f"{cli_name} failed (exit {result.returncode}): {stderr}" if stderr
              else f"{cli_name} failed (exit {result.returncode})",
        retryable=retryable,
    )


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
    """Get diffs for relevant PR files within budget. Returns {path: diff_text}.

    Includes ALL files from relevant_paths (not just package_map keys) so that
    new packages/files introduced in a PR are visible to drift detection.
    Mapped files are prioritized; unmapped-but-relevant files fill remaining budget.
    """
    if not merge_commit or not files:
        return {}

    package_map_keys = set()
    for doc in config.get("docs") or []:
        for key in (doc.get("package_map") or {}).keys():
            package_map_keys.add(key)
    relevant_paths = config.get("relevant_paths") or []
    exclude = set(config.get("exclude_patterns") or [])

    # Separate into mapped (priority) and unmapped-but-relevant (secondary)
    mapped_files: list[str] = []
    unmapped_files: list[str] = []
    for f in files:
        path = f["path"]
        if _is_noise_file(path, exclude):
            continue
        if _is_mapped_file(path, package_map_keys):
            mapped_files.append(path)
        elif _is_relevant_file(path, relevant_paths):
            unmapped_files.append(path)

    diffs: dict[str, str] = {}
    total_lines = 0

    # Mapped files first (known doc sections), then unmapped-but-relevant
    for path in mapped_files + unmapped_files:
        if total_lines >= DIFF_BUDGET_PER_PR:
            break
        diff_text = _get_file_diff(repo_dir, merge_commit, path)
        if diff_text:
            diff_lines = diff_text.splitlines()
            remaining = DIFF_BUDGET_PER_PR - total_lines
            if len(diff_lines) > remaining:
                diff_lines = diff_lines[:remaining]
                diff_lines.append(f"... (truncated, {DIFF_BUDGET_PER_PR} line budget)")
            diffs[path] = "\n".join(diff_lines)
            total_lines += len(diff_lines)

    return diffs


def _get_file_diff(repo_dir: Path, merge_commit: str, path: str) -> str | None:
    """Get diff for a single file from a merge commit."""
    result = subprocess.run(
        ["git", "diff", "-U3", f"{merge_commit}^..{merge_commit}", "--", path],
        capture_output=True, text=True, cwd=str(repo_dir),
    )
    return result.stdout if result.returncode == 0 and result.stdout else None


def _is_relevant_file(path: str, relevant_paths: list[str]) -> bool:
    """Check if a file matches any relevant_paths entry (directory or exact file)."""
    for rp in relevant_paths:
        if rp.endswith("/"):
            # Directory prefix — must match with the separator
            if path.startswith(rp):
                return True
        else:
            # Exact file path or directory without trailing slash
            if path == rp or path.startswith(rp + "/"):
                return True
    return False


# ---------------------------------------------------------------------------
# Review comment fetching (per-PR, for relevant PRs only)
# ---------------------------------------------------------------------------

def fetch_review_comments(config: dict, pr_number: int) -> list[dict]:
    """Fetch review comments for a single PR. Returns list of {body, state, author}."""
    platform = config.get("platform", "")

    if platform == "github":
        return _fetch_github_reviews(config, pr_number)
    if platform == "gitlab":
        return _fetch_gitlab_notes(config, pr_number)
    if platform == "bitbucket":
        return _fetch_bitbucket_comments(config, pr_number)
    if platform == "ado":
        return _fetch_ado_threads(config, pr_number)
    return []


def _fetch_github_reviews(config: dict, pr_number: int) -> list[dict]:
    """Fetch GitHub PR reviews via gh CLI."""
    owner = config.get("github", {}).get("owner", "")
    repo = config.get("github", {}).get("repo", "")
    if not owner or not repo:
        return []
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
         "--jq", '[.[] | {body, state, author: .user.login}]'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    return [{"body": r.get("body", ""), "state": r.get("state", ""),
             "author": {"login": r.get("author", "")}} for r in raw]


def _fetch_gitlab_notes(config: dict, mr_iid: int) -> list[dict]:
    """Fetch GitLab MR notes via glab CLI."""
    project = config.get("gitlab", {}).get("project_path", "")
    if not project:
        return []
    # URL-encode the project path for the API
    encoded = project.replace("/", "%2F")
    result = subprocess.run(
        ["glab", "api", f"projects/{encoded}/merge_requests/{mr_iid}/notes",
         "--paginate"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    try:
        raw = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    reviews = []
    for note in raw:
        # Skip system-generated notes (merge notifications, label changes, etc.)
        if note.get("system", False):
            continue
        body = note.get("body", "").strip()
        if not body:
            continue
        author = note.get("author", {})
        reviews.append({
            "body": body,
            "state": "COMMENTED",
            "author": {"login": author.get("username", "")},
        })
    return reviews


def _fetch_bitbucket_comments(config: dict, pr_id: int) -> list[dict]:
    """Fetch Bitbucket PR comments via REST API."""
    ws = config.get("bitbucket", {}).get("workspace", "")
    repo = config.get("bitbucket", {}).get("repo", "")
    token = os.environ.get("BITBUCKET_TOKEN", "")
    if not ws or not repo or not token:
        return []
    data = _http_get_json(
        f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}"
        f"/pullrequests/{pr_id}/comments?pagelen=50",
        token,
    )
    if not data or not isinstance(data, dict):
        return []
    reviews = []
    for comment in data.get("values", []):
        body = (comment.get("content", {}).get("raw", "") or "").strip()
        if not body:
            continue
        user = comment.get("user", {})
        reviews.append({
            "body": body,
            "state": "COMMENTED",
            "author": {"login": user.get("nickname", user.get("display_name", ""))},
        })
    return reviews


def _fetch_ado_threads(config: dict, pr_id: int) -> list[dict]:
    """Fetch ADO PR threads via az CLI."""
    ado = config.get("ado", {})
    org, project = ado.get("org", ""), ado.get("project", "")
    repo_name = ado.get("repo_id") or ado.get("repo", "")
    if not org or not project:
        return []
    result = subprocess.run(
        ["az", "rest", "--method", "get",
         "--uri", f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/"
                  f"{repo_name}/pullRequests/{pr_id}/threads?api-version=7.1"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    reviews = []
    for thread in data.get("value", []):
        for comment in thread.get("comments", []):
            # Skip system-generated comments
            if comment.get("commentType") == "system":
                continue
            body = (comment.get("content", "") or "").strip()
            if not body:
                continue
            author = comment.get("author", {})
            reviews.append({
                "body": body,
                "state": "COMMENTED",
                "author": {"login": author.get("displayName", author.get("uniqueName", ""))},
            })
    return reviews


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
            pr["classification"] = CLASS_YES
            pr["matched_prefix"] = matched_prefix
        elif relevant_pattern and any(relevant_pattern in fp.lower() for fp in file_paths):
            pr["classification"] = CLASS_MAYBE
        else:
            pr["classification"] = CLASS_NO
        pr["classification_label"] = feature_name

    return prs


def _classify_by_fallback(pr: dict, pattern: str) -> str:
    """Classify by title when file paths are unavailable."""
    if not pattern:
        return CLASS_NO
    title = pr.get("title", "").lower()
    if pattern in title:
        return CLASS_MAYBE
    return CLASS_NO


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

    return [pr for pr in prs
            if pr.get("author") in usernames
            or pr.get("classification") == CLASS_YES]  # git-discovered PRs: already path-filtered


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_daily_report(
    output_dir: Path, today: str, prs: list[dict], owner_activity: dict,
    feature_name: str,
) -> None:
    """Write daily-report.md in the exact format downstream helpers expect."""
    feature_prs = [p for p in prs if p.get("classification") in (CLASS_YES, CLASS_MAYBE)]
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
            cls = pr.get("classification", CLASS_NO)
            label = pr.get("classification_label", "Feature")
            prefix = pr.get("matched_prefix", "")

            lines.append(f'- PR #{pr["number"]}: "{pr["title"]}" by {pr["author"]} — merged')
            desc = pr.get("description", "")
            if desc:
                lines.append(f"  Description: {desc}")

            if cls == CLASS_YES and prefix:
                lines.append(f"  {label}: YES ({prefix})")
            elif cls == CLASS_MAYBE:
                lines.append(f"  {label}: MAYBE — review")
            elif cls == "REFACTOR":
                lines.append(f"  {label}: REFACTOR")
            else:
                lines.append(f"  {label}: NO")

            # File list for YES/MAYBE PRs
            if cls in (CLASS_YES, CLASS_MAYBE):
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

    raw_paths = config.get("relevant_paths") or []
    owned_paths = expand_relevant_paths(repo_dir, raw_paths)
    cross_cutting_files = discover_cross_cutting_files(repo_dir, config)
    relevant_paths = owned_paths + cross_cutting_files
    # Use combined paths throughout (discovery, diffs, etc.)
    config = {**config, "relevant_paths": relevant_paths}

    # Two discovery strategies:
    # 1. With relevant_paths: git-first discovery (fast, path-filtered)
    # 2. Without relevant_paths: platform API fetch (all PRs, small repos)
    prs: list[dict] = []

    git_discovered = False
    if relevant_paths:
        prs = discover_prs_from_git(repo_dir, relevant_paths, lookback)
        if prs:
            git_discovered = True
            # Git-first PRs are already path-filtered — mark as YES.
            # classify_prs would misclassify them as NO because they lack
            # file data (git log only returns commit hash + message).
            for pr in prs:
                pr["classification"] = CLASS_YES
                pr["classification_label"] = feature_name
            # Enrich with platform API details (best-effort, parallel)
            from concurrent.futures import ThreadPoolExecutor
            def _enrich(pr: dict) -> None:
                details = fetch_pr_details(config, pr["number"])
                if details:
                    pr["title"] = details.get("title") or pr["title"]
                    pr["description"] = details.get("description") or pr["description"]
                    pr["author"] = details.get("author") or pr["author"]
            with ThreadPoolExecutor(max_workers=min(8, len(prs))) as pool:
                list(pool.map(_enrich, prs))

    if not prs:
        # Fallback: platform API fetch (no relevant_paths, shallow clone, etc.)
        result = fetch_prs(config, output_dir, lookback)
        if result.prs is None:
            _write_partial_report(output_dir, today, feature_name, result.error)
            return True
        prs = result.prs

    # Filter to team members
    prs = filter_team_prs(prs, config)

    # Classify only API-fetched PRs (git-discovered PRs are already classified)
    if not git_discovered:
        prs = classify_prs(prs, config)

    # Git operations only for relevant PRs
    for pr in prs:
        if pr.get("classification") not in (CLASS_YES, CLASS_MAYBE):
            continue

        # Get change types via git diff-tree
        if pr.get("merge_commit"):
            pr["change_types"] = get_change_types(repo_dir, pr["merge_commit"])
        if not pr.get("change_types") and pr.get("files"):
            pr["change_types"] = [
                {"change_type": "M", "path": f["path"]}
                for f in pr["files"] if f.get("path")
            ]

        # Get targeted diffs for mapped files
        if pr.get("merge_commit"):
            change_types = pr.get("change_types") or []
            pr["diffs"] = get_targeted_diffs(repo_dir, pr["merge_commit"], change_types, config)

        # Fetch review threads if not already present
        if not pr.get("reviews"):
            pr["reviews"] = fetch_review_comments(config, pr["number"])

    # Extract owner activity
    owner_activity = extract_owner_activity(prs, config)

    # Write outputs
    write_daily_report(output_dir, today, prs, owner_activity, feature_name)
    write_activity_log(output_dir, today, prs, owner_activity)

    return True


def _write_partial_report(output_dir: Path, today: str, feature_name: str, error: str | None = None) -> None:
    """Write a partial report when platform is unavailable."""
    reason = f"Platform unavailable: {error}" if error else "Platform unavailable — skipped"
    (output_dir / "daily-report.md").write_text(
        f"---\ndate: {today}\nsync_status: partial\npr_count: 0\n"
        f"feature_prs: 0\nowner_reviews: 0\nowner_authored: 0\nanomaly_count: 0\n---\n"
        f"# Work Report — {today}\n\n## Team PRs\n{reason}\n\n"
        f"## Owner Activity\n{reason}\n"
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
        if len(body) > REVIEW_MAX_CHARS:
            body = body[:REVIEW_MAX_CHARS] + "..."
        state = r.get("state", "")
        prefix = f"({state}) " if state and state != "COMMENTED" else ""
        human_reviews.append(f"{login}: {prefix}{body}")

    if not human_reviews:
        return ""

    summary = " | ".join(human_reviews[:REVIEW_MAX_COUNT])
    if len(human_reviews) > REVIEW_MAX_COUNT:
        summary += f" (+{len(human_reviews) - REVIEW_MAX_COUNT} more)"
    if len(summary) > REVIEW_SUMMARY_MAX:
        summary = summary[:REVIEW_SUMMARY_MAX - 3] + "..."
    return summary


def _in_window(date_str: str, lookback: str) -> bool:
    """Check if a date string is within the lookback window."""
    if not date_str:
        return False
    return date_str[:10] >= lookback


def _sanitize_title(title: str) -> str:
    """Sanitize PR title to prevent markdown injection in reports.

    PR titles are untrusted input that end up in markdown files.
    Strip any markdown formatting that could break document structure.
    """
    # Strip leading markdown structure characters
    title = re.sub(r"^#+\s", "", title)      # heading markers
    title = re.sub(r"^>\s", "", title)        # blockquote
    title = re.sub(r"^-{3,}", "", title)      # horizontal rules
    # Escape remaining markdown that could affect structure
    title = title.replace("|", "\\|")          # table cell breaks
    return title.strip()


def _is_noise_file(path: str, extra_exclude: set[str]) -> bool:
    """Check if a file should be skipped during diff analysis."""
    import fnmatch
    for d in NOISE_DIRS:
        if d in path:
            return True
    basename = path.split("/")[-1] if "/" in path else path
    for pattern in NOISE_PATTERNS:
        if fnmatch.fnmatch(basename, pattern):
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
