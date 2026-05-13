"""Unit tests for verify-helper.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# verify-helper.py contains a hyphen, so import via importlib
_VH_PATH = Path(__file__).parent.parent / "scripts" / "verify-helper.py"
_spec = importlib.util.spec_from_file_location("verify_helper", _VH_PATH)
verify_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_helper)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SUGGESTIONS_TEMPLATE = """---
date: 2026-05-13
suggestion_count: 1
verified: 1/1
---
# Suggested Updates — 2026-05-13

## architecture.md — Error Handling
**Triggered by:** PR #1 "Test"
**Confidence:** CONFIDENT

### FIND (in architecture.md, section "Error Handling"):
> existing line in doc

### REPLACE WITH:
> The new error type `{IDENT}` is now handled.

**Verified:** YES — FIND text confirmed in doc

### Reasoning:
Test suggestion.

---
"""


def _make_workspace(tmp_path: Path, identifier: str,
                    source_context_files: dict[str, str] | None = None,
                    repo_files: dict[str, str] | None = None,
                    config: dict | None = None) -> Path:
    """Build a workspace for verify_replaces. Returns the output_dir."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "drift-suggestions.md").write_text(
        SUGGESTIONS_TEMPLATE.replace("{IDENT}", identifier)
    )

    # source-context (the curated subset the LLM had)
    if source_context_files is not None:
        sc = output_dir / "source-context"
        sc.mkdir()
        for path, content in source_context_files.items():
            f = sc / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)

    # repo files (the broader ground truth)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    if repo_files is not None:
        for path, content in repo_files.items():
            f = repo_dir / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)

    if config is not None:
        import yaml
        (output_dir / "config.yaml").write_text(yaml.safe_dump(config))

    return output_dir, repo_dir


def _gate(output_dir: Path) -> str:
    """Read the first suggestion's gate from replace-verification.json."""
    data = json.loads((output_dir / "replace-verification.json").read_text())
    return data[0]["gate"] if data else "MISSING"


def _value_status(output_dir: Path, value: str) -> str:
    """Read the status of a specific value from replace-verification.json."""
    data = json.loads((output_dir / "replace-verification.json").read_text())
    for entry in data:
        for v in entry.get("values", []):
            if v["value"] == value:
                return v["status"]
    return "MISSING"


# ---------------------------------------------------------------------------
# Existing behavior: source-context primary search
# ---------------------------------------------------------------------------

class TestSourceContextSearch:
    def test_identifier_found_in_source_context_evidenced(self, tmp_path: Path):
        """Baseline: identifier present in source-context → EVIDENCED."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="MyError",
            source_context_files={"handler.ts": "export class MyError extends Error {}"},
        )
        verify_helper.verify_replaces(out, repo)
        assert _value_status(out, "MyError") == "EVIDENCED"
        assert _gate(out) == "AUTO_APPLY"

    def test_identifier_absent_everywhere_mismatch(self, tmp_path: Path):
        """Hallucinated identifier (nowhere) → MISMATCH → BLOCK."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="HallucinatedError",
            source_context_files={"handler.ts": "export class RealError {}"},
            repo_files={"src/handler.ts": "export class RealError {}"},
            config={
                "relevant_paths": ["src/"],
                "cross_cutting_packages": [],
            },
        )
        verify_helper.verify_replaces(out, repo)
        assert _value_status(out, "HallucinatedError") == "MISMATCH"
        assert _gate(out) == "BLOCK"


# ---------------------------------------------------------------------------
# NEW behavior: repo-wide fallback when source-context is incomplete
# ---------------------------------------------------------------------------

