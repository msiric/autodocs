# Architecture

## Overview

autodocs uses 2 LLM calls daily (drift detection + suggestion generation), with deterministic Python handling everything else: PR fetching, classification, verification, edit application, git operations, and PR creation. A weekly structural scan runs separately. Each step is independent — downstream failures can't corrupt upstream output.

The LLM is only used for tasks that genuinely need natural language understanding. Every LLM output that affects documentation edits is verified by deterministic Python before being applied.

```
launchd/cron/GitHub Actions/webhook (daily)
    |
    v
autodocs-sync.sh → orchestrator.py
    |
    ├── Lock (bash), config validation, auth check, git fetch
    ├── Pre-sync: discover PRs, check state, detect corrections (Python)
    ├── Open PR limit check
    |
    ├── Step 1: Sync (deterministic Python — sync_engine.py)
    |   ├── Discover relevant PRs via git log + path filter
    |   ├── Fetch PR details from platform API (relevant PRs only)
    |   ├── Get changed files via git diff-tree
    |   ├── Get targeted diffs for mapped files
    |   ├── Fetch review threads for relevant PRs
    |   └── Write: daily-report.md, activity-log.md
    |
    ├── match-helper.py      (Python: file → section mapping)
    ├── drift-helper.py      (Python: parse, group, dedup, lifecycle)
    ├── Log match rate metric
    |
    ├── Step 2: Drift (LLM — Read/Write tools only)
    |   ├── Read drift-context.json (pre-processed)
    |   └── Write: drift-report.md, drift-status.md, drift-log.md
    |
    ├── drift-helper.py suggest-dedup  (Python: changelog + open PR filtering)
    ├── Copy mapped source files to source-context/ (Python)
    |
    ├── Step 3: Suggest (LLM — Read/Write tools only)
    |   ├── Read suggest-context.json + source files (ground truth)
    |   ├── Generate FIND/REPLACE with self-verification
    |   └── Write: drift-suggestions.md, changelog-*.md
    |
    ├── verify-helper.py verify-finds    (Python: FIND text exists in doc?)
    ├── verify-helper.py verify-replaces (Python: REPLACE values in source?)
    |   └── Three-tier gating: EVIDENCED → apply, MISMATCH → block, UNVERIFIED → review
    |
    ├── Shadow verify (optional, LLM, log-only — does not gate apply)
    |
    ├── Step 4: Apply (deterministic Python — apply_engine.py)
    |   ├── Parse and filter suggestions by verification gates
    |   ├── Apply FIND/REPLACE + INSERT AFTER to doc files
    |   ├── git: create branch, commit, push
    |   └── Platform CLI: create PR with autodocs label + metadata
    |
    ├── Write sync-status.md + metrics.jsonl
    └── Advance last-successful-run (only if relevant PRs processed)

launchd/cron/GitHub Actions (weekly, Saturday)
    |
    v
autodocs-structural-scan.sh → orchestrator.py --structural-scan
    |
    ├── Read reference docs, extract all file paths
    ├── git ls-files: verify each exists, find undocumented files
    ├── Suggest package_map additions
    └── Write: structural-report.md
```

## LLM Backend

autodocs supports two LLM backends, configured via `llm.backend` in config.yaml:

- **`cli`** (default): Claude Code CLI (`claude -p`). Supports all tools. Required for telemetry (Kusto).
- **`api`**: Anthropic API directly. Supports Read/Write tools (drift + suggest). No CLI installation needed.

Since Steps 1 and 4 are deterministic Python, both backends provide full pipeline functionality. The LLM is only invoked for Steps 2 and 3, which only need Read and Write tools.

## Storage Abstraction

The orchestrator uses a `Storage` protocol for file I/O, enabling future migration to S3/database backends. Currently backed by `LocalStorage` (filesystem). Helper scripts still receive filesystem paths via subprocess arguments — they will be migrated to direct function calls when a non-filesystem backend is needed.

## The git diff-tree Innovation

The Azure DevOps MCP provides `repo_get_pull_request_by_id` which returns PR metadata including the `lastMergeCommit.commitId` — but not the list of changed files.

autodocs works around this by using the local git repo:

```
ADO MCP                         Local Git Repo
   |                                  |
   | repo_get_pull_request_by_id      |
   | → lastMergeCommit.commitId       |
   |   "be0c278..."                   |
   |                                  |
   +----------------------------------+
                                      |
                         git diff-tree --no-commit-id \
                           --name-status -M -r be0c278...
                                      |
                                      v
                         M    packages/components/fluid/src/error/map.ts
                         A    packages/components/fluid/src/new-handler.ts
                         R100 packages/old-name.ts → packages/new-name.ts
                         D    packages/legacy/removed.ts
```

