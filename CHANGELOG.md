# Changelog

All notable changes to autodocs are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **Deterministic sync engine** (`sync_engine.py`) — PR fetching, classification, diff extraction, and report generation in Python. No LLM needed for sync. Supports all 4 platforms.
- **Deterministic apply engine** (`apply_engine.py`) — suggestion parsing, FIND/REPLACE editing, git branch/commit/push, and PR creation in Python. No LLM needed for apply.
- **Multi-backend LLM runner** (`llm_runner.py`) — `LLMRunner` ABC with `CLIRunner` (Claude Code CLI) and `APIRunner` (Anthropic API with Read/Write agentic loop). Configure via `llm.backend` in config.
- **Webhook server** (`webhook_server.py`) — FastAPI endpoint receiving PR merge webhooks from GitHub/GitLab/Bitbucket for real-time pipeline triggers.
- **Storage abstraction** (`storage.py`) — `Storage` protocol with `LocalStorage` implementation. Atomic writes via write-to-temp-then-`os.replace()`. Path traversal protection.
- **Config schema validation** (`schema_helper.py`) — validates config.yaml structure at pipeline start. Catches platform, docs, auto_pr, and llm config errors.
- **Pipeline lock in orchestrator** — `PipelineLock` using atomic `mkdir`, protecting all entry points (cron, webhook, direct invocation). Stale lock detection (>2 hours).
- **Review thread fetching** — fetches PR review comments from all 4 platforms (GitHub API, GitLab notes, Bitbucket comments, ADO threads). Bot reviews filtered.
- **Git-first PR discovery** — discovers relevant PRs via `git log --first-parent -- relevant_paths/` instead of fetching all PRs from platform API. Works identically across all 4 platforms. Critical for monorepos: 1000 daily merges but 10 relevant → only 10 processed. Falls back to platform API when git discovery returns nothing.
- **Doc generation** (`generate.py`) — `setup.sh generate` reads a codebase and generates an architecture doc + config.yaml with package_map derived from doc sections. Investigation-based prompt (4 phases: reconnaissance, architecture mapping, deep dive, write). Zero manual doc writing or config editing.
- **Dynamic cross-cutting discovery** — `cross_cutting_packages` + `cross_cutting_identifiers` config fields. At sync time, greps external packages for your feature's identifiers to dynamically discover integration points. No static file list to maintain.
- **PR reviewer assignment** — `auto_pr.reviewers` config field. Assigns specified reviewers to every autodocs PR via platform CLI (GitHub, ADO, GitLab).
- **Security hardening** — Bitbucket API calls use `urllib.request` instead of `curl` subprocess (prevents token leak via `ps aux`). Path traversal protection in glob expansion and doc repo_path. Markdown injection prevention in PR titles.
- **Unit test suite** — 166 pytest tests covering orchestrator logic, apply engine, LLM runner, webhook server, cross-cutting discovery, and schema validation.
- **CI workflow** (`.github/workflows/test.yml`) — runs pytest + BATS on push and PR.
- **`pyproject.toml`** — dependency manifest with required (`pyyaml`) and optional groups (`api`, `webhook`, `dev`).

### Changed

- **Bash → Python orchestrator** — `sync.sh` reduced from 585 to 23 lines (PATH + exec). All pipeline logic in `orchestrator.py`.
- **2 LLM calls instead of 4** — sync and apply are deterministic Python. Only drift detection and suggestion generation use the LLM. Both only need Read/Write tools.
- **Pipeline lock moved from bash to Python** — protects all entry points, not just the cron wrapper.
- **Error classification in PR fetchers** — `FetchResult` with human-readable error messages and retryable/permanent distinction.
- **yaml import failures exit with code 2** — previously exited 0, silently skipping processing.
- **Type hints on all Python functions** — `from __future__ import annotations` + parameter/return types.

### Fixed

- `_parse_changelog_sections` shared-reference bug — replaced fragile `dict(sections)` rebuild with explicit `section_index`.
- Suggestion parser handles bare `>` blockquote lines in INSERT AFTER blocks.
- `_replace_normalized` simplified from 20-line character walker to 5-line regex approach.
- Path sanitization in `setup.sh` and `sync.sh` — `sys.argv` instead of string interpolation in Python heredocs.
- Stale `fetched-prs.json` between pipeline runs — cleaned at start, webhook data uses `webhook-prs.json` promotion pattern.
- Storage path traversal protection — `_safe_path()` validates all resolved paths.
- Atomic file writes in `LocalStorage.write()` — write-to-temp-then-`os.replace()`.
- Dead code: removed unused imports (`glob`, `os`, `field`), deprecated `handle_detect_corrections`.
- Branch prefix mismatch: `platform_helper.py` now reads from config instead of hardcoded constant.

### Migration

To upgrade from the previous (4-LLM-call bash) architecture:

```bash
cd autodocs
git pull
./setup.sh upgrade
```

This re-renders all prompts, scripts, and copies the new Python modules. Your `config.yaml` is preserved. The new architecture is backward-compatible — the default `llm.backend: cli` works identically to before, with sync and apply now running as deterministic Python (faster, cheaper, more reliable).

To use the Anthropic API backend instead of Claude Code CLI:

```yaml
# Add to config.yaml:
llm:
  backend: "api"
```

Set the `ANTHROPIC_API_KEY` environment variable before running.
