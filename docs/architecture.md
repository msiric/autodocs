# Architecture

## Overview

autodocs runs as two sequential Claude Code headless calls, triggered daily by launchd (macOS) or cron (Linux). Each call is independent — if drift detection fails, the sync output is preserved.

```
launchd/cron (daily)
    |
    v
autodocs-sync.sh
    |
    ├── git fetch origin (ensure merge commits are available)
    |
    ├── Auth check (claude -p "Reply OK")
    |   └── Fails? → Write sync-status.md "failed", exit
    |
    ├── Call 1: Sync Prompt
    |   ├── Read config.yaml
    |   ├── ADO MCP: list completed PRs
    |   ├── ADO MCP: get PR details (merge commit SHA)
    |   ├── git diff-tree: get changed files per PR
    |   ├── Classify PRs by path matching
    |   ├── Extract owner's activity
    |   ├── Kusto MCP: run predefined queries (if configured)
    |   ├── Compare errors against known patterns (if configured)
    |   └── Write: daily-report.md, activity-log.md
    |
    ├── Call 2: Drift Prompt (only if Call 1 succeeded)
    |   ├── Read daily-report.md (Call 1 output)
    |   ├── Read config.yaml (package_map, docs)
    |   ├── Read reference docs (Table of Contents, structure)
    |   ├── Read drift-status.md (active alerts)
    |   ├── Map changed packages → doc sections
    |   ├── Detect unmapped packages (CRITICAL)
    |   ├── Detect new telemetry patterns (HIGH)
    |   ├── Deduplicate against existing alerts
    |   ├── Auto-expire stale LOW alerts
    |   └── Write: drift-report.md, drift-status.md, drift-log.md
    |
    └── Write sync-status.md ("success" or "failed")
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
                           --name-only -r be0c278...
                                      |
                                      v
                         packages/components/fluid/src/error/map.ts
                         packages/components/fluid/src/loader.ts
                         packages/data/resolvers/worker.ts
                         ...
```

This requires:
- The repo is cloned locally (it is — that's where Claude Code runs)
- A `git fetch origin` before the sync (ensures merge commits from teammates are available)
- `Bash(git:*)` in the allowed tools list (scoped to git commands only)

The approach works for all merge strategies (squash, merge commit, rebase) because `lastMergeCommit` always points to the final commit on the target branch.

## Two-Call Isolation

The sync and drift prompts run as separate Claude Code invocations:

| Property | Call 1: Sync | Call 2: Drift |
|----------|-------------|---------------|
| Purpose | Fetch data from ADO/Kusto | Analyze sync output for drift |
| Inputs | config.yaml, ADO, Kusto, git | daily-report.md, config.yaml, docs |
| Outputs | daily-report.md, activity-log.md | drift-report.md, drift-status.md, drift-log.md |
| Allowed tools | 4 ADO MCP + Kusto MCP + Bash(git) + Write | Read + Write |
| Failure impact | sync-status.md = "failed" | Logged, sync output preserved |
| Can break the other? | No | No |

This means:
- Iterating on drift detection doesn't risk breaking the sync
- Each prompt can be debugged independently
- Token budgets are independent (~30K sync, ~10K drift)

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

Only 4 ADO tools are in the allowlist:
- `repo_list_pull_requests_by_repo_or_project` — list merged PRs
- `repo_get_pull_request_by_id` — get PR details/merge commit
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

### Git scope

Only two git operations are used:
- `git fetch origin` — update remote refs (read-only)
- `git diff-tree` — list changed files for a commit (read-only)

No modifications to the working tree, index, or branches.

### Data sanitization

Prompts explicitly prohibit including:
- Internal URLs
- Stack traces
- User identifiers (aggregated counts only)
- PII of any kind