This requires:
- The repo is cloned locally (it is — that's where Claude Code runs)
- A `git fetch origin` before the sync (ensures merge commits from teammates are available)
- `Bash(git:*)` in the allowed tools list (scoped to git commands only)

The approach works for all merge strategies (squash, merge commit, rebase) because `lastMergeCommit` always points to the final commit on the target branch.

## Call Isolation

Each prompt runs as a separate Claude Code invocation with its own allowlist:

| Property | Step 1: Sync | Step 2: Drift | Step 3: Suggest | Step 3v: Verify | Step 4: Apply |
|----------|-------------|---------------|-----------------|-----------------|---------------|
| Engine | **Deterministic Python** | LLM (Read/Write) | LLM (Read/Write) | LLM (optional) | **Deterministic Python** |
| Purpose | Fetch PRs, classify, write report | Detect stale sections | Generate FIND/REPLACE | Verify FIND/REPLACE | Apply edits + open PR |
| Inputs | Platform CLI + git | drift-context.json, docs | suggest-context.json, source-context/, docs | drift-suggestions.md, docs | drift-suggestions.md, verification JSONs |
| Outputs | daily-report.md, activity-log.md | drift-report/status/log.md | drift-suggestions.md, changelog | drift-suggestions-verify.md | git branch + PR |
| Runs when | Always | Step 1 succeeded | HIGH/CRITICAL alerts | multi_model enabled | auto_pr + verified suggestions |

Key properties:
- Each step can fail without corrupting the others
- Steps 1 and 4 are deterministic Python — no LLM needed, identical results every run
- Steps 2 and 3 only need Read/Write tools — works with both CLI and API backends
- Step 3 reads actual source files (source-context/) as ground truth
- Step 4 only applies suggestions that pass both FIND and REPLACE verification
- Shadow verify (Step 3v) runs optionally — logs only, never gates apply

The weekly structural scan runs as a completely separate job with its own wrapper and schedule.

## Drift Detection Signals

### Signal 1: PR → Doc Section (file-path based)

```
PR changed files → extract package → look up package_map → doc section
```

- **HIGH confidence**: Package found in package_map, maps to specific section
- **CRITICAL**: Package in feature paths but NOT in package_map (unmapped — docs missing coverage)
- **LOW**: File paths unavailable from ADO (fallback — manual review needed)

For packages that span multiple doc sections (e.g., a shared utilities package), the config supports `title_hints` — keyword matching against the PR title to narrow down the section.

### Signal 2: Telemetry → Known Patterns

```
Kusto errors → compare against known_patterns_section in doc → flag NEW patterns
```

The sync prompt already compares telemetry errors against known patterns. The drift prompt reads the "Anomalies" section from the sync output and converts "NEW" flags into HIGH confidence drift alerts.

## Alert Lifecycle

```
NEW alert (today's sync)
    |
    v
drift-status.md: - [ ] 2026-03-02 | doc | section | PR #123 | HIGH
    |
    ├── User checks off in Obsidian → - [x] ... | resolved
    |
    ├── Same section flagged again → PR #456 appended (deduplicated)
    |
    ├── LOW alert, 7 days pass → auto-expired
    |
    └── 30 days pass → trimmed from file
```

## Security Model

### Read-only ADO access

Only 5 read-only ADO tools are in the allowlist:
- `repo_list_pull_requests_by_repo_or_project` — list merged PRs
- `repo_get_pull_request_by_id` — get PR details/merge commit
- `repo_list_pull_request_threads` — get PR review comments
- `search_code` — search repo (optional, for edge cases)
- `repo_get_repo_by_name_or_id` — resolve repo GUID (setup only)

Write operations (`repo_create_pull_request`, `repo_update_pull_request`, `wit_create_work_item`, etc.) are excluded.

### Predefined Kusto queries

The LLM never generates KQL. Queries are defined in config and copied verbatim. This prevents:
- Accidental expensive queries against production telemetry
- KQL injection via prompt manipulation
- Queries that expose PII

### Write sandbox

Each prompt can only write to its specific output files (enforced by the prompt's Rules section). The drift prompt cannot modify reference docs.

### Suggestions are advisory

The suggest prompt writes to `drift-suggestions.md` and `changelog-*.md`. It never modifies reference documentation. Suggestions include before/after diffs and confidence ratings — the human decides whether to apply them.

### Git scope

Only three git operations are used:
- `git fetch origin` — update remote refs (read-only)
- `git diff-tree` — list changed files for a commit (read-only)
- `git ls-files` — verify file existence for structural scan (read-only)

No modifications to the working tree, index, or branches.

### Data sanitization

Prompts explicitly prohibit including:
- Internal URLs
- Stack traces
- User identifiers (aggregated counts only)
- PII of any kind
