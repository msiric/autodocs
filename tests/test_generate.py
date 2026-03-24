"""Unit tests for generate.py — file discovery, section parsing, config generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate import (
    build_config,
    detect_relevant_paths,
    detect_source_dirs,
    discover_source_files,
    extract_sections,
    infer_package_map,
    read_source_context,
)


# ---------------------------------------------------------------------------
# discover_source_files
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_finds_ts_files(self, tmp_path: Path):
        (tmp_path / "src" / "api").mkdir(parents=True)
        (tmp_path / "src" / "api" / "users.ts").write_text("export function listUsers() {}")
        (tmp_path / "src" / "api" / "health.ts").write_text("export function health() {}")
        files = discover_source_files(tmp_path)
        assert len(files) == 2
        assert files[0]["path"] == "src/api/health.ts"
        assert files[1]["path"] == "src/api/users.ts"

    def test_finds_py_files(self, tmp_path: Path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "main.py").write_text("def main(): pass")
        files = discover_source_files(tmp_path)
        assert len(files) == 1
        assert files[0]["path"] == "scripts/main.py"

    def test_skips_node_modules(self, tmp_path: Path):
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("console.log('hi')")
        files = discover_source_files(tmp_path)
        assert len(files) == 1
        assert "node_modules" not in files[0]["path"]

    def test_skips_test_files(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("export function app() {}")
        (tmp_path / "src" / "app.test.ts").write_text("test('app', () => {})")
        (tmp_path / "src" / "app.spec.ts").write_text("describe('app', () => {})")
        files = discover_source_files(tmp_path)
        assert len(files) == 1

    def test_relevant_dirs_filter(self, tmp_path: Path):
        (tmp_path / "src" / "api").mkdir(parents=True)
        (tmp_path / "src" / "auth").mkdir(parents=True)
        (tmp_path / "src" / "api" / "users.ts").write_text("export function listUsers() {}")
        (tmp_path / "src" / "auth" / "jwt.ts").write_text("export function requireJWT() {}")
        files = discover_source_files(tmp_path, relevant_dirs=["src/api"])
        assert len(files) == 1
        assert "api" in files[0]["path"]

    def test_empty_repo(self, tmp_path: Path):
        files = discover_source_files(tmp_path)
        assert files == []

    def test_counts_lines(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("line1\nline2\nline3\n")
        files = discover_source_files(tmp_path)
        assert files[0]["lines"] == 3


# ---------------------------------------------------------------------------
# read_source_context
# ---------------------------------------------------------------------------

class TestReadSourceContext:
    def test_includes_file_tree(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("export function app() {}")
        files = discover_source_files(tmp_path)
        context = read_source_context(tmp_path, files)
        assert "## File tree" in context
        assert "src/app.ts" in context

    def test_includes_file_content(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("export function app() { return 42; }")
        files = discover_source_files(tmp_path)
        context = read_source_context(tmp_path, files)
        assert "export function app()" in context

    def test_respects_token_budget(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        # Create a large file that exceeds a tiny budget
        (tmp_path / "src" / "big.ts").write_text("x\n" * 10000)
        files = discover_source_files(tmp_path)
        context = read_source_context(tmp_path, files, max_tokens=100)
        assert "truncated" in context.lower() or "Skipped" in context


# ---------------------------------------------------------------------------
# extract_sections
# ---------------------------------------------------------------------------

class TestExtractSections:
    def test_extracts_h2_headers(self):
        doc = "# Title\n\n## API Endpoints\n\nContent.\n\n## Authentication\n\nMore.\n"
        sections = extract_sections(doc)
        assert len(sections) == 2
        assert sections[0]["name"] == "API Endpoints"
        assert sections[1]["name"] == "Authentication"

    def test_skips_table_of_contents(self):
        doc = "## Table of Contents\n\n## Real Section\n"
        sections = extract_sections(doc)
        assert len(sections) == 1
        assert sections[0]["name"] == "Real Section"

    def test_strips_numbering(self):
        doc = "## 1. API Endpoints\n\n## 2. Authentication\n"
        sections = extract_sections(doc)
        assert sections[0]["name"] == "API Endpoints"
        assert sections[1]["name"] == "Authentication"

    def test_ignores_h3(self):
        doc = "## Section\n\n### Subsection\n\n## Another\n"
        sections = extract_sections(doc)
        assert len(sections) == 2


# ---------------------------------------------------------------------------
# detect_source_dirs + infer_package_map
# ---------------------------------------------------------------------------

class TestPackageMap:
    def test_detect_source_dirs(self):
        files = [
            {"path": "src/api/users.ts", "lines": 100},
            {"path": "src/auth/jwt.ts", "lines": 50},
            {"path": "src/errors/handler.ts", "lines": 80},
        ]
        dirs = detect_source_dirs(files)
        assert "src/api" in dirs
        assert "src/auth" in dirs
        assert "src/errors" in dirs

    def test_detect_relevant_paths(self):
        dirs = ["src/api", "src/auth"]
        paths = detect_relevant_paths(dirs)
        assert paths == ["src/api/", "src/auth/"]

    def test_infer_package_map(self):
        doc = (
            "## API Endpoints\n\n"
            "The `src/api/users.ts` file handles user CRUD.\n\n"
            "## Authentication\n\n"
            "The `src/auth/jwt.ts` file handles JWT tokens.\n\n"
            "## File Index\n\n"
            "| src/api/users.ts | Users |\n"
            "| src/auth/jwt.ts | Auth |\n"
        )
        sections = extract_sections(doc)
        source_dirs = ["src/api", "src/auth"]
        pm = infer_package_map(sections, source_dirs, doc)
        assert pm.get("api") == "API Endpoints"
        assert pm.get("auth") == "Authentication"

    def test_infer_package_map_no_references(self):
        doc = "## Overview\n\nGeneral description.\n\n## File Index\n\n"
        sections = extract_sections(doc)
        pm = infer_package_map(sections, ["src/api"], doc)
        assert pm == {}


# ---------------------------------------------------------------------------
# build_config
# ---------------------------------------------------------------------------

class TestBuildConfig:
    def test_generates_valid_yaml(self, tmp_path: Path):
        # Create a minimal git repo for detection
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
            cwd=str(tmp_path), capture_output=True,
        )
        import yaml
        config_text = build_config(
            tmp_path, "docs/arch.md", "arch.md",
            {"api": "API Endpoints"}, ["src/api/"], "Test Repo",
        )
        config = yaml.safe_load(config_text)
        assert config["platform"] == "github"
        assert config["docs"][0]["name"] == "arch.md"
        assert config["docs"][0]["package_map"]["api"] == "API Endpoints"
        assert "src/api/" in config["relevant_paths"]
