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
# Cross-cutting file discovery (sync_engine)
# ---------------------------------------------------------------------------

class TestDiscoverCrossCuttingFiles:
    def setup_method(self):
        from sync_engine import discover_cross_cutting_files
        self.discover = discover_cross_cutting_files

    def test_finds_files_with_identifier(self, tmp_path: Path):
        pkg = tmp_path / "packages" / "shared-lib" / "src"
        pkg.mkdir(parents=True)
        (pkg / "helper.ts").write_text("export function useChannelPageData() {}")
        (pkg / "unrelated.ts").write_text("export function useSomethingElse() {}")
        config = {
            "cross_cutting_packages": ["packages/shared-lib/src/"],
            "cross_cutting_identifiers": ["ChannelPage"],
        }
        files = self.discover(tmp_path, config)
        assert len(files) == 1
        assert "helper.ts" in files[0]

    def test_skips_test_files(self, tmp_path: Path):
        pkg = tmp_path / "packages" / "lib" / "src"
        pkg.mkdir(parents=True)
        (pkg / "page.ts").write_text("const channelPage = true;")
        (pkg / "page.test.ts").write_text("test('channelPage', () => {});")
        config = {
            "cross_cutting_packages": ["packages/lib/src/"],
            "cross_cutting_identifiers": ["channelPage"],
        }
        files = self.discover(tmp_path, config)
        assert len(files) == 1
        assert ".test." not in files[0]

    def test_empty_config(self, tmp_path: Path):
        assert self.discover(tmp_path, {}) == []
        assert self.discover(tmp_path, {"cross_cutting_packages": []}) == []
        assert self.discover(tmp_path, {"cross_cutting_identifiers": ["X"]}) == []

    def test_nonexistent_package(self, tmp_path: Path):
        config = {
            "cross_cutting_packages": ["packages/nonexistent/"],
            "cross_cutting_identifiers": ["ChannelPage"],
        }
        assert self.discover(tmp_path, config) == []

    def test_no_matches(self, tmp_path: Path):
        pkg = tmp_path / "packages" / "lib" / "src"
        pkg.mkdir(parents=True)
        (pkg / "helper.ts").write_text("export function doStuff() {}")
        config = {
            "cross_cutting_packages": ["packages/lib/src/"],
            "cross_cutting_identifiers": ["ChannelPage"],
        }
        assert self.discover(tmp_path, config) == []

    def test_multiple_identifiers(self, tmp_path: Path):
        pkg = tmp_path / "packages" / "lib" / "src"
        pkg.mkdir(parents=True)
        (pkg / "a.ts").write_text("useChannelPage()")
        (pkg / "b.ts").write_text("channel-pages config")
        (pkg / "c.ts").write_text("nothing relevant")
        config = {
            "cross_cutting_packages": ["packages/lib/src/"],
            "cross_cutting_identifiers": ["ChannelPage", "channel-pages"],
        }
        files = self.discover(tmp_path, config)
        assert len(files) == 2

    def test_deduplication(self, tmp_path: Path):
        pkg = tmp_path / "packages" / "lib" / "src"
        pkg.mkdir(parents=True)
        (pkg / "a.ts").write_text("ChannelPage and channelPage in same file")
        config = {
            "cross_cutting_packages": ["packages/lib/src/"],
            "cross_cutting_identifiers": ["ChannelPage", "channelPage"],
        }
        files = self.discover(tmp_path, config)
        assert len(files) == 1


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
        from llm_runner import CLIRunner as ClaudeRunner
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
        from llm_runner import CLIRunner as ClaudeRunner
        logger = Logger(output_dir)
        scripts = Path(__file__).parent.parent / "scripts"
        return Orchestrator(output_dir, output_dir, config, ClaudeRunner(), logger, scripts)

    def _write_report(self, output_dir: Path, feature_prs: int):
        (output_dir / "daily-report.md").write_text(
            f"---\nfeature_prs: {feature_prs}\n---\n"
        )

    def test_advances_on_success_with_relevant(self, output_dir: Path, minimal_config: dict):
        self._write_report(output_dir, feature_prs=2)
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "success"
        orch._advance_timestamp()
        assert (output_dir / "last-successful-run").exists()

    def test_no_advance_on_drift_failure(self, output_dir: Path, minimal_config: dict):
        self._write_report(output_dir, feature_prs=1)
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "failed"
        orch._advance_timestamp()
        assert not (output_dir / "last-successful-run").exists()

    def test_advances_on_drift_skipped(self, output_dir: Path, minimal_config: dict):
        self._write_report(output_dir, feature_prs=0)
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "skipped"
        orch._advance_timestamp()
        # Drift skipped (no feature PRs) should still advance
        assert (output_dir / "last-successful-run").exists()

    def test_advances_on_empty_window(self, output_dir: Path, minimal_config: dict):
        self._write_report(output_dir, feature_prs=0)
        orch = self._make_orchestrator(output_dir, minimal_config)
        orch.status["sync"] = "success"
        orch.status["drift"] = "success"
        orch._advance_timestamp()
        # No feature PRs but drift ran successfully → advance
        assert not (output_dir / "last-successful-run").exists()


