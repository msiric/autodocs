"""Unit tests for pipeline-helper.py copy_sources git-show behavior."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# pipeline-helper.py has a hyphen — import via importlib
_PH_PATH = Path(__file__).parent.parent / "scripts" / "pipeline-helper.py"
_SCRIPTS_DIR = str(_PH_PATH.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)  # for platform_helper import
_spec = importlib.util.spec_from_file_location("pipeline_helper", _PH_PATH)
pipeline_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline_helper)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    """Run a git command, asserting success."""
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


def _init_repo_with_master(repo: Path, files: dict[str, str]) -> None:
    """Create a fake 'origin/master' state via a real local git repo.

    Sets up: repo/ with master branch containing `files`, then creates a
    fake 'origin' remote (a bare repo) that mirrors master. This lets the
    code-under-test resolve `origin/master` via standard git plumbing.
    """
    bare = repo.parent / "origin.git"
    _git(repo.parent, "init", "--bare", str(bare))

    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    for path, content in files.items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "master")


def _write_mappings(output_dir: Path, entries: list[tuple[str, str, str]]) -> None:
    """Write resolved-mappings.md from (change_type, path, section) tuples."""
    lines = []
    for change_type, path, section in entries:
        lines.append(f"{change_type} {path} → {section}")
    (output_dir / "resolved-mappings.md").write_text("\n".join(lines) + "\n")


def _write_config(output_dir: Path, target_branch: str = "master") -> None:
    """Write a minimal config.yaml."""
    import yaml as _yaml
    (output_dir / "config.yaml").write_text(_yaml.safe_dump({
        "auto_pr": {"target_branch": target_branch},
    }))


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Set up output_dir and empty repo directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    return output_dir, repo_dir


# ---------------------------------------------------------------------------
# copy_sources reads from origin/<target_branch>
# ---------------------------------------------------------------------------

class TestOriginRefRead:
    def test_file_on_origin_master_is_copied(self, tmp_path: Path):
        """File exists on origin/master → copied with origin's content."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/handler.ts": "// origin version\nexport function handler() {}",
        })
        _write_config(output_dir)
        _write_mappings(output_dir, [("M", "src/handler.ts", "API Endpoints")])

        copied = pipeline_helper.copy_sources(output_dir, repo_dir)

        assert copied == 1
        result_path = output_dir / "source-context" / "src/handler.ts"
        assert result_path.exists()
        assert "origin version" in result_path.read_text()

    def test_working_tree_diverges_from_origin_uses_origin(self, tmp_path: Path):
        """If working tree has different content than origin/master, prefer origin.

        This is the critical bug we're fixing: previously copy_sources used the
        working tree; now it must use origin/master regardless of local state.
        """
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/handler.ts": "// origin content\n",
        })
        # Modify the working tree locally (simulates user being on a feature branch)
        (repo_dir / "src/handler.ts").write_text("// LOCAL EDIT — should not appear\n")
        _write_config(output_dir)
        _write_mappings(output_dir, [("M", "src/handler.ts", "API Endpoints")])

        pipeline_helper.copy_sources(output_dir, repo_dir)

        content = (output_dir / "source-context" / "src/handler.ts").read_text()
        assert "origin content" in content
        assert "LOCAL EDIT" not in content, "must use origin/master, not working tree"

    def test_deleted_files_skipped(self, tmp_path: Path):
        """'D' change_type means file was deleted on target → must skip."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/keep.ts": "// kept\n",
        })
        # The 'D' entry references a file that doesn't exist on origin/master
        _write_config(output_dir)
        _write_mappings(output_dir, [
            ("M", "src/keep.ts", "Section"),
            ("D", "src/deleted.ts", "Section"),
        ])

        copied = pipeline_helper.copy_sources(output_dir, repo_dir)

        assert copied == 1
        assert (output_dir / "source-context/src/keep.ts").exists()
        assert not (output_dir / "source-context/src/deleted.ts").exists()

    def test_added_files_copied_from_origin(self, tmp_path: Path):
        """'A' change_type files should be fetched from origin, not skipped."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/new-feature.ts": "// new feature on origin\n",
        })
        _write_config(output_dir)
        _write_mappings(output_dir, [("A", "src/new-feature.ts", "Section")])

        pipeline_helper.copy_sources(output_dir, repo_dir)

        result = (output_dir / "source-context/src/new-feature.ts").read_text()
        assert "new feature on origin" in result

    def test_renamed_path_resolved_at_origin(self, tmp_path: Path):
        """'R' change_type: mapping holds the new path, fetched from origin."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/new-name.ts": "// renamed file\n",
        })
        _write_config(output_dir)
        _write_mappings(output_dir, [("R", "src/new-name.ts", "Section")])

        pipeline_helper.copy_sources(output_dir, repo_dir)

        assert (output_dir / "source-context/src/new-name.ts").exists()


# ---------------------------------------------------------------------------
# Graceful fallback to working tree
# ---------------------------------------------------------------------------

class TestFallbackToWorkingTree:
    def test_no_origin_ref_falls_back(self, tmp_path: Path, capsys):
        """If origin/master doesn't exist locally, fall back to working tree."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        # Init a repo WITHOUT origin remote
        _git(repo_dir, "init", "-q", "-b", "master")
        _git(repo_dir, "config", "user.email", "t@t.com")
        _git(repo_dir, "config", "user.name", "T")
        (repo_dir / "src").mkdir()
        (repo_dir / "src/handler.ts").write_text("// working tree only\n")
        _git(repo_dir, "add", ".")
        _git(repo_dir, "commit", "-q", "-m", "init")

        _write_config(output_dir)
        _write_mappings(output_dir, [("M", "src/handler.ts", "Section")])

        pipeline_helper.copy_sources(output_dir, repo_dir)

        # File should still be copied via fallback path
        result = output_dir / "source-context/src/handler.ts"
        assert result.exists()
        assert "working tree only" in result.read_text()
        # And the fallback warning should be on stderr
        captured = capsys.readouterr()
        assert "falling back to working tree" in captured.err

    def test_file_unavailable_anywhere_skipped(self, tmp_path: Path):
        """If a file is in mappings but missing on origin AND working tree, skip it."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {"src/exists.ts": "// exists\n"})
        _write_config(output_dir)
        _write_mappings(output_dir, [
            ("M", "src/exists.ts", "Section"),
            ("M", "src/never-existed.ts", "Section"),
        ])

        copied = pipeline_helper.copy_sources(output_dir, repo_dir)

        assert copied == 1  # only the real file
        assert (output_dir / "source-context/src/exists.ts").exists()
        assert not (output_dir / "source-context/src/never-existed.ts").exists()


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------

class TestConfigHandling:
    def test_no_config_defaults_to_main(self, tmp_path: Path, capsys):
        """Without config.yaml, target_branch defaults to 'main'."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        # Build a real master branch
        _init_repo_with_master(repo_dir, {"src/x.ts": "// master\n"})
        # No config — default is 'main', which doesn't exist → fallback warning
        _write_mappings(output_dir, [("M", "src/x.ts", "Section")])

        pipeline_helper.copy_sources(output_dir, repo_dir)

        # Working tree fallback should still produce the file
        assert (output_dir / "source-context/src/x.ts").exists()
        captured = capsys.readouterr()
        assert "origin/main" in captured.err  # default branch attempted

    def test_unmapped_section_skipped(self, tmp_path: Path):
        """Entries with section == 'UNMAPPED' are not copied (existing behavior)."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "src/mapped.ts": "// mapped\n",
            "src/unmapped.ts": "// unmapped\n",
        })
        _write_config(output_dir)
        _write_mappings(output_dir, [
            ("M", "src/mapped.ts", "Section"),
            ("M", "src/unmapped.ts", "UNMAPPED"),
        ])

        copied = pipeline_helper.copy_sources(output_dir, repo_dir)

        assert copied == 1
        assert (output_dir / "source-context/src/mapped.ts").exists()
        assert not (output_dir / "source-context/src/unmapped.ts").exists()


# ---------------------------------------------------------------------------
# sync_canonical_docs — output_dir mirror of master-side doc + changelog
# ---------------------------------------------------------------------------
# Without this sync, the suggest LLM reads from output_dir/<doc>.md which is
# never refreshed (observed: 6 weeks stale in production), and suggest_dedup
# reads output_dir/changelog-<doc>.md which accumulates entries from every
# autodocs PR — including the ones that were abandoned and never landed on
# master. Both produce silent false negatives for real drift.

def _write_docs_config(output_dir: Path, docs: list[dict], target_branch: str = "master") -> None:
    """Write config.yaml with a docs[] list."""
    import yaml as _yaml
    (output_dir / "config.yaml").write_text(_yaml.safe_dump({
        "auto_pr": {"target_branch": target_branch},
        "docs": docs,
    }))


class TestSyncCanonicalDocs:
    def test_refreshes_doc_from_master(self, tmp_path: Path):
        """The local doc copy is overwritten with master's current content."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "docs/area/architecture.md": "MASTER CONTENT\n",
        })
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])
        # Local file is stale
        (output_dir / "architecture.md").write_text("STALE LOCAL\n")

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "architecture.md").read_text() == "MASTER CONTENT\n"

    def test_refreshes_changelog_from_master(self, tmp_path: Path):
        """If master has the changelog, local is overwritten with master's."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "docs/area/architecture.md": "doc\n",
            "docs/area/changelog-architecture.md": "MASTER CHANGELOG\n",
        })
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])
        # Local changelog has phantom entries from abandoned PRs
        (output_dir / "changelog-architecture.md").write_text(
            "PHANTOM ENTRIES\n### PR #999 by ghost\n"
        )

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "changelog-architecture.md").read_text() == "MASTER CHANGELOG\n"

    def test_removes_local_changelog_when_master_has_none(self, tmp_path: Path):
        """The critical case: master has no changelog file. Any local copy is
        accumulator state from abandoned autodocs PRs (the bug we observed in
        production) and must be removed so suggest_dedup sees a clean slate."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        # Master has the doc but NOT the changelog
        _init_repo_with_master(repo_dir, {
            "docs/area/architecture.md": "doc\n",
        })
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])
        # Local changelog exists (phantom from abandoned PRs)
        (output_dir / "changelog-architecture.md").write_text(
            "## Section\n### 2026-05-13 — PR #123 by ghost\n**Changed:** never shipped\n"
        )

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert not (output_dir / "changelog-architecture.md").exists(), \
            "local changelog must be removed when master has no changelog"

    def test_preserves_local_doc_when_master_has_none(self, tmp_path: Path):
        """Bootstrap case: user stages a new doc that's not yet on master.
        The local copy must be preserved so the apply step can ship it via the
        first autodocs PR. Wiping it here would block the bootstrap path."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        # Master has neither doc nor changelog
        _init_repo_with_master(repo_dir, {
            "README.md": "placeholder\n",  # unrelated; just so master has a commit
        })
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])
        # User has the doc staged locally
        (output_dir / "architecture.md").write_text("BOOTSTRAPPING NEW DOC\n")

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "architecture.md").read_text() == "BOOTSTRAPPING NEW DOC\n", \
            "local doc must be preserved when master has no copy"

    def test_no_op_when_origin_ref_missing(self, tmp_path: Path, capsys):
        """If origin/<target_branch> is unreachable (e.g., shallow clone), do
        not touch local files. Matches copy_sources's fallback semantics."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        # repo_dir is empty — no origin/master
        _git(repo_dir, "init", "-q", "-b", "master")
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])
        (output_dir / "architecture.md").write_text("LOCAL\n")
        (output_dir / "changelog-architecture.md").write_text("LOCAL CHANGELOG\n")

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "architecture.md").read_text() == "LOCAL\n"
        assert (output_dir / "changelog-architecture.md").read_text() == "LOCAL CHANGELOG\n"
        assert "origin/master" in capsys.readouterr().err

    def test_multi_doc_config(self, tmp_path: Path):
        """Each doc + companion changelog in config.docs is processed."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "docs/a/arch.md": "ARCH MASTER\n",
            "docs/a/changelog-arch.md": "ARCH CHANGELOG MASTER\n",
            "docs/b/guide.md": "GUIDE MASTER\n",
            # No changelog for guide on master
        })
        _write_docs_config(output_dir, [
            {"name": "arch.md", "repo_path": "docs/a/arch.md"},
            {"name": "guide.md", "repo_path": "docs/b/guide.md"},
        ])
        (output_dir / "arch.md").write_text("STALE\n")
        (output_dir / "guide.md").write_text("STALE\n")
        (output_dir / "changelog-arch.md").write_text("STALE\n")
        (output_dir / "changelog-guide.md").write_text("PHANTOM\n")

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "arch.md").read_text() == "ARCH MASTER\n"
        assert (output_dir / "guide.md").read_text() == "GUIDE MASTER\n"
        assert (output_dir / "changelog-arch.md").read_text() == "ARCH CHANGELOG MASTER\n"
        # Guide has no changelog on master → local phantom removed
        assert not (output_dir / "changelog-guide.md").exists()

    def test_idempotent(self, tmp_path: Path):
        """Running twice produces identical state. Critical because the orchestrator
        invokes this every pipeline run."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {
            "docs/area/architecture.md": "MASTER\n",
            "docs/area/changelog-architecture.md": "MASTER CHANGELOG\n",
        })
        _write_docs_config(output_dir, [
            {"name": "architecture.md", "repo_path": "docs/area/architecture.md"},
        ])

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)
        first_doc = (output_dir / "architecture.md").read_bytes()
        first_changelog = (output_dir / "changelog-architecture.md").read_bytes()

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)
        second_doc = (output_dir / "architecture.md").read_bytes()
        second_changelog = (output_dir / "changelog-architecture.md").read_bytes()

        assert first_doc == second_doc
        assert first_changelog == second_changelog

    def test_empty_docs_list_is_noop(self, tmp_path: Path):
        """Config without docs[] entries → no-op (don't crash)."""
        output_dir, repo_dir = _make_workspace(tmp_path)
        _init_repo_with_master(repo_dir, {"README.md": "x\n"})
        # No docs in config
        import yaml as _yaml
        (output_dir / "config.yaml").write_text(_yaml.safe_dump({
            "auto_pr": {"target_branch": "master"},
        }))
        (output_dir / "stray.md").write_text("untouched\n")

        pipeline_helper.sync_canonical_docs(output_dir, repo_dir)

        assert (output_dir / "stray.md").read_text() == "untouched\n"
