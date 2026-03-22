"""Storage abstraction for autodocs.

Wraps file I/O so the orchestrator doesn't use raw Path operations.
Today: local filesystem. Tomorrow: S3, database, or other backends.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    """Abstract storage interface."""

    def read(self, name: str) -> str | None:
        """Read a file. Returns None if it doesn't exist."""
        ...

    def write(self, name: str, content: str) -> None:
        """Write a file (creates parent dirs as needed)."""
        ...

    def exists(self, name: str) -> bool:
        """Check if a file exists."""
        ...

    def delete(self, name: str) -> None:
        """Delete a file (no-op if missing)."""
        ...

    def glob_names(self, pattern: str) -> list[str]:
        """Return relative names matching a glob pattern."""
        ...

    def resolve_path(self, name: str) -> Path:
        """Escape hatch: get the real filesystem path (for subprocess args)."""
        ...


class LocalStorage:
    """Local filesystem storage backed by a base directory."""

    def __init__(self, base: Path):
        self.base = base.resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, name: str) -> Path:
        """Resolve name to a path guaranteed to be within base directory."""
        path = (self.base / name).resolve()
        if not (path == self.base or str(path).startswith(str(self.base) + "/")):
            raise ValueError(f"Path '{name}' resolves outside storage directory")
        return path

    def read(self, name: str) -> str | None:
        path = self._safe_path(name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def write(self, name: str, content: str) -> None:
        path = self._safe_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file then rename. os.replace() is
        # atomic on POSIX when source and destination are on the same
        # filesystem (guaranteed here since .tmp is in the same directory).
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content)
        os.replace(tmp, path)

    def exists(self, name: str) -> bool:
        return self._safe_path(name).exists()

    def delete(self, name: str) -> None:
        self._safe_path(name).unlink(missing_ok=True)

    def glob_names(self, pattern: str) -> list[str]:
        return sorted(
            str(p.relative_to(self.base))
            for p in self.base.glob(pattern)
            if p.is_file()
        )

    def resolve_path(self, name: str) -> Path:
        return self._safe_path(name)
