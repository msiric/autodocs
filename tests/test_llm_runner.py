"""Unit tests for llm_runner.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from llm_runner import APIRunner, CLIRunner, LLMRunner, create_runner


# ---------------------------------------------------------------------------
# create_runner factory
# ---------------------------------------------------------------------------

class TestCreateRunner:
    def test_default_is_cli(self):
        runner = create_runner({})
        assert isinstance(runner, CLIRunner)

    def test_cli_explicit(self):
        runner = create_runner({"llm": {"backend": "cli"}})
        assert isinstance(runner, CLIRunner)

    def test_api_backend(self):
        runner = create_runner({"llm": {"backend": "api"}})
        assert isinstance(runner, APIRunner)

    def test_unknown_defaults_to_cli(self):
        runner = create_runner({"llm": {"backend": "unknown"}})
        assert isinstance(runner, CLIRunner)

    def test_api_with_model(self):
        runner = create_runner({"llm": {"backend": "api", "model": "claude-opus-4-0-20250514"}})
        assert isinstance(runner, APIRunner)
        assert runner.default_model == "claude-opus-4-0-20250514"


# ---------------------------------------------------------------------------
# CLIRunner
# ---------------------------------------------------------------------------

class TestCLIRunner:
    @patch("llm_runner.subprocess.run")
    def test_run_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
        runner = CLIRunner(max_retries=1)
        rc, output = runner.run("prompt", "Read,Write", ["/dir"])
        assert rc == 0
        assert output == "output"

    @patch("llm_runner.subprocess.run")
    def test_run_failure_retries(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        runner = CLIRunner(max_retries=2, initial_delay=0.01)
        rc, output = runner.run("prompt", "Read,Write", ["/dir"])
        assert rc == 1
        assert mock_run.call_count == 2  # retried once

    @patch("llm_runner.subprocess.run")
    def test_check_auth_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK")
        runner = CLIRunner()
        assert runner.check_auth("/repo") is True

    @patch("llm_runner.subprocess.run")
    def test_check_auth_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        runner = CLIRunner()
        assert runner.check_auth("/repo") is False

    @patch("llm_runner.subprocess.run")
    def test_run_passes_all_options(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        runner = CLIRunner(max_retries=1)
        runner.run("p", "Read", ["/a", "/b"], append_system="sys", model="opus", working_dir="/wd")
        cmd = mock_run.call_args[0][0]
        assert "--add-dir" in cmd
        assert "--append-system-prompt" in cmd
        assert "--model" in cmd
        assert mock_run.call_args[1]["cwd"] == "/wd"


# ---------------------------------------------------------------------------
# APIRunner
# ---------------------------------------------------------------------------

class TestAPIRunner:
    def test_check_auth_no_key(self):
        runner = APIRunner(api_key="")
        assert runner.check_auth("/repo") is False

    def test_run_no_key_or_package(self):
        runner = APIRunner(api_key="")
        rc, output = runner.run("prompt", "Read", ["/dir"])
        assert rc == 1
        # Either missing package or missing key
        assert "anthropic" in output.lower() or "ANTHROPIC_API_KEY" in output

    def test_path_allowed(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        d = tmp_path / "output"
        d.mkdir()
        f = d / "test.md"
        f.write_text("content")
        assert runner._is_path_allowed(str(f), [str(d)]) is True

    def test_path_blocked_traversal(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        d = tmp_path / "output"
        d.mkdir()
        assert runner._is_path_allowed(str(d / ".." / "etc" / "passwd"), [str(d)]) is False

    def test_path_blocked_outside_dir(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        d = tmp_path / "output"
        d.mkdir()
        assert runner._is_path_allowed("/etc/passwd", [str(d)]) is False

    def test_path_blocked_empty(self):
        runner = APIRunner(api_key="test")
        assert runner._is_path_allowed("", ["/dir"]) is False

    def test_build_tools_read_write(self):
        runner = APIRunner(api_key="test")
        tools = runner._build_tools("Read,Write")
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"Read", "Write"}

    def test_build_tools_empty(self):
        runner = APIRunner(api_key="test")
        tools = runner._build_tools("")
        assert tools == []

    def test_handle_read_tool(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        f = tmp_path / "test.md"
        f.write_text("hello world")
        result = runner._handle_tool_call("Read", {"file_path": str(f)}, [str(tmp_path)])
        assert result == "hello world"

    def test_handle_write_tool(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        f = tmp_path / "output.md"
        result = runner._handle_tool_call("Write", {"file_path": str(f), "content": "written"}, [str(tmp_path)])
        assert "Successfully" in result
        assert f.read_text() == "written"

    def test_handle_read_blocked_path(self, tmp_path: Path):
        runner = APIRunner(api_key="test")
        result = runner._handle_tool_call("Read", {"file_path": "/etc/passwd"}, [str(tmp_path)])
        assert "Error" in result
        assert "outside" in result

    def test_handle_unknown_tool(self):
        runner = APIRunner(api_key="test")
        result = runner._handle_tool_call("Bash", {"cmd": "ls"}, ["/dir"])
        assert "unknown tool" in result


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_claude_runner_import(self):
        from claude_runner import ClaudeRunner
        runner = ClaudeRunner()
        assert isinstance(runner, CLIRunner)
