#!/usr/bin/env python3
"""Thin wrapper for Claude Code CLI invocation.

Today: subprocess call to `claude -p`. Tomorrow: direct Anthropic API call.
This is the seam between the orchestrator and the LLM backend.
"""

from __future__ import annotations

import subprocess
import time


class ClaudeRunner:
    """Runs Claude Code CLI calls with retry and exponential backoff."""

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
        """Run a Claude CLI call with retry. Returns (exit_code, output).

        On success: (0, stdout).
        On failure after retries: (exit_code, combined_output).
        """
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
                cmd,
                capture_output=True,
                text=True,
                cwd=working_dir,
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
        """Quick auth check: claude -p 'Reply with OK'."""
        result = subprocess.run(
            ["claude", "-p", "Reply with OK", "--output-format", "text"],
            capture_output=True,
            text=True,
            cwd=working_dir,
        )
        return result.returncode == 0 and result.stdout.strip() == "OK"
