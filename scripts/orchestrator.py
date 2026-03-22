#!/usr/bin/env python3
"""Pipeline orchestrator for autodocs.

Translates the pipeline logic from sync.sh into Python. The bash wrapper
handles only lock management and PATH setup, then exec's this script.

Usage:
  python3 orchestrator.py <output_dir> <repo_dir> [--dry-run] [--since DATE [--chunk-days N]]
  python3 orchestrator.py <output_dir> <repo_dir> --structural-scan
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install: pip3 install pyyaml", file=sys.stderr)
    sys.exit(2)

from llm_runner import LLMRunner, CLIRunner, create_runner
from schema_helper import validate_config
from storage import LocalStorage
from apply_engine import deterministic_apply
from sync_engine import deterministic_sync


# ---------------------------------------------------------------------------
# Logging and metrics
# ---------------------------------------------------------------------------

class Logger:
    """Timestamped logging to sync.log + metrics to metrics.jsonl."""

    def __init__(self, output_dir: Path):
        self.log_file = output_dir / "sync.log"
        self.metrics_file = output_dir / "metrics.jsonl"
        self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def log(self, message: str) -> None:
        with open(self.log_file, "a") as f:
            f.write(f"[{self.timestamp}] {message}\n")

    def metric(self, call: str, status: str, rc: int = 0) -> None:
        entry = json.dumps({"ts": self.timestamp, "call": call, "status": status, "rc": rc})
        with open(self.metrics_file, "a") as f:
            f.write(entry + "\n")

    def rotate(self) -> None:
        """Rotate large log/metric files."""
        _rotate_if_large(self.log_file, max_bytes=102400, keep_lines=50)
        _rotate_if_large(self.metrics_file, max_bytes=512000, keep_lines=1000)


def _rotate_if_large(path: Path, max_bytes: int, keep_lines: int) -> None:
    if not path.exists():
        return
    if path.stat().st_size <= max_bytes:
        return
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[-keep_lines:]) + "\n")


# ---------------------------------------------------------------------------
# Config and platform helpers
# ---------------------------------------------------------------------------

def load_config(output_dir: Path) -> dict:
    config_path = output_dir / "config.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def read_config_key(config: dict, dotted_key: str) -> str:
    """Read a dotted key like 'github.owner' from config. Returns '' if missing."""
    v: object = config
    for k in dotted_key.split("."):
        v = v.get(k, "") if isinstance(v, dict) else ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v) if v else ""


def get_tool_allowlists(config: dict) -> tuple[str, str]:
    """Compute (sync_tools, apply_tools) based on platform."""
    platform = read_config_key(config, "platform")

    tool_map = {
        "github": (
            "Bash(gh:*),Bash(git:*),Write",
            "Read,Edit,Write,Bash(gh:*),Bash(git:*)",
        ),
        "gitlab": (
            "Bash(glab:*),Bash(git:*),Write",
            "Read,Edit,Write,Bash(glab:*),Bash(git:*)",
        ),
        "bitbucket": (
            "Bash(curl:*),Bash(git:*),Write",
            "Read,Edit,Write,Bash(curl:*),Bash(git:*)",
        ),
        "ado": (
            ",".join([
                "mcp__azure-devops__repo_list_pull_requests_by_repo_or_project",
                "mcp__azure-devops__repo_get_pull_request_by_id",
                "mcp__azure-devops__repo_list_pull_request_threads",
                "mcp__azure-devops__search_code",
                "Bash(git:*)",
                "Write",
            ]),
            ",".join([
                "Read", "Edit", "Write", "Bash(git:*)",
                "mcp__azure-devops__repo_create_pull_request",
                "mcp__azure-devops__repo_create_branch",
            ]),
        ),
    }

    if platform not in tool_map:
        return "", ""

    sync_tools, apply_tools = tool_map[platform]

    if read_config_key(config, "telemetry.enabled") == "true":
        sync_tools += ",mcp__kusto-mcp__kusto_query"

    return sync_tools, apply_tools


# ---------------------------------------------------------------------------
# Helper script runners (call existing Python helpers as functions)
# ---------------------------------------------------------------------------

def _run_helper(scripts_dir: Path, script: str, args: list[str], logger: Logger) -> bool:
    """Run a Python helper script. Returns True on success."""
    path = scripts_dir / script
    if not path.exists():
        return False
    result = subprocess.run(
        ["python3", str(path)] + args,
        capture_output=True, text=True,
    )
    if result.returncode != 0 and result.stderr:
        logger.log(f"WARN: {script} stderr: {result.stderr.strip()[:200]}")
    return result.returncode == 0


def _prefetch_github_prs(config: dict, output_dir: Path, lookback_date: str) -> None:
    """Pre-fetch merged PRs for GitHub (deterministic, no LLM).

    Skips if fetched-prs.json already exists (e.g., provided by webhook or test).
    """
    if read_config_key(config, "platform") != "github":
        return
    if (output_dir / "fetched-prs.json").exists():
        return  # Already provided externally
    owner = read_config_key(config, "github.owner")
    repo = read_config_key(config, "github.repo")
    if not owner or not repo:
        return
    result = subprocess.run(
        [
            "gh", "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "merged",
            "--search", f"merged:>={lookback_date}",
            "--json", "number,title,body,mergedAt,mergeCommit,files,author,reviews",
            "--limit", "1000",
        ],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        (output_dir / "fetched-prs.json").write_text(result.stdout)


def _compute_match_rate(output_dir: Path, logger: Logger) -> None:
    """Log match rate metric from resolved-mappings.md."""
    mappings_path = output_dir / "resolved-mappings.md"
    if not mappings_path.exists():
        return
    lines = mappings_path.read_text().splitlines()
    total = len(lines)
    unmapped = sum(1 for line in lines if "UNMAPPED" in line)
    mapped = total - unmapped
    logger.metric("match-rate", f"{mapped}/{total}")
    if total > 5 and mapped == 0:
        logger.log(f"WARN: 0/{total} files matched package_map. Check config.")


def _has_actionable_drift(output_dir: Path) -> bool:
    """Check if drift-report.md contains HIGH or CRITICAL alerts."""
    report = output_dir / "drift-report.md"
    if not report.exists():
        return False
    text = report.read_text()
    return bool(re.search(r"HIGH|CRITICAL", text))


def _has_confident_suggestions(output_dir: Path) -> bool:
    """Check if drift-suggestions.md has CONFIDENT suggestions."""
    path = output_dir / "drift-suggestions.md"
    if not path.exists():
        return False
    return "CONFIDENT" in path.read_text()


def _suggestion_count_zero(output_dir: Path) -> bool:
    """Check if drift-suggestions.md has suggestion_count: 0."""
    path = output_dir / "drift-suggestions.md"
    if not path.exists():
        return True
    return "suggestion_count: 0" in path.read_text()


def _get_acceptance_rate(scripts_dir: Path, output_dir: Path) -> str:
    """Compute acceptance rate from feedback data."""
    feedback_file = output_dir / "feedback" / "open-prs.json"
    helper = scripts_dir / "feedback-helper.py"
    if not feedback_file.exists() or not helper.exists():
        return "n/a"
    result = subprocess.run(
        ["python3", str(helper), str(feedback_file), "acceptance-rate"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "n/a"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

INTERMEDIATE_FILES = [
    "daily-report.md", "resolved-mappings.md", "drift-context.json",
    "drift-report.md", "suggest-context.json", "drift-suggestions.md",
    "drift-suggestions-verify.md", "verified-suggestions.json",
    "replace-verification.json", "pre-sync-result.json",
    "current-date.txt", "lookback-date.txt",
    # Note: fetched-prs.json is NOT cleaned — it may be provided externally
    # (by webhook, test, or a previous prefetch). It gets overwritten by
    # _prefetch_github_prs if not already present.
]


class Orchestrator:
    """Runs the autodocs pipeline: sync → drift → suggest → verify → apply."""

    def __init__(
        self,
        output_dir: Path,
        repo_dir: Path,
        config: dict,
        runner: LLMRunner,
        logger: Logger,
        scripts_dir: Path,
        dry_run: bool = False,
        storage: LocalStorage | None = None,
    ):
        self.output_dir = output_dir
        self.repo_dir = repo_dir
        self.config = config
        self.runner = runner
        self.logger = logger
        self.scripts_dir = scripts_dir
        self.dry_run = dry_run
        self.storage = storage or LocalStorage(output_dir)

        self.sync_tools, self.apply_tools = get_tool_allowlists(config)
        self.platform = read_config_key(config, "platform")

        # Per-run status
        self.status = {
            "sync": "failed", "drift": "skipped", "suggest": "skipped",
            "verify": "skipped", "apply": "skipped",
        }

    def run_pipeline(self) -> dict[str, str]:
        """Single pipeline cycle. Returns status dict."""
        self._clean_intermediate_files()
        lookback = self._compute_lookback_dates()
        _prefetch_github_prs(self.config, self.output_dir, lookback)

        # Call 1: Sync
        if not self._run_sync():
            return self.status

        self._run_match_helper()
        _compute_match_rate(self.output_dir, self.logger)
        self._run_drift_preprocess()

        # Call 2: Drift
        self._run_drift()

        # Call 3: Suggest (only if actionable drift)
        if self.status["drift"] == "success" and _has_actionable_drift(self.output_dir):
            self._run_suggest_pipeline()

        return self.status

    # -- Cleanup --

    def _clean_intermediate_files(self) -> None:
        for f in INTERMEDIATE_FILES:
            (self.output_dir / f).unlink(missing_ok=True)
        source_ctx = self.output_dir / "source-context"
        if source_ctx.exists():
            shutil.rmtree(source_ctx)
        for bak in self.output_dir.glob("changelog-*.md.bak"):
            bak.unlink()

    # -- Date computation --

    def _compute_lookback_dates(self) -> str:
        """Compute and write current-date.txt + lookback-date.txt. Returns lookback date."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (self.output_dir / "current-date.txt").write_text(today)

        last_run_file = self.output_dir / "last-successful-run"
        if last_run_file.exists():
            lookback = last_run_file.read_text().strip()[:10]
            if lookback > today:
                self.logger.log(
                    f"WARN: last-successful-run ({lookback}) is in the future. "
                    "Resetting to 1 day ago."
                )
                lookback = _yesterday()
        else:
            lookback = _yesterday()

        (self.output_dir / "lookback-date.txt").write_text(lookback)
        return lookback

    # -- Call 1: Sync (deterministic, with LLM fallback) --

    def _run_sync(self) -> bool:
        # Try deterministic sync first (no LLM needed)
        ok = deterministic_sync(self.config, self.output_dir, self.repo_dir)
        if ok and (self.output_dir / "daily-report.md").exists():
            self.status["sync"] = "success"
            self.logger.log("SYNC SUCCESS")
            self.logger.metric("sync", "success")
            if read_config_key(self.config, "telemetry.enabled") == "true":
                self.logger.log(
                    "WARN: telemetry (Kusto) requires LLM sync (llm.backend: cli). "
                    "Deterministic sync does not run Kusto queries."
                )
            return True

        # Fallback to LLM sync (for platforms/configs deterministic sync can't handle)
        return self._run_sync_llm()

    def _run_sync_llm(self) -> bool:
        """LLM-based sync fallback (e.g., telemetry queries, ADO MCP tools)."""
        prompt_path = self.output_dir / "sync-prompt.md"
        if not prompt_path.exists():
            self.logger.log("SYNC FAILED — no sync-prompt.md and deterministic sync failed")
            self.logger.metric("sync", "failed", 1)
            return False

        rc, output = self.runner.run(
            prompt=prompt_path.read_text(),
            allowed_tools=self.sync_tools,
            add_dirs=[str(self.output_dir)],
            working_dir=str(self.repo_dir),
        )

        if rc == 0 and (self.output_dir / "daily-report.md").exists():
            self.status["sync"] = "success"
            self.logger.log("SYNC SUCCESS (LLM fallback)")
            self.logger.metric("sync", "success", rc)
            return True

        self.logger.log(f"SYNC FAILED (exit {rc})")
        self.logger.log(_tail(output, 20))
        self.logger.metric("sync", "failed", rc)
        return False

    def _run_match_helper(self) -> None:
        """Run match-helper to create resolved-mappings.md (stdout capture)."""
        helper = self.scripts_dir / "match-helper.py"
        if not helper.exists() or not (self.output_dir / "daily-report.md").exists():
            return
        result = subprocess.run(
            [
                "python3", str(helper),
                str(self.output_dir / "config.yaml"),
                "--resolve-report",
                str(self.output_dir / "daily-report.md"),
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            (self.output_dir / "resolved-mappings.md").write_text(result.stdout)
        else:
            self.logger.log("WARN: match-helper failed (file-to-section mappings unavailable)")

    def _run_drift_preprocess(self) -> None:
        if not _run_helper(
            self.scripts_dir, "drift-helper.py",
            ["pre-process", str(self.output_dir)],
            self.logger,
        ):
            self.logger.log("WARN: drift pre-process failed (LLM will fall back to raw report parsing)")

    # -- Call 2: Drift --

    def _run_drift(self) -> None:
        prompt_path = self.output_dir / "drift-prompt.md"
        if not prompt_path.exists():
            return

        rc, output = self.runner.run(
            prompt=prompt_path.read_text(),
            allowed_tools="Read,Write",
            add_dirs=[str(self.output_dir)],
            working_dir=str(self.repo_dir),
        )

        if rc == 0:
            self.status["drift"] = "success"
            self.logger.log("DRIFT SUCCESS")
        else:
            self.status["drift"] = "failed"
            self.logger.log(f"DRIFT FAILED (exit {rc})")
            self.logger.log(_tail(output, 10))
        self.logger.metric("drift", self.status["drift"], rc)

        # Post-drift lifecycle
        if self.status["drift"] == "success":
            _run_helper(
                self.scripts_dir, "drift-helper.py",
                ["apply-lifecycle", str(self.output_dir)],
                self.logger,
            )

    # -- Call 3: Suggest pipeline --

    def _run_suggest_pipeline(self) -> None:
        prompt_path = self.output_dir / "suggest-prompt.md"
        if not prompt_path.exists():
            return

        # Pre-compute suggest dedup
        _run_helper(
            self.scripts_dir, "drift-helper.py",
            ["suggest-dedup", str(self.output_dir)],
            self.logger,
        )

        # Copy source files for ground truth
        _run_helper(
            self.scripts_dir, "pipeline-helper.py",
            ["copy-sources", str(self.output_dir), str(self.repo_dir)],
            self.logger,
        )

        # Back up changelogs
        for f in self.output_dir.glob("changelog-*.md"):
            shutil.copy2(f, str(f) + ".bak")

        # Call 3: Suggest
        rc, output = self.runner.run(
            prompt=prompt_path.read_text(),
            allowed_tools="Read,Write",
            add_dirs=[str(self.output_dir)],
            working_dir=str(self.repo_dir),
        )

        if rc != 0:
            self.status["suggest"] = "failed"
            self.logger.log(f"SUGGEST FAILED (exit {rc})")
            self.logger.log(_tail(output, 10))
            self.logger.metric("suggest", "failed", rc)
            return

        self.status["suggest"] = "success"
        self.logger.log("SUGGEST SUCCESS")
        self.logger.metric("suggest", "success", rc)

        # Post-suggest: merge changelogs
        _run_helper(
            self.scripts_dir, "drift-helper.py",
            ["merge-changelogs", str(self.output_dir)],
            self.logger,
        )

        if (self.output_dir / "drift-suggestions.md").exists():
            text = (self.output_dir / "drift-suggestions.md").read_text()
            if "Verified: NO" in text:
                self.logger.log("SUGGEST WARNING: some suggestions are UNVERIFIED")

        # Deterministic verification (Python, not LLM)
        _run_helper(
            self.scripts_dir, "verify-helper.py",
            ["verify-finds", str(self.output_dir), str(self.repo_dir)],
            self.logger,
        )
        if (self.output_dir / "source-context").exists():
            _run_helper(
                self.scripts_dir, "verify-helper.py",
                ["verify-replaces", str(self.output_dir), str(self.repo_dir)],
                self.logger,
            )

        # Shadow verification (optional, log-only)
        self._run_shadow_verify()

        # Call 4: Apply
        self._run_apply()

    def _run_shadow_verify(self) -> None:
        if read_config_key(self.config, "multi_model.enabled") != "true":
            return
        if not _has_confident_suggestions(self.output_dir):
            return
        variation_path = self.output_dir / "verify-variation.md"
        suggest_path = self.output_dir / "suggest-prompt.md"
        if not variation_path.exists() or not suggest_path.exists():
            return

        rc, _ = self.runner.run(
            prompt=suggest_path.read_text(),
            allowed_tools="Read,Write",
            add_dirs=[str(self.output_dir)],
            append_system=variation_path.read_text(),
            model="opus",
            working_dir=str(self.repo_dir),
        )
        verify_status = "shadow-success" if rc == 0 else "shadow-failed"
        self.status["verify"] = verify_status
        self.logger.log(f"VERIFY (shadow): {verify_status}")
        self.logger.metric("verify-shadow", verify_status)

    # -- Call 4: Apply (deterministic, with LLM fallback) --

    def _run_apply(self) -> None:
        if self.dry_run:
            self.status["apply"] = "dry-run"
            self.logger.log("DRY RUN — skipping apply")
            return

        if read_config_key(self.config, "auto_pr.enabled") != "true":
            return
        if not (self.output_dir / "drift-suggestions.md").exists():
            return
        if _suggestion_count_zero(self.output_dir):
            return

        result = deterministic_apply(self.config, self.output_dir, self.repo_dir)
        if result.success:
            self.status["apply"] = "success"
            msg = f"APPLY SUCCESS: {len(result.applied)} applied"
            if result.pr_number:
                msg += f", PR #{result.pr_number}"
            self.logger.log(msg)
            self.logger.metric("apply", "success")
            return

        # Fallback to LLM apply
        self._run_apply_llm()

    def _run_apply_llm(self) -> None:
        """LLM-based apply fallback."""
        prompt_path = self.output_dir / "apply-prompt.md"
        if not prompt_path.exists():
            self.logger.log("APPLY FAILED — no apply-prompt.md and deterministic apply failed")
            self.logger.metric("apply", "failed", 1)
            return

        rc, output = self.runner.run(
            prompt=prompt_path.read_text(),
            allowed_tools=self.apply_tools,
            add_dirs=[str(self.output_dir), str(self.repo_dir)],
            working_dir=str(self.repo_dir),
        )

        if rc == 0:
            self.status["apply"] = "success"
            self.logger.log("APPLY SUCCESS (LLM fallback)")
        else:
            self.status["apply"] = "failed"
            self.logger.log(f"APPLY FAILED (exit {rc})")
            self.logger.log(_tail(output, 10))
        self.logger.metric("apply", self.status["apply"], rc)

    # -- Status --

    def write_status(self) -> None:
        """Write sync-status.md and advance last-successful-run timestamp."""
        acceptance = _get_acceptance_rate(self.scripts_dir, self.output_dir)

        self.storage.write("sync-status.md",
            f"status: {self.status['sync']}\n"
            f"drift: {self.status['drift']}\n"
            f"suggest: {self.status['suggest']}\n"
            f"verify: {self.status['verify']}\n"
            f"apply: {self.status['apply']}\n"
            f"acceptance_rate: {acceptance}\n"
            f"timestamp: {self.logger.timestamp}\n"
        )

        self._advance_timestamp()

    def _advance_timestamp(self) -> None:
        """Advance last-successful-run only if sync+drift succeeded with relevant PRs."""
        if self.status["sync"] != "success" or self.status["drift"] == "failed":
            return

        context_path = self.output_dir / "drift-context.json"
        relevant_count = 0
        pr_count = 0
        if context_path.exists():
            try:
                data = json.loads(context_path.read_text())
                relevant_count = data.get("summary", {}).get("relevant_count", 0)
                pr_count = data.get("summary", {}).get("pr_count", 0)
            except (json.JSONDecodeError, ValueError):
                pass

        if relevant_count > 0 or pr_count == 0:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            (self.output_dir / "last-successful-run").write_text(ts)
        else:
            self.logger.log(
                f"WARN: {pr_count} PRs found, 0 relevant. Timestamp not advanced."
            )


# ---------------------------------------------------------------------------
# Pre-sync (runs before the pipeline, handles feedback/stale/discovery)
# ---------------------------------------------------------------------------

def run_pre_sync(
    scripts_dir: Path,
    output_dir: Path,
    repo_dir: Path,
    platform: str,
    logger: Logger,
) -> bool:
    """Run pre-sync operations. Returns True if pipeline should proceed."""
    if not _run_helper(
        scripts_dir, "pipeline-helper.py",
        ["pre-sync", str(output_dir), str(repo_dir), platform],
        logger,
    ):
        logger.log("WARN: pre-sync helper failed (discovery/stale management may be incomplete)")

    result_path = output_dir / "pre-sync-result.json"
    if not result_path.exists():
        return True

    try:
        data = json.loads(result_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return True

    # Log entries from pre-sync
    for entry in data.get("log", []):
        if entry:
            logger.log(entry)

    # Check open PR limit
    if not data.get("proceed", True):
        reason = data.get("skip_reason", "unknown")
        logger.log(f"SKIPPED — {reason}")
        logger.metric("sync", "skipped-open-limit")
        return False

    return True


# ---------------------------------------------------------------------------
# Catchup mode
# ---------------------------------------------------------------------------

def run_catchup(
    output_dir: Path,
    repo_dir: Path,
    config: dict,
    runner: LLMRunner,
    logger: Logger,
    scripts_dir: Path,
    since_date: str,
    chunk_days: int,
    dry_run: bool,
) -> None:
    """Catchup mode: process historical PRs in weekly chunks."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Validate date
    try:
        datetime.strptime(since_date, "%Y-%m-%d")
    except ValueError:
        print(f"Error: invalid --since date '{since_date}'. Use YYYY-MM-DD format.", file=sys.stderr)
        sys.exit(1)
    if since_date > today:
        print(f"Error: --since date '{since_date}' is in the future.", file=sys.stderr)
        sys.exit(1)

    # Count chunks
    chunks = _compute_chunks(since_date, today, chunk_days)
    logger.log(f"CATCHUP: {len(chunks)} chunks from {since_date} to {today} ({chunk_days}-day windows)")

    if dry_run:
        print("=== autodocs catchup (dry-run) ===")
        print(f"Window: {since_date} to {today}")
        print(f"Chunks: {len(chunks)} ({chunk_days}-day windows)")
        print()
        print(f"Estimated time: ~{len(chunks) * 3} minutes ({len(chunks)} chunks × ~3 min each)")
        print()
        print("Run without --dry-run to execute.")
        return

    # Detect already-processed chunks (resumability)
    last_run_file = output_dir / "last-successful-run"
    original_last_run = ""
    if last_run_file.exists():
        original_last_run = last_run_file.read_text().strip()[:10]

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        if original_last_run and chunk_end <= original_last_run:
            logger.log(f"CATCHUP: chunk {i}/{len(chunks)} ({chunk_start} to {chunk_end}) — already processed, skipping")
            continue

        logger.log(f"CATCHUP: chunk {i}/{len(chunks)} ({chunk_start} to {chunk_end})")
        last_run_file.write_text(f"{chunk_start}T00:00:00Z")

        orch = Orchestrator(
            output_dir, repo_dir, config, runner, logger, scripts_dir, dry_run=True,
        )
        orch.run_pipeline()
        orch.write_status()

    # Final run: normal mode (creates the PR)
    logger.log("CATCHUP: final run (creating PR)")
    orch = Orchestrator(
        output_dir, repo_dir, config, runner, logger, scripts_dir, dry_run=False,
    )
    orch.run_pipeline()
    orch.write_status()


def _compute_chunks(since: str, until: str, chunk_days: int) -> list[tuple[str, str]]:
    """Compute (start, end) date pairs for chunked iteration."""
    chunks: list[tuple[str, str]] = []
    current = datetime.strptime(since, "%Y-%m-%d")
    end = datetime.strptime(until, "%Y-%m-%d")
    while current < end:
        next_date = current + timedelta(days=chunk_days)
        chunks.append((current.strftime("%Y-%m-%d"), next_date.strftime("%Y-%m-%d")))
        current = next_date
    return chunks


# ---------------------------------------------------------------------------
# Structural scan
# ---------------------------------------------------------------------------

def run_structural_scan(
    output_dir: Path,
    repo_dir: Path,
    runner: LLMRunner,
    logger: Logger,
) -> None:
    """Weekly structural scan: verify doc file references exist."""
    prompt_path = output_dir / "structural-scan-prompt.md"
    if not prompt_path.exists():
        logger.log("ERROR: structural-scan-prompt.md not found")
        return

    # Git fetch
    subprocess.run(
        ["git", "fetch", "origin", "--quiet"],
        cwd=str(repo_dir), capture_output=True,
    )

    rc, output = runner.run(
        prompt=prompt_path.read_text(),
        allowed_tools="Read,Bash(git:*),Write",
        add_dirs=[str(output_dir)],
        working_dir=str(repo_dir),
    )

    if rc == 0:
        logger.log("STRUCTURAL SCAN SUCCESS")
    else:
        logger.log(f"STRUCTURAL SCAN FAILED (exit {rc})")
        logger.log(_tail(output, 10))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _tail(text: str, n: int) -> str:
    """Last n lines of text, for error logging."""
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:]) if lines else ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="autodocs pipeline orchestrator")
    parser.add_argument("output_dir", help="Output directory path")
    parser.add_argument("repo_dir", help="Git repository path")
    parser.add_argument("--dry-run", action="store_true", help="Skip apply step")
    parser.add_argument("--since", dest="since_date", help="Catchup mode: process PRs since date (YYYY-MM-DD)")
    parser.add_argument("--chunk-days", type=int, default=7, help="Catchup chunk size in days")
    parser.add_argument("--structural-scan", action="store_true", help="Run weekly structural scan")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    repo_dir = Path(args.repo_dir)

    # Resolve scripts directory (same logic as bash wrapper)
    scripts_dir = Path(__file__).parent

    logger = Logger(output_dir)
    logger.rotate()

    # Validate config
    config = load_config(output_dir)
    errors = validate_config(config)
    if errors:
        for e in errors:
            logger.log(f"CONFIG ERROR: {e}")
        logger.metric("sync", "config-invalid", 1)
        sys.exit(1)

    runner = create_runner(config)

    # Structural scan mode
    if args.structural_scan:
        if not runner.check_auth(str(repo_dir)):
            logger.log("SCAN AUTH FAILED — aborting")
            sys.exit(1)
        logger.rotate()
        run_structural_scan(output_dir, repo_dir, runner, logger)
        return

    # Auth check
    if not runner.check_auth(str(repo_dir)):
        (output_dir / "sync-status.md").write_text(
            f"status: failed\ndrift: skipped\nsuggest: skipped\n"
            f"verify: skipped\napply: skipped\n"
            f"timestamp: {logger.timestamp}\n"
            f"error: Claude Code auth expired\n"
            f"likely_cause: Re-open Claude Code interactively to refresh authentication.\n"
        )
        logger.log("AUTH FAILED — aborting sync")
        sys.exit(1)

    # Pre-flight: verify doc paths
    config_helper = scripts_dir / "config-helper.py"
    if config_helper.exists():
        result = subprocess.run(
            ["python3", str(config_helper), str(output_dir / "config.yaml"), "verify-docs", str(repo_dir)],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            logger.log("WARN: doc paths not found in repo (check config.yaml docs[].repo_path):")
            for line in result.stdout.strip().splitlines():
                logger.log(f"  {line}")

    # Git fetch
    result = subprocess.run(
        ["git", "fetch", "origin", "--quiet"],
        cwd=str(repo_dir), capture_output=True,
    )
    if result.returncode != 0:
        logger.log("git fetch failed (non-fatal)")

    platform = read_config_key(config, "platform")

    # Pre-sync
    proceed = run_pre_sync(scripts_dir, output_dir, repo_dir, platform, logger)
    if not proceed:
        (output_dir / "sync-status.md").write_text(
            f"status: skipped\nreason: open PR limit\ntimestamp: {logger.timestamp}\n"
        )
        return

    # Catchup or normal mode
    if args.since_date:
        run_catchup(
            output_dir, repo_dir, config, runner, logger, scripts_dir,
            args.since_date, args.chunk_days, args.dry_run,
        )
    else:
        orch = Orchestrator(
            output_dir, repo_dir, config, runner, logger, scripts_dir, args.dry_run,
        )
        orch.run_pipeline()
        orch.write_status()


if __name__ == "__main__":
    main()
