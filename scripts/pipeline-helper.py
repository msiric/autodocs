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
    sys.exit(0)


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
        return f"{ado.get('org', '')}/{ado.get('project', '')}" if ado.get("org") else None
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
    if platform == "github" and repo_id:
        output = _gh(
            ["pr", "list", "--search", "head:autodocs/ is:open",
             "--json", "number,createdAt", "--limit", "50"],
            repo_id
        )
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
        parts = repo_id.split("/")
        if len(parts) >= 2:
            output = _run_cli([
                "az", "repos", "pr", "show", "--id", str(pr_number),
                "--org", f"https://dev.azure.com/{parts[0]}",
                "-p", parts[1],
                "--query", "status", "-o", "tsv"
            ])
            if output == "completed":
                return "MERGED"
            if output == "abandoned":
                return "CLOSED"
    return None


def execute_stale_action(platform, repo_id, pr_number, action, reason):
    """Execute a stale PR action (warn or close)."""
    if platform == "github" and repo_id:
        if action == "warn":
            _gh(["pr", "comment", str(pr_number), "--body",
                 f"**autodocs**: {reason}. This PR will be auto-closed in 7 days "
                 f"if no activity. Add label `autodocs:keep-open` to prevent."],
                repo_id)
            _gh(["pr", "edit", str(pr_number), "--add-label", "autodocs:stale"],
                repo_id)
        elif action == "close":
            _gh(["pr", "comment", str(pr_number), "--body",
                 f"**autodocs**: Closing — {reason}. A fresh PR will be generated "
                 f"if changes are still needed."],
                repo_id)
            _gh(["pr", "close", str(pr_number)], repo_id)


def get_stale_labels(platform, repo_id):
    """Get PR numbers that have the autodocs:stale label."""
    labels = {}
    if platform == "github" and repo_id:
        output = _gh(
            ["pr", "list", "--label", "autodocs:stale", "--state", "open",
             "--json", "number", "--limit", "50"],
            repo_id
        )
        prs = _parse_json(output) or []
        for pr in prs:
            labels[str(pr.get("number", ""))] = True
    return labels


# ---------------------------------------------------------------------------
# Pre-sync orchestration
# ---------------------------------------------------------------------------

def pre_sync(output_dir, repo_dir, platform):
    """Run all pre-Call-1 operations. Write pre-sync-result.json."""
    output_dir = Path(output_dir)
    config = load_config(output_dir)
    repo_id = get_platform_repo(config, platform)
    feedback = load_feedback(output_dir)
    log_entries = []

    # 1. Discover existing autodocs PRs
    discovered = discover_prs(platform, repo_id)
    new_discovered = 0
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
        new_discovered += 1

    # 2. Check state of tracked open PRs
    state_updates = []
    today_str = datetime.now().strftime("%Y-%m-%d")
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

    # 3. Detect post-merge corrections
    corrections = []
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
            if not doc:
                continue
            since = pr["merged_date"]
            until = (merged_date + timedelta(days=7)).strftime("%Y-%m-%d")
            result = _run_cli([
                "git", "-C", str(repo_dir), "log", "--oneline",
                f"--since={since}", f"--until={until}",
                "--", f"docs/{doc}"
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

    # 4. Stale PR management
    stale_actions = []
    stale_config = config.get("stale_pr", {})
    warn_days = stale_config.get("warn_after_days", 14)
    close_days = stale_config.get("close_after_days", 21)
    max_actions = stale_config.get("max_actions_per_run", 5)
    stale_labels = get_stale_labels(platform, repo_id)

    # Import stale detection logic from sibling script
    stale_helper_path = Path(__file__).parent / "stale-helper.py"
    stale_results = []
    if stale_helper_path.exists():
        try:
            result = subprocess.run(
                ["python3", str(stale_helper_path),
                 str(output_dir / "feedback" / "open-prs.json"),
                 str(output_dir / "config.yaml"),
                 str(repo_dir),
                 "list-stale", today_str, json.dumps(stale_labels)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                stale_results = result.stdout.strip().splitlines()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    for line in stale_results[:max_actions]:
        parts = line.split("|")
        if len(parts) >= 3:
            pr_num, action, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
            execute_stale_action(platform, repo_id, int(pr_num), action, reason)
            if action == "close":
                for pr in feedback:
                    if pr.get("pr_number") == int(pr_num):
                        pr["state"] = "closed"
            stale_actions.append({"pr": int(pr_num), "action": action, "reason": reason})
            log_entries.append(f"STALE: {action} PR #{pr_num} ({reason})")

    # 5. Open PR limit
    open_count = sum(1 for pr in feedback if pr.get("state") == "open")
    max_open = config.get("limits", {}).get("max_open_prs", 10)

    # Save updated feedback
    save_feedback(output_dir, feedback)

    # Write result
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

def copy_sources(output_dir, repo_dir):
    """Copy mapped source files to source-context/ for suggest prompt."""
    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)
    source_dir = output_dir / "source-context"
    source_dir.mkdir(exist_ok=True)

    # Clear previous files
    for f in source_dir.iterdir():
        if f.is_file():
            f.unlink()

    # Read resolved mappings
    mappings_path = output_dir / "resolved-mappings.md"
    if not mappings_path.exists():
        return

    # Extract unique mapped file paths (exclude UNMAPPED)
    copied = 0
    seen = set()
    for line in mappings_path.read_text().splitlines():
        m = re.match(r"[MADR]\d*\s+(\S+)\s+→\s+(.+)", line)
        if m and m.group(2).strip() != "UNMAPPED":
            src_path = m.group(1).strip()
            if src_path in seen:
                continue
            seen.add(src_path)
            full_path = repo_dir / src_path
            if full_path.exists():
                # Copy to source-context/ (flat — just the filename)
                import shutil
                shutil.copy2(full_path, source_dir / full_path.name)
                copied += 1

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
