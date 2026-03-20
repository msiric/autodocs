"""Storage abstraction for autodocs.

Wraps file I/O so the orchestrator doesn't use raw Path operations.
Today: local filesystem. Tomorrow: S3, database, or other backends.
"""

from __future__ import annotations

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
        self.base = base
        self.base.mkdir(parents=True, exist_ok=True)

    def read(self, name: str) -> str | None:
        path = self.base / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def write(self, name: str, content: str) -> None:
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def exists(self, name: str) -> bool:
        return (self.base / name).exists()

    def delete(self, name: str) -> None:
        path = self.base / name
        if path.exists():
            path.unlink()

    def glob_names(self, pattern: str) -> list[str]:
        return sorted(
            str(p.relative_to(self.base))
            for p in self.base.glob(pattern)
            if p.is_file()
        )

    def resolve_path(self, name: str) -> Path:
        return self.base / name
