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
# APIRunner agentic loop (mock-based)
# ---------------------------------------------------------------------------

class _MockBlock:
    """Mock Anthropic content block (TextBlock or ToolUseBlock)."""
    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)

class _MockMessage:
    """Mock Anthropic Message response."""
    def __init__(self, content: list, stop_reason: str = "end_turn"):
        self.content = content
        self.stop_reason = stop_reason

def _text_response(text: str) -> _MockMessage:
    return _MockMessage([_MockBlock("text", text=text)])

def _tool_use_response(name: str, input_data: dict, tool_id: str = "tool_1") -> _MockMessage:
    return _MockMessage(
        [_MockBlock("tool_use", id=tool_id, name=name, input=input_data)],
        stop_reason="tool_use",
    )


class TestAPIRunnerLoop:
    """Test the full agentic run() loop with mock API client."""

    def _make_runner(self, mock_client) -> APIRunner:
        runner = APIRunner(api_key="test-key")
        runner._client = mock_client
        return runner

    def test_direct_text_response(self, tmp_path: Path):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response("Done.")
        runner = self._make_runner(mock_client)

        rc, output = runner.run("test prompt", "Read,Write", [str(tmp_path)])
        assert rc == 0
        assert "Done." in output
        assert mock_client.messages.create.call_count == 1

    def test_read_then_text(self, tmp_path: Path):
        (tmp_path / "input.md").write_text("file content here")
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _tool_use_response("Read", {"file_path": str(tmp_path / "input.md")}),
            _text_response("Processed the file."),
        ]
        runner = self._make_runner(mock_client)

        rc, output = runner.run("read input.md", "Read,Write", [str(tmp_path)])
        assert rc == 0
        assert "Processed" in output
        assert mock_client.messages.create.call_count == 2

    def test_write_then_text(self, tmp_path: Path):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _tool_use_response("Write", {
                "file_path": str(tmp_path / "output.md"),
                "content": "generated content",
            }),
            _text_response("File written."),
        ]
        runner = self._make_runner(mock_client)

        rc, output = runner.run("write output", "Read,Write", [str(tmp_path)])
        assert rc == 0
        assert (tmp_path / "output.md").read_text() == "generated content"

    def test_read_write_multi_round(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text("platform: github")
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _tool_use_response("Read", {"file_path": str(tmp_path / "config.yaml")}, "t1"),
            _tool_use_response("Write", {
                "file_path": str(tmp_path / "report.md"),
                "content": "# Report\nDone",
            }, "t2"),
            _text_response("Pipeline complete."),
        ]
        runner = self._make_runner(mock_client)

        rc, output = runner.run("run pipeline", "Read,Write", [str(tmp_path)])
        assert rc == 0
        assert "Pipeline complete" in output
        assert (tmp_path / "report.md").read_text() == "# Report\nDone"
        assert mock_client.messages.create.call_count == 3

    def test_path_security_in_loop(self, tmp_path: Path):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _tool_use_response("Read", {"file_path": "/etc/passwd"}),
            _text_response("Got an error."),
        ]
        runner = self._make_runner(mock_client)

        rc, output = runner.run("read /etc/passwd", "Read,Write", [str(tmp_path)])
        assert rc == 0  # Loop continues despite tool error
        # The second call's messages should contain the error tool_result
        second_call = mock_client.messages.create.call_args_list[1]
        messages = second_call[1]["messages"]
        tool_result = messages[-1]["content"][0]
        assert "outside" in tool_result["content"]

    def test_max_rounds_exceeded(self, tmp_path: Path):
        mock_client = MagicMock()
        # Always return tool_use — never a final text response
        mock_client.messages.create.return_value = _tool_use_response(
            "Read", {"file_path": str(tmp_path / "loop.md")}
        )
        (tmp_path / "loop.md").write_text("looping")
        runner = self._make_runner(mock_client)
        runner.max_tool_rounds = 3

        rc, output = runner.run("infinite loop", "Read,Write", [str(tmp_path)])
        assert rc == 1
        assert "Max tool rounds" in output
        assert mock_client.messages.create.call_count == 3


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_claude_runner_import(self):
        from claude_runner import ClaudeRunner
        runner = ClaudeRunner()
        assert isinstance(runner, CLIRunner)