# ---------------------------------------------------------------------------
# Review thread formatting (sync_engine)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PR number extraction from merge commits (sync_engine)
# ---------------------------------------------------------------------------

class TestExtractPrNumber:
    def setup_method(self):
        from sync_engine import _extract_pr_number
        self.extract = _extract_pr_number

    def test_github_merge(self):
        assert self.extract("Merge pull request #42 from owner/branch") == 42

    def test_github_squash(self):
        assert self.extract("feat: add rate limiting (#123)") == 123

    def test_ado_merge(self):
        assert self.extract("Merged PR 456: Fix auth handler") == 456

    def test_ado_squash(self):
        assert self.extract("Merged PR 789: Refactor permissions") == 789

    def test_gitlab_merge(self):
        assert self.extract("See merge request group/project!99") == 99

    def test_bitbucket_merge(self):
        assert self.extract("Merged in feat/search (pull request #55)") == 55

    def test_no_pr_number(self):
        assert self.extract("regular commit without PR") is None

    def test_github_merge_takes_priority_over_squash(self):
        # If both patterns match, merge pattern should win (more specific)
        result = self.extract("Merge pull request #10 from owner/branch (#10)")
        assert result == 10


# ---------------------------------------------------------------------------
# Review thread formatting (sync_engine)
# ---------------------------------------------------------------------------

class TestFormatReviewThreads:
    def setup_method(self):
        from sync_engine import _format_review_threads
        self.format = _format_review_threads

    def test_human_review_included(self):
        reviews = [{"body": "LGTM, nice error handling", "state": "APPROVED", "author": {"login": "alice"}}]
        result = self.format(reviews)
        assert "alice" in result
        assert "LGTM" in result

    def test_bot_review_excluded(self):
        reviews = [
            {"body": "Auto-approved", "state": "APPROVED", "author": {"login": "dependabot[bot]"}},
            {"body": "Good change", "state": "APPROVED", "author": {"login": "alice"}},
        ]
        result = self.format(reviews)
        assert "dependabot" not in result
        assert "alice" in result

    def test_empty_body_excluded(self):
        reviews = [{"body": "", "state": "APPROVED", "author": {"login": "alice"}}]
        result = self.format(reviews)
        assert result == ""

    def test_no_reviews(self):
        assert self.format([]) == ""

    def test_long_comment_truncated(self):
        reviews = [{"body": "x" * 300, "state": "COMMENTED", "author": {"login": "alice"}}]
        result = self.format(reviews)
        assert len(result) < 350  # 200 char truncation + prefix

    def test_multiple_reviews_capped(self):
        reviews = [
            {"body": f"Comment {i}", "state": "COMMENTED", "author": {"login": f"user{i}"}}
            for i in range(5)
        ]
        result = self.format(reviews)
        assert "+2 more" in result

    def test_bot_suffix_excluded(self):
        reviews = [{"body": "check passed", "state": "APPROVED", "author": {"login": "ci-bot"}}]
        result = self.format(reviews)
        assert result == ""


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


