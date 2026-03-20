"""Unit tests for orchestrator.py — decision logic only, no LLM calls."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts/ to path so we can import orchestrator
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from orchestrator import (
    Orchestrator,
    Logger,
    _compute_chunks,
    _has_actionable_drift,
    _has_confident_suggestions,
    _suggestion_count_zero,
    _yesterday,
    get_tool_allowlists,
    read_config_key,
)


# ---------------------------------------------------------------------------
# read_config_key
# ---------------------------------------------------------------------------

class TestReadConfigKey:
    def test_simple_key(self):
        assert read_config_key({"platform": "github"}, "platform") == "github"

    def test_nested_key(self):
        config = {"github": {"owner": "alice"}}
        assert read_config_key(config, "github.owner") == "alice"

    def test_missing_key(self):
        assert read_config_key({}, "nonexistent") == ""

    def test_missing_nested_key(self):
        assert read_config_key({"github": {}}, "github.owner") == ""

    def test_deeply_missing(self):
        assert read_config_key({}, "a.b.c") == ""

    def test_boolean_true(self):
        assert read_config_key({"telemetry": {"enabled": True}}, "telemetry.enabled") == "true"

    def test_boolean_false(self):
        assert read_config_key({"telemetry": {"enabled": False}}, "telemetry.enabled") == "false"


# ---------------------------------------------------------------------------
# get_tool_allowlists
# ---------------------------------------------------------------------------

class TestToolAllowlists:
    def test_github(self):
        sync, apply = get_tool_allowlists({"platform": "github"})
        assert "Bash(gh:*)" in sync
        assert "Bash(git:*)" in sync
        assert "Bash(gh:*)" in apply

    def test_gitlab(self):
        sync, _ = get_tool_allowlists({"platform": "gitlab"})
        assert "Bash(glab:*)" in sync

    def test_bitbucket(self):
        sync, _ = get_tool_allowlists({"platform": "bitbucket"})
        assert "Bash(curl:*)" in sync

    def test_ado(self):
        sync, apply = get_tool_allowlists({"platform": "ado"})
        assert "mcp__azure-devops__repo_list_pull_requests_by_repo_or_project" in sync
        assert "mcp__azure-devops__repo_create_pull_request" in apply

    def test_unknown_platform(self):
        sync, apply = get_tool_allowlists({"platform": "svn"})
        assert sync == ""
        assert apply == ""

    def test_telemetry_appends_kusto(self):
        config = {"platform": "github", "telemetry": {"enabled": True}}
        sync, _ = get_tool_allowlists(config)
        assert "mcp__kusto-mcp__kusto_query" in sync

    def test_telemetry_disabled(self):
        config = {"platform": "github", "telemetry": {"enabled": False}}
        sync, _ = get_tool_allowlists(config)
        assert "kusto" not in sync


# ---------------------------------------------------------------------------
# Pipeline gating helpers
# ---------------------------------------------------------------------------

class TestPipelineGating:
    def test_actionable_drift_with_high(self, output_dir: Path):
        (output_dir / "drift-report.md").write_text("| guide.md | Auth | #1 | HIGH | Modified |")
        assert _has_actionable_drift(output_dir) is True

    def test_actionable_drift_with_critical(self, output_dir: Path):
        (output_dir / "drift-report.md").write_text("| guide.md | Auth | #1 | CRITICAL | Unmapped |")
        assert _has_actionable_drift(output_dir) is True

    def test_actionable_drift_low_only(self, output_dir: Path):
        (output_dir / "drift-report.md").write_text("| guide.md | Auth | #1 | LOW | Refactor |")
        assert _has_actionable_drift(output_dir) is False

    def test_actionable_drift_missing_file(self, output_dir: Path):
        assert _has_actionable_drift(output_dir) is False

    def test_suggestion_count_zero_true(self, output_dir: Path):
        (output_dir / "drift-suggestions.md").write_text("suggestion_count: 0\n")
        assert _suggestion_count_zero(output_dir) is True

    def test_suggestion_count_nonzero(self, output_dir: Path):
        (output_dir / "drift-suggestions.md").write_text("suggestion_count: 3\n")
        assert _suggestion_count_zero(output_dir) is False

    def test_suggestion_count_missing(self, output_dir: Path):
        assert _suggestion_count_zero(output_dir) is True

    def test_confident_suggestions_present(self, output_dir: Path):
        (output_dir / "drift-suggestions.md").write_text("**Confidence:** CONFIDENT\n")
        assert _has_confident_suggestions(output_dir) is True

    def test_confident_suggestions_absent(self, output_dir: Path):
        (output_dir / "drift-suggestions.md").write_text("**Confidence:** REVIEW\n")
        assert _has_confident_suggestions(output_dir) is False


# ---------------------------------------------------------------------------
# Catchup chunks
# ---------------------------------------------------------------------------

class TestComputeChunks:
    def test_standard_weekly(self):
        chunks = _compute_chunks("2026-03-01", "2026-03-22", 7)
        assert len(chunks) == 3
        assert chunks[0] == ("2026-03-01", "2026-03-08")
        assert chunks[1] == ("2026-03-08", "2026-03-15")
        assert chunks[2] == ("2026-03-15", "2026-03-22")

    def test_same_day(self):
        chunks = _compute_chunks("2026-03-01", "2026-03-01", 7)
        assert len(chunks) == 0

    def test_daily_chunks(self):
        chunks = _compute_chunks("2026-03-01", "2026-03-04", 1)
        assert len(chunks) == 3


# ---------------------------------------------------------------------------
# Date computation (Orchestrator._compute_lookback_dates)
# ---------------------------------------------------------------------------

class TestLookbackDates:
    def _make_orchestrator(self, output_dir: Path, config: dict) -> Orchestrator:
        """Create a minimal Orchestrator for testing date logic."""
        from claude_runner import ClaudeRunner
        logger = Logger(output_dir)
        scripts = Path(__file__).parent.parent / "scripts"
        return Orchestrator(output_dir, output_dir, config, ClaudeRunner(), logger, scripts)

    @patch("orchestrator.datetime")
    def test_no_last_run_returns_yesterday(self, mock_dt, output_dir: Path, minimal_config: dict):
        mock_dt.now.return_value = datetime(2026, 3, 20, tzinfo=timezone.utc)
        mock_dt.strptime = datetime.strptime
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        orch = self._make_orchestrator(output_dir, minimal_config)
        lookback = orch._compute_lookback_dates()
        assert lookback == "2026-03-19"
        assert (output_dir / "current-date.txt").read_text() == "2026-03-20"

    def test_valid_last_run(self, output_dir: Path, minimal_config: dict):
        (output_dir / "last-successful-run").write_text("2026-03-18T12:00:00Z")
        orch = self._make_orchestrator(output_dir, minimal_config)
        lookback = orch._compute_lookback_dates()
        assert lookback == "2026-03-18"

    def test_future_last_run_resets(self, output_dir: Path, minimal_config: dict):
        (output_dir / "last-successful-run").write_text("2099-01-01T00:00:00Z")
        orch = self._make_orchestrator(output_dir, minimal_config)
        lookback = orch._compute_lookback_dates()
        # Should reset to yesterday, not use the future date
        assert lookback != "2099-01-01"


# ---------------------------------------------------------------------------
# Timestamp advancement
# ---------------------------------------------------------------------------

class TestAdvanceTimestamp:
    def _make_orchestrator(self, output_dir: Path, config: dict) -> Orchestrator:
        from claude_runner import ClaudeRunner
        logger = Logger(output_dir)
        scripts = Path(__file__).parent.parent / "scripts"
        return Orchestrator(output_dir, output_dir, config, ClaudeRunner(), logger, scripts)

    def test_advances_on_success_with_relevant(self, output_dir: Path, minimal_config: dict):
        context = {"summary": {"relevant_count": 2, "pr_count": 3}}
        (output_dir / "drift-context.json").write_text(json.dumps(context))
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "success"
        orch._advance_timestamp()
        assert (output_dir / "last-successful-run").exists()

    def test_no_advance_on_drift_failure(self, output_dir: Path, minimal_config: dict):
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "failed"
        orch._advance_timestamp()
        assert not (output_dir / "last-successful-run").exists()

    def test_no_advance_zero_relevant(self, output_dir: Path, minimal_config: dict):
        context = {"summary": {"relevant_count": 0, "pr_count": 5}}
        (output_dir / "drift-context.json").write_text(json.dumps(context))
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "success"
        orch._advance_timestamp()
        assert not (output_dir / "last-successful-run").exists()

    def test_advances_on_empty_window(self, output_dir: Path, minimal_config: dict):
        context = {"summary": {"relevant_count": 0, "pr_count": 0}}
        (output_dir / "drift-context.json").write_text(json.dumps(context))
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "success"
        orch._advance_timestamp()
        # Empty window (0 PRs total) should still advance
        assert (output_dir / "last-successful-run").exists()


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class TestLogger:
    def test_log_writes_to_file(self, output_dir: Path):
        logger = Logger(output_dir)
        logger.log("test message")
        content = (output_dir / "sync.log").read_text()
        assert "test message" in content
        assert logger.timestamp in content

    def test_metric_writes_jsonl(self, output_dir: Path):
        logger = Logger(output_dir)
        logger.metric("sync", "success", 0)
        content = (output_dir / "metrics.jsonl").read_text()
        data = json.loads(content.strip())
        assert data["call"] == "sync"
        assert data["status"] == "success"
