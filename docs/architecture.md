# Architecture

## Overview

autodocs runs up to 4 sequential Claude Code headless calls daily, with deterministic Python pre/post-processing between each call. A weekly structural scan runs separately. Each call is independent — downstream failures can't corrupt upstream output.

The pipeline alternates between deterministic code (Python/bash — reliable, testable) and LLM calls (Claude — for natural language understanding and generation). Every LLM output that affects documentation edits is verified by Python before being applied.

```
launchd/cron/GitHub Actions (daily)
    |
    v
autodocs-sync.sh
    |
    ├── Lock, auth check, git fetch
    ├── Compute current-date.txt + lookback-date.txt (bash, deterministic)
    ├── Pre-fetch merged PRs (bash, platform CLI)
    ├── Feedback: discover autodocs PRs, check state, detect corrections
    ├── Stale PR management (Python: warn/close old PRs)
    ├── Open PR limit check
    |
    ├── Call 1: Sync (LLM)
    |   ├── Read pre-fetched PRs from fetched-prs.json
    |   ├── Get changed files via git diff-tree
    |   ├── Full diffs for mapped files, stat-only for unmapped
    |   └── Write: daily-report.md, activity-log.md
    |
    ├── match-helper.py      (Python: file → section mapping)
    ├── drift-helper.py      (Python: parse, group, dedup, lifecycle)
    ├── Log match rate metric
    |
    ├── Call 2: Drift (LLM)
    |   ├── Read drift-context.json (pre-processed)
    |   └── Write: drift-report.md, drift-status.md, drift-log.md
    |
    ├── drift-helper.py suggest-dedup  (Python: changelog + open PR filtering)
    ├── Copy mapped source files to source-context/ (bash)
    |
    ├── Call 3: Suggest (LLM)
    |   ├── Read suggest-context.json + source files (ground truth)
    |   ├── Generate FIND/REPLACE with self-verification
    |   └── Write: drift-suggestions.md, changelog-*.md
    |
    ├── drift-helper.py verify-finds    (Python: FIND text exists in doc?)
    ├── drift-helper.py verify-replaces (Python: REPLACE values in source?)
    |   └── Three-tier gating: EVIDENCED → apply, MISMATCH → block, UNVERIFIED → review
    |
    ├── Shadow verify (optional, LLM, log-only — does not gate apply)
    |
    ├── Call 4: Apply (LLM, optional — if auto_pr enabled + verified suggestions)
    |   ├── Read verification results (verified-suggestions.json, replace-verification.json)
    |   ├── Apply only CONFIDENT + FIND-verified + REPLACE-verified suggestions
    |   ├── git: create branch, commit, push
    |   └── Platform: create PR with autodocs label + metadata
    |
    ├── Write sync-status.md + metrics.jsonl
    └── Advance last-successful-run (only if relevant PRs processed)

launchd/cron/GitHub Actions (weekly, Saturday)
    |
    v
autodocs-structural-scan.sh
    |
    ├── Read reference docs, extract all file paths
    ├── git ls-files: verify each exists, find undocumented files
    ├── Suggest package_map additions
    └── Write: structural-report.md
```

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

| Property | Call 1: Sync | Call 2: Drift | Call 3: Suggest | Call 3v: Verify | Call 4: Apply |
|----------|-------------|---------------|-----------------|-----------------|---------------|
| Property | Call 1: Sync | Call 2: Drift | Call 3: Suggest | Call 4: Apply |
|----------|-------------|---------------|-----------------|---------------|
| Purpose | Fetch PR data | Detect stale sections | Generate FIND/REPLACE | Apply edits + open PR |
| Inputs | fetched-prs.json, config | drift-context.json, docs | suggest-context.json, source-context/, docs | drift-suggestions.md, verification JSONs |
| Outputs | daily-report.md | drift-report/status/log.md | drift-suggestions.md, changelog | git branch + PR |
| Runs when | Always | Call 1 succeeded | HIGH/CRITICAL alerts | auto_pr + verified suggestions |
| Deterministic pre-processing | Pre-fetch PRs, date computation | match-helper, drift-helper pre-process | suggest-dedup, source copy | verify-finds, verify-replaces |

Key properties:
- Each call can fail without corrupting the others
- Deterministic Python runs between every call — the LLM never sees unverified data
- Call 3 reads actual source files (source-context/) as ground truth
- Call 4 only applies suggestions that pass both FIND and REPLACE verification
- Shadow verify (Call 3v) runs optionally in a subshell — logs only, never gates apply

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
