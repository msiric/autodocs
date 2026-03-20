"""Shared pytest fixtures for autodocs tests."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Create a minimal output directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def minimal_config() -> dict:
    """Minimal valid github config."""
    return {
        "platform": "github",
        "github": {"owner": "testuser", "repo": "testrepo"},
        "feature_name": "Test Feature",
        "owner": {"name": "Alice", "github_username": "alice"},
        "team_members": [],
        "relevant_paths": ["src/"],
        "relevant_pattern": "test-feature",
        "docs": [{"name": "guide.md", "package_map": {"auth": "Authentication"}}],
    }
