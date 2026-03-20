#!/usr/bin/env python3
"""Multi-backend LLM runner for autodocs.

Provides a unified interface for running LLM calls via different backends:
- CLIRunner: Claude Code CLI (`claude -p`) — supports all tools
- APIRunner: Anthropic API — supports Read/Write tools (drift + suggest calls)

Usage:
    runner = create_runner(config)
    rc, output = runner.run(prompt, allowed_tools, add_dirs)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path


class LLMRunner(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def run(
        self,
        prompt: str,
        allowed_tools: str,
        add_dirs: list[str],
        *,
        append_system: str | None = None,
        model: str | None = None,
        working_dir: str | None = None,
    ) -> tuple[int, str]:
        """Run an LLM call. Returns (exit_code, output_text)."""
        ...

    @abstractmethod
    def check_auth(self, working_dir: str) -> bool:
        """Verify credentials are valid."""
        ...


# ---------------------------------------------------------------------------
# CLI Runner (Claude Code)
# ---------------------------------------------------------------------------

class CLIRunner(LLMRunner):
    """Claude Code CLI backend. Supports all tools."""

    def __init__(self, max_retries: int = 3, initial_delay: float = 5.0):
        self.max_retries = max_retries
        self.initial_delay = initial_delay

    def run(
        self,
        prompt: str,
        allowed_tools: str,
        add_dirs: list[str],
        *,
        append_system: str | None = None,
        model: str | None = None,
        working_dir: str | None = None,
    ) -> tuple[int, str]:
        cmd = ["claude", "-p", prompt]
        for d in add_dirs:
            cmd.extend(["--add-dir", d])
        cmd.extend(["--allowedTools", allowed_tools])
        cmd.extend(["--output-format", "text"])
        if append_system:
            cmd.extend(["--append-system-prompt", append_system])
        if model:
            cmd.extend(["--model", model])

        delay = self.initial_delay
        last_rc = 1
        last_output = ""

        for attempt in range(1, self.max_retries + 1):
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=working_dir,
            )
            last_output = result.stdout + result.stderr
            last_rc = result.returncode

            if last_rc == 0:
                return 0, result.stdout

            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2

        return last_rc, last_output

    def check_auth(self, working_dir: str) -> bool:
        result = subprocess.run(
            ["claude", "-p", "Reply with OK", "--output-format", "text"],
            capture_output=True, text=True, cwd=working_dir,
        )
        return result.returncode == 0 and result.stdout.strip() == "OK"


# ---------------------------------------------------------------------------
# API Runner (Anthropic API)
# ---------------------------------------------------------------------------

# Tool definitions for Read and Write
READ_TOOL = {
    "name": "Read",
    "description": "Read a file and return its contents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file to read."},
        },
        "required": ["file_path"],
    },
}

WRITE_TOOL = {
    "name": "Write",
    "description": "Write content to a file (creates parent directories if needed).",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file to write."},
            "content": {"type": "string", "description": "Content to write to the file."},
        },
        "required": ["file_path", "content"],
    },
}

MODEL_MAP = {
    "opus": "claude-opus-4-0-20250514",
    "sonnet": "claude-sonnet-4-20250514",
}


class APIRunner(LLMRunner):
    """Anthropic API backend with agentic Read/Write tool loop.

    Only supports Read and Write tools — suitable for drift and suggest calls.
    Requires: pip install anthropic
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        max_tool_rounds: int = 50,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.default_model = model
        self.max_retries = max_retries
        self.max_tool_rounds = max_tool_rounds
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "anthropic package required for API backend. "
                    "Install with: pip install anthropic"
                )
            if not self.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY environment variable required for API backend")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def check_auth(self, working_dir: str) -> bool:
        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.default_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with OK"}],
            )
            text = "".join(
                b.text for b in response.content if hasattr(b, "text")
            )
            return "OK" in text
        except Exception:
            return False

    def run(
        self,
        prompt: str,
        allowed_tools: str,
        add_dirs: list[str],
        *,
        append_system: str | None = None,
        model: str | None = None,
        working_dir: str | None = None,
    ) -> tuple[int, str]:
        try:
            client = self._get_client()
        except RuntimeError as e:
            return 1, str(e)

        # Resolve model
        model_id = MODEL_MAP.get(model or "", model or self.default_model)

        # Build tool list based on allowed_tools
        tools = self._build_tools(allowed_tools)

        # Build system prompt with directory context
        system_parts = []
        if append_system:
            system_parts.append(append_system)
        for d in add_dirs:
            p = Path(d)
            if p.exists() and p.is_dir():
                files = sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
                if files:
                    listing = "\n".join(f"  {f}" for f in files[:200])
                    system_parts.append(f"Files available in {d}:\n{listing}")
        system = "\n\n".join(system_parts) if system_parts else ""

        messages: list[dict] = [{"role": "user", "content": prompt}]

        # Agentic loop
        for _round in range(self.max_tool_rounds):
            try:
                kwargs: dict = {
                    "model": model_id,
                    "max_tokens": self.max_tokens,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system
                if tools:
                    kwargs["tools"] = tools

                response = client.messages.create(**kwargs)
            except Exception as e:
                return 1, f"API error: {e}"

            # Extract tool_use blocks
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # Final response — extract text
                text = "".join(
                    b.text for b in response.content if hasattr(b, "text")
                )
                return 0, text

            # Handle tool calls
            tool_results = []
            for tu in tool_uses:
                result_content = self._handle_tool_call(
                    tu.name, tu.input, add_dirs,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_content,
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        return 1, "Max tool rounds exceeded"

    def _build_tools(self, allowed_tools: str) -> list[dict]:
        """Build API tool definitions from the allowed_tools string."""
        tool_set = {t.strip() for t in allowed_tools.split(",") if t.strip()}
        tools = []
        if "Read" in tool_set:
            tools.append(READ_TOOL)
        if "Write" in tool_set:
            tools.append(WRITE_TOOL)
        return tools

    def _handle_tool_call(
        self, tool_name: str, tool_input: dict, add_dirs: list[str],
    ) -> str:
        """Execute a tool call and return the result string."""
        if tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            if not self._is_path_allowed(file_path, add_dirs):
                return f"Error: path '{file_path}' is outside allowed directories"
            path = Path(file_path)
            if not path.exists():
                return f"Error: file '{file_path}' does not exist"
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"Error reading file: {e}"

        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            if not self._is_path_allowed(file_path, add_dirs):
                return f"Error: path '{file_path}' is outside allowed directories"
            path = Path(file_path)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                return f"Successfully wrote to {file_path}"
            except Exception as e:
                return f"Error writing file: {e}"

        return f"Error: unknown tool '{tool_name}'"

    def _is_path_allowed(self, file_path: str, add_dirs: list[str]) -> bool:
        """Security: verify path is within allowed directories."""
        if not file_path:
            return False
        try:
            resolved = Path(file_path).resolve()
            return any(
                resolved == Path(d).resolve() or
                str(resolved).startswith(str(Path(d).resolve()) + os.sep)
                for d in add_dirs
            )
        except (ValueError, OSError):
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_runner(config: dict) -> LLMRunner:
    """Create an LLM runner from config.

    Reads config['llm']['backend']: 'cli' (default) or 'api'.
    """
    backend = (config.get("llm", {}).get("backend", "cli")).lower()
    if backend == "api":
        model = config.get("llm", {}).get("model", "claude-sonnet-4-20250514")
        return APIRunner(model=model)
    return CLIRunner()