class TestRepoFallback:
    def test_identifier_in_repo_but_not_source_context_evidenced(self, tmp_path: Path):
        """Identifier exists in repo file NOT included in source-context.
        Should fall back to repo search and find it → EVIDENCED.

        This is the bug fix: previously this returned MISMATCH because the
        verifier only checked source-context.
        """
        out, repo = _make_workspace(
            tmp_path,
            identifier="ChannelPageOutOfStorageError",
            source_context_files={
                # source-context has unrelated files — does NOT contain the identifier
                "users.ts": "export function listUsers() {}",
            },
            repo_files={
                # the actual repo has the identifier in a cross-cutting package
                "packages/components/components-fluid/src/error/fluid-error-details-map.ts":
                    "export class ChannelPageOutOfStorageError extends Error {}",
            },
            config={
                "relevant_paths": ["packages/apps/"],
                "cross_cutting_packages": ["packages/components/components-fluid/"],
            },
        )
        verify_helper.verify_replaces(out, repo)
        status = _value_status(out, "ChannelPageOutOfStorageError")
        assert status == "EVIDENCED", f"Expected EVIDENCED, got {status}"

    def test_identifier_in_relevant_paths_evidenced(self, tmp_path: Path):
        """Identifier in relevant_paths (not just cross_cutting) → EVIDENCED."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="useChannelPageData",
            source_context_files={},
            repo_files={
                "packages/apps/apps-channel-pages/src/hook.ts":
                    "export function useChannelPageData() {}",
            },
            config={
                "relevant_paths": ["packages/apps/apps-channel-pages/"],
                "cross_cutting_packages": [],
            },
        )
        verify_helper.verify_replaces(out, repo)
        assert _value_status(out, "useChannelPageData") == "EVIDENCED"

    def test_glob_pattern_in_relevant_paths_expanded(self, tmp_path: Path):
        """relevant_paths glob like 'packages/apps/apps-channel-pages-*' should expand."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="useGlobMatched",
            source_context_files={},
            repo_files={
                "packages/apps/apps-channel-pages-extra/hook.ts":
                    "export function useGlobMatched() {}",
            },
            config={
                "relevant_paths": ["packages/apps/apps-channel-pages-*/"],
                "cross_cutting_packages": [],
            },
        )
        verify_helper.verify_replaces(out, repo)
        assert _value_status(out, "useGlobMatched") == "EVIDENCED"

    def test_repo_fallback_skipped_when_no_repo_dir(self, tmp_path: Path):
        """Without repo_dir, fall back is disabled — preserves legacy behavior."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="NotFound",
            source_context_files={"unrelated.ts": "x"},
            repo_files={
                "src/handler.ts": "export class NotFound {}",
            },
            config={"relevant_paths": ["src/"]},
        )
        # Pass repo_dir=None → no fallback search
        verify_helper.verify_replaces(out, repo_dir=None)
        assert _value_status(out, "NotFound") == "MISMATCH"

    def test_no_config_yaml_graceful(self, tmp_path: Path):
        """Missing config.yaml → fallback is disabled, behavior degrades gracefully."""
        out, repo = _make_workspace(
            tmp_path,
            identifier="StillMissing",
            source_context_files={"unrelated.ts": "x"},
            repo_files={"src/handler.ts": "export class StillMissing {}"},
            config=None,  # no config.yaml written
        )
        verify_helper.verify_replaces(out, repo)
        # No config → no search paths → MISMATCH (legacy behavior)
        assert _value_status(out, "StillMissing") == "MISMATCH"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

class TestPathSafety:
    def test_traversal_in_relevant_paths_rejected(self, tmp_path: Path):
        """A malicious '../../etc' in relevant_paths must not escape repo_dir."""
        import yaml as _yaml
        out, repo = _make_workspace(
            tmp_path,
            identifier="WontMatter",
            source_context_files={"unrelated.ts": "x"},  # ensures verify runs
            repo_files={"src/handler.ts": "export class Foo {}"},
            config={"relevant_paths": ["../../etc/"]},
        )
        # Directly test _config_search_paths — it must reject the traversal
        config = _yaml.safe_load((out / "config.yaml").read_text())
        paths = verify_helper._config_search_paths(config, repo)
        # No path outside repo should be returned
        for p in paths:
            assert str(p).startswith(str(repo.resolve())), \
                f"Path {p} escaped repo dir {repo}"
        # Verify_replaces still runs (source-context has content) and produces output
        verify_helper.verify_replaces(out, repo)
        # Identifier not anywhere → MISMATCH (legacy behavior preserved)
        assert _value_status(out, "WontMatter") == "MISMATCH"