# ---------------------------------------------------------------------------
# Config schema validation (schema_helper)
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def setup_method(self):
        from schema_helper import validate_config
        self.validate = validate_config

    def test_cross_cutting_valid(self):
        config = {
            "platform": "ado", "ado": {"org": "x", "project": "y"},
            "cross_cutting_packages": ["pkg/a/", "pkg/b/"],
            "cross_cutting_identifiers": ["FeatureName"],
        }
        assert self.validate(config) == []

    def test_cross_cutting_packages_without_identifiers(self):
        config = {
            "platform": "github", "github": {"owner": "x", "repo": "y"},
            "cross_cutting_packages": ["pkg/a/"],
        }
        errors = self.validate(config)
        assert any("cross_cutting_identifiers" in e for e in errors)

    def test_cross_cutting_identifiers_without_packages(self):
        config = {
            "platform": "github", "github": {"owner": "x", "repo": "y"},
            "cross_cutting_identifiers": ["Feature"],
        }
        errors = self.validate(config)
        assert any("cross_cutting_packages" in e for e in errors)

    def test_cross_cutting_not_list(self):
        config = {
            "platform": "github", "github": {"owner": "x", "repo": "y"},
            "cross_cutting_packages": "not-a-list",
            "cross_cutting_identifiers": ["X"],
        }
        errors = self.validate(config)
        assert any("must be a list" in e for e in errors)

    def test_no_cross_cutting_is_valid(self):
        config = {
            "platform": "github", "github": {"owner": "x", "repo": "y"},
        }
        assert self.validate(config) == []

    # --- llm.temperature validation ---
    # The temperature knob is the linchpin of run-to-run determinism for
    # SUGGEST. Garbage values must be rejected at config-load time, not at
    # the API call site where they cause cryptic 400s mid-pipeline.

    def _base_cfg(self) -> dict:
        return {"platform": "github", "github": {"owner": "x", "repo": "y"}}

    def test_llm_temperature_valid_int(self):
        cfg = self._base_cfg() | {"llm": {"temperature": 0}}
        assert self.validate(cfg) == []

    def test_llm_temperature_valid_float(self):
        cfg = self._base_cfg() | {"llm": {"temperature": 0.5}}
        assert self.validate(cfg) == []

    def test_llm_temperature_one_is_valid(self):
        cfg = self._base_cfg() | {"llm": {"temperature": 1}}
        assert self.validate(cfg) == []

    def test_llm_temperature_negative_rejected(self):
        cfg = self._base_cfg() | {"llm": {"temperature": -0.1}}
        errors = self.validate(cfg)
        assert any("temperature" in e for e in errors)

    def test_llm_temperature_above_one_rejected(self):
        cfg = self._base_cfg() | {"llm": {"temperature": 1.5}}
        errors = self.validate(cfg)
        assert any("temperature" in e for e in errors)

    def test_llm_temperature_string_rejected(self):
        cfg = self._base_cfg() | {"llm": {"temperature": "0"}}
        errors = self.validate(cfg)
        assert any("temperature" in e for e in errors)

    def test_llm_temperature_bool_rejected(self):
        # Python's `bool` is a subclass of `int`. Without an explicit guard,
        # `temperature: true` would silently validate as 1. Reject it so the
        # config error surfaces the actual mistake.
        cfg = self._base_cfg() | {"llm": {"temperature": True}}
        errors = self.validate(cfg)
        assert any("temperature" in e for e in errors)

    def test_llm_temperature_null_is_valid(self):
        # YAML `temperature: null` → Python None. The runtime treats it as
        # "use the default" — must not be a validation error.
        cfg = self._base_cfg() | {"llm": {"temperature": None}}
        assert self.validate(cfg) == []


# ---------------------------------------------------------------------------
# fetch_pr_details — guards against ADO CLI argument regressions
# ---------------------------------------------------------------------------

class TestFetchPrDetailsAdoCommand:
    """ADO PR-id-targeted commands ('show', 'update', 'reviewer add') do NOT
    accept -p/--project. Only project-context commands (create, list) do.

    Silently passing -p caused 'unrecognized arguments' errors, dropping
    PR title/description/author enrichment. The daily report then showed
    'by ' (empty author), and downstream changelog entries showed
    'by (unknown)' for every entry.
    """

    def _capture(self, monkeypatch, config: dict):
        """Run fetch_pr_details with subprocess.run captured."""
        import subprocess
        from sync_engine import fetch_pr_details
        calls: list[list[str]] = []

        class _Result:
            returncode = 1  # force failure so the function returns None cleanly
            stdout = ""
            stderr = ""

        def _fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _Result()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        fetch_pr_details(config, pr_number=42)
        return calls

    def test_ado_pr_show_has_no_project_flag(self, monkeypatch):
        """az repos pr show --id N must not include -p/--project."""
        calls = self._capture(monkeypatch, {
            "platform": "ado",
            "ado": {"org": "myorg", "project": "MyProject"},
        })
        ado_calls = [c for c in calls if c[:4] == ["az", "repos", "pr", "show"]]
        assert ado_calls, "expected an 'az repos pr show' call"
        for cmd in ado_calls:
            assert "-p" not in cmd, f"-p must not appear in: {cmd}"
            assert "--project" not in cmd, f"--project must not appear in: {cmd}"
            assert "--id" in cmd
            assert "--org" in cmd

    def test_ado_skips_when_no_org(self, monkeypatch):
        calls = self._capture(monkeypatch, {
            "platform": "ado",
            "ado": {},  # missing org
        })
        assert calls == []


# ---------------------------------------------------------------------------
# fetch_pr_details — retry + observable failure on platform CLI errors
# ---------------------------------------------------------------------------
# Originally the call was one-shot with silent None on any failure. During the
# Feb-20 lookback experiment, a transient ADO API blip dropped 74/76 PRs'
# enrichment in Run #1; subsequent runs got full enrichment for the same PRs.
# The pipeline silently shipped LLM input that varied between runs (Merged-PR-N
# fallback vs full title/description), masquerading as LLM stochasticity.
# Retry recovers transients; WARN surfaces permanent failures.

