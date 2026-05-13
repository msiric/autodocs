"""Unit tests for orchestrator.ensure_worktree() — git worktree isolation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from orchestrator import (
    Logger,
    _default_worktree_path,
    _sync_worktree,
    ensure_worktree,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check:
        assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result


def _make_origin_and_clone(tmp_path: Path, target_branch: str = "master") -> tuple[Path, Path]:
    """Create a bare origin repo + a working clone with master branch.

    Returns (clone_dir, bare_dir). The clone has origin/<target_branch>
    resolvable, which is what ensure_worktree requires.
    """
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", target_branch, str(bare))

    clone = tmp_path / "clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", target_branch)
    _git(clone, "config", "user.email", "t@t.com")
    _git(clone, "config", "user.name", "Test")
    (clone / "README.md").write_text("# initial\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "init")
    _git(clone, "remote", "add", "origin", str(bare))
    _git(clone, "push", "-q", "origin", target_branch)
    return clone, bare


def _make_logger(tmp_path: Path) -> Logger:
    return Logger(tmp_path)


# ---------------------------------------------------------------------------
# First-run worktree creation
# ---------------------------------------------------------------------------

class TestWorktreeCreation:
    def test_creates_worktree_at_configured_path(self, tmp_path: Path):
        clone, _ = _make_origin_and_clone(tmp_path)
        wt = tmp_path / "wt"
        config = {
            "worktree_dir": str(wt),
            "auto_pr": {"target_branch": "master"},
        }
        result = ensure_worktree(clone, config, _make_logger(tmp_path))
        assert result == wt
        assert wt.exists()
        assert (wt / "README.md").exists()
        # Worktree should be on origin/master ref
        head = _git(wt, "rev-parse", "HEAD").stdout.strip()
        origin_head = _git(clone, "rev-parse", "origin/master").stdout.strip()
        assert head == origin_head

    def test_defaults_to_autodocs_worktrees_dir(self, tmp_path: Path, monkeypatch):
        """Without worktree_dir in config, default is ~/.autodocs-worktrees/<repo>."""
        clone, _ = _make_origin_and_clone(tmp_path)
        # Redirect HOME so default path lands in tmp_path
        monkeypatch.setenv("HOME", str(tmp_path))
        config = {"auto_pr": {"target_branch": "master"}}
        result = ensure_worktree(clone, config, _make_logger(tmp_path))
        expected = tmp_path / ".autodocs-worktrees" / clone.name
        assert result == expected
        assert expected.exists()

    def test_isolates_from_user_working_tree(self, tmp_path: Path):
        """Dirty/conflicted main checkout must not block worktree operations.

        This is the bug we set out to fix: when the user has uncommitted
        changes or unresolved merges in their main clone, autodocs would
        fail. The worktree is a separate working dir — main is untouched.
        """
        clone, _ = _make_origin_and_clone(tmp_path)
        # Pollute the main clone heavily
        (clone / "README.md").write_text("local edit\n")
        (clone / "untracked.txt").write_text("dirty\n")

        config = {"worktree_dir": str(tmp_path / "wt"), "auto_pr": {"target_branch": "master"}}
        wt = ensure_worktree(clone, config, _make_logger(tmp_path))

        # Worktree is clean
        status = _git(wt, "status", "--porcelain").stdout
        assert status == "", f"worktree not clean: {status!r}"
        # Main checkout still has its local edits — untouched
        assert (clone / "README.md").read_text() == "local edit\n"
        assert (clone / "untracked.txt").exists()


# ---------------------------------------------------------------------------
# Subsequent-run sync
# ---------------------------------------------------------------------------

class TestWorktreeSync:
    def test_subsequent_run_pulls_latest_origin(self, tmp_path: Path):
        """After worktree exists, the next run should sync to current origin."""
        clone, bare = _make_origin_and_clone(tmp_path)
        wt = tmp_path / "wt"
        config = {"worktree_dir": str(wt), "auto_pr": {"target_branch": "master"}}

        # First run — creates worktree at initial state
        ensure_worktree(clone, config, _make_logger(tmp_path))
        initial_head = _git(wt, "rev-parse", "HEAD").stdout.strip()

        # Someone else pushes a new commit to origin/master
        (clone / "new-file.ts").write_text("export function added() {}\n")
        _git(clone, "add", ".")
        _git(clone, "commit", "-q", "-m", "add new file")
        _git(clone, "push", "-q", "origin", "master")
        new_head = _git(clone, "rev-parse", "origin/master").stdout.strip()
        assert new_head != initial_head

        # Second run — must sync worktree to the new origin commit
        ensure_worktree(clone, config, _make_logger(tmp_path))
        synced_head = _git(wt, "rev-parse", "HEAD").stdout.strip()
        assert synced_head == new_head
        assert (wt / "new-file.ts").exists()

    def test_sync_discards_stale_files_in_worktree(self, tmp_path: Path):
        """If a previous autodocs run left files behind, sync cleans them up.

        Without `git clean -fd`, untracked artifacts from a previous run
        would accumulate in the worktree across days.
        """
        clone, _ = _make_origin_and_clone(tmp_path)
        wt = tmp_path / "wt"
        config = {"worktree_dir": str(wt), "auto_pr": {"target_branch": "master"}}
        ensure_worktree(clone, config, _make_logger(tmp_path))

        # Pollute the worktree as if a previous run crashed mid-apply
        (wt / "leftover.tmp").write_text("stale\n")
        (wt / "README.md").write_text("locally hacked\n")

        # Second run must clean up
        ensure_worktree(clone, config, _make_logger(tmp_path))
        assert not (wt / "leftover.tmp").exists(), "untracked file should be cleaned"
        assert "locally hacked" not in (wt / "README.md").read_text()


# ---------------------------------------------------------------------------
# Fallback behavior — safe degradation
# ---------------------------------------------------------------------------

class TestFallbackToMainRepo:
    def test_no_origin_remote_falls_back(self, tmp_path: Path):
        """Repo without origin remote → fall back to main checkout, log warning."""
        clone = tmp_path / "clone"
        clone.mkdir()
        _git(clone, "init", "-q", "-b", "master")
        _git(clone, "config", "user.email", "t@t.com")
        _git(clone, "config", "user.name", "Test")
        (clone / "f.txt").write_text("x\n")
        _git(clone, "add", ".")
        _git(clone, "commit", "-q", "-m", "init")
        # No remote add — so origin/master doesn't exist

        config = {"worktree_dir": str(tmp_path / "wt"), "auto_pr": {"target_branch": "master"}}
        result = ensure_worktree(clone, config, _make_logger(tmp_path))
        # Falls back to main repo
        assert result == clone
        # And the worktree directory was NOT created
        assert not (tmp_path / "wt").exists()

    def test_worktree_path_equals_repo_dir_falls_back(self, tmp_path: Path):
        """If worktree_dir resolves to the same path as repo_dir, refuse to use it.

        Using the same dir would defeat the entire purpose of isolation.
        """
        clone, _ = _make_origin_and_clone(tmp_path)
        config = {"worktree_dir": str(clone), "auto_pr": {"target_branch": "master"}}
        result = ensure_worktree(clone, config, _make_logger(tmp_path))
        assert result == clone  # falls back to main repo


# ---------------------------------------------------------------------------
# _default_worktree_path
# ---------------------------------------------------------------------------

class TestDefaultWorktreePath:
    def test_uses_repo_basename(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", "/Users/test")
        result = _default_worktree_path(Path("/some/dir/teams-modular-packages"))
        assert result == Path("/Users/test/.autodocs-worktrees/teams-modular-packages")