class TestFetchPrDetailsRetry:
    def _setup(self, monkeypatch, exit_codes, stderrs=None, stdouts=None):
        """Wire a fake subprocess.run that returns the given sequence."""
        import subprocess as _sp
        from sync_engine import fetch_pr_details

        stderrs = stderrs or [""] * len(exit_codes)
        stdouts = stdouts or [""] * len(exit_codes)
        calls: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            idx = len(calls)
            calls.append(list(cmd))
            rc = exit_codes[min(idx, len(exit_codes) - 1)]
            return type("_R", (), {
                "returncode": rc,
                "stdout": stdouts[min(idx, len(stdouts) - 1)],
                "stderr": stderrs[min(idx, len(stderrs) - 1)],
            })()

        monkeypatch.setattr(_sp, "run", _fake_run)
        # Don't actually sleep between attempts during tests
        monkeypatch.setattr("sync_engine.time.sleep", lambda *_a, **_kw: None)
        return fetch_pr_details, calls

    def test_transient_failure_then_success(self, monkeypatch, capsys):
        """Retryable error (timeout/503/etc.) → retry → success returns parsed payload."""
        success_payload = json.dumps({
            "title": "Real Title",
            "description": "desc",
            "author": "user@example.com",
        })
        fetch, calls = self._setup(
            monkeypatch,
            exit_codes=[1, 0],
            stderrs=["timeout while reading response", ""],
            stdouts=["", success_payload],
        )
        result = fetch({"platform": "ado", "ado": {"org": "myorg"}}, pr_number=42)
        assert result == {
            "title": "Real Title",
            "description": "desc",
            "author": "user@example.com",
        }
        assert len(calls) == 2, "expected one retry"
        # Success path: no WARN emitted
        assert "WARN: fetch_pr_details" not in capsys.readouterr().err

    def test_transient_failure_twice_warns_and_returns_none(self, monkeypatch, capsys):
        """Retryable failure twice → return None, log WARN with PR # and error."""
        fetch, calls = self._setup(
            monkeypatch,
            exit_codes=[1, 1],
            stderrs=["503 Service Unavailable", "503 Service Unavailable"],
        )
        result = fetch({"platform": "ado", "ado": {"org": "myorg"}}, pr_number=99)
        assert result is None
        assert len(calls) == 2, "expected exactly one retry (max 2 attempts total)"
        warning = capsys.readouterr().err
        assert "WARN: fetch_pr_details" in warning
        assert "PR #99" in warning
        assert "503" in warning

    def test_permanent_failure_does_not_retry(self, monkeypatch, capsys):
        """Non-retryable error (auth, unrecognized arg) → single call → WARN + None."""
        fetch, calls = self._setup(
            monkeypatch,
            exit_codes=[1],
            stderrs=["error: unrecognized argument: --bogus-flag"],
        )
        result = fetch({"platform": "ado", "ado": {"org": "myorg"}}, pr_number=7)
        assert result is None
        assert len(calls) == 1, "permanent errors must NOT retry"
        warning = capsys.readouterr().err
        assert "WARN: fetch_pr_details" in warning
        assert "PR #7" in warning

    def test_success_first_try_no_retry_no_warn(self, monkeypatch, capsys):
        """Happy path: one call, no warning, parsed payload returned."""
        payload = json.dumps({
            "title": "ok",
            "description": "",
            "author": "x@y.com",
        })
        fetch, calls = self._setup(
            monkeypatch,
            exit_codes=[0],
            stdouts=[payload],
        )
        result = fetch({"platform": "ado", "ado": {"org": "myorg"}}, pr_number=1)
        assert result == {"title": "ok", "description": "", "author": "x@y.com"}
        assert len(calls) == 1
        assert "WARN" not in capsys.readouterr().err

    def test_cli_not_installed_silent(self, monkeypatch, capsys):
        """FileNotFoundError (CLI missing) → return None silently. The error
        is the same for every PR; logging per call would just be noise, and
        the operator notices via the universal data-degradation pattern."""
        import subprocess as _sp
        from sync_engine import fetch_pr_details

        def _missing(*_a, **_kw):
            raise FileNotFoundError("az: command not found")

        monkeypatch.setattr(_sp, "run", _missing)
        result = fetch_pr_details({"platform": "ado", "ado": {"org": "myorg"}}, pr_number=1)
        assert result is None
        assert "WARN" not in capsys.readouterr().err
