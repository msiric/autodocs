# autodocs

Automated documentation drift detection using Claude Code + Azure DevOps.

When your team merges PRs that change code described in your documentation, autodocs detects which doc sections are stale, generates suggested updates, and maintains a changelog of why things changed.

## How it works

```
Your repo (git)         GitHub / ADO / GitLab / Bitbucket    Kusto (optional)
     |                       |                                    |
     |   git diff-tree       |   merged PRs (+ descriptions,     |   telemetry
     |   (change types,      |      review threads, diffs)       |   (error patterns)
     |    A/M/D/R + diffs)   |                                    |
     v                       v                                    v
  +---------------------------------------------------------+
  |              Claude Code (headless mode)                |
  |                                                         |
  |  Call 1: Sync (daily)                                   |
  |  - Fetch merged PRs from ADO (with descriptions)        |
  |  - Get changed files via git diff-tree (local repo)     |
  |  - Fetch PR review threads for relevant PRs             |
  |  - Classify PRs by path matching                        |
  |  - Run predefined Kusto queries (if configured)         |
  |  - Write: daily-report.md, activity-log.md              |
  |                                                         |
  |  Call 2: Drift Detection (daily)                        |
  |  - Read sync output + your doc's file index             |
  |  - Map changed packages to doc sections                 |
  |  - Flag new error patterns not in known list            |
  |  - Detect unmapped files (new code not in docs)         |
  |  - Write: drift-report.md, drift-status.md, drift-log   |
  |                                                         |
  |  Call 3: Suggest + Changelog (daily, if drift found)    |
  |  - Read flagged sections from your actual docs          |
  |  - Generate FIND/REPLACE edit suggestions (verified)    |
  |  - Write changelog entries capturing WHY things changed |
  |  - Write: drift-suggestions.md, changelog-<doc>.md      |
  |                                                         |
  |  Call 3v: Verify (optional, multi-model verification)   |
  |  - Re-run suggest with variant reasoning path           |
  |  - Write: drift-suggestions-verify.md                   |
  |                                                         |
  |  Call 4: Apply as PR (optional, if suggestions agreed)  |
  |  - Compare primary + verify suggestions                 |
  |  - Apply only AGREED suggestions to doc files           |
  |  - Create branch, commit changes + changelog            |
  |  - Open pull request in ADO (with work item link)       |
  |                                                         |
  |  Weekly: Structural Scan (Saturday)                     |
  |  - Verify every file referenced in docs still exists    |
  |  - Find undocumented files in feature paths             |
  |  - Write: structural-report.md                          |
  +---------------------------------------------------------+
```

## Key innovations

**`git diff-tree` for file-level precision.** The ADO MCP doesn't expose changed files for a PR. autodocs extracts the merge commit SHA from the PR response, then runs `git diff-tree` against the local repo. This enables precise, package-to-section drift detection.

**FIND/REPLACE with self-verification.** Suggestions use a structured FIND/REPLACE format where each FIND block is verified against the actual doc (with line numbers). Optionally, autodocs can apply verified suggestions automatically by opening a PR in ADO — the human reviews and merges through the standard code review workflow.

**Changelog with "why."** Most documentation tells you WHAT the system does today. autodocs also captures WHY things changed — from PR descriptions and review threads. Six months later, when nobody remembers why `handleError` became `classifyError`, the changelog does.

## What it produces

### Daily output

**daily-report.md** — Structured daily summary with YAML frontmatter:
- Team PRs with descriptions, file lists, and review thread summaries
- Owner's activity (reviews, authored PRs)
- Telemetry metrics (reliability, error breakdown, anomalies)

**drift-report.md** — Documentation drift alerts:
- Which doc sections may be stale, triggered by which PRs
- Confidence levels (CRITICAL / HIGH / LOW)
- New error patterns not in your known patterns list

**drift-suggestions.md** — FIND/REPLACE edit suggestions:
- Structured FIND/REPLACE or FIND/INSERT AFTER format
- Each FIND block self-verified against the doc (with line numbers)
- Rated CONFIDENT (clear factual change) or REVIEW (needs human judgment)
- Frontmatter includes `verified: X/Y` count

**changelog-\<doc\>.md** — Per-doc change history, organized by section:
- What changed, why it changed (from PR descriptions)
- Reviewer context (from PR review threads)
- Permanent record — never trimmed
- Committed to the repo alongside doc edits (via auto-PR)

**drift-status.md** — Active alert tracker (Obsidian-compatible checkboxes):
- Check off alerts you've resolved
- LOW alerts auto-expire after 7 days
- Deduplicates across days

### Weekly output

**structural-report.md** — Documentation structural audit:
- Files referenced in docs that no longer exist in the repo
- Files in feature paths that aren't documented
- Catches drift that predates autodocs

## Quick start

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Git repo checked out locally
- Platform CLI:

| Platform | Tool | Setup |
|----------|------|-------|
| GitHub | [`gh`](https://cli.github.com/) | Install and run `gh auth login` |
| GitLab | [`glab`](https://docs.gitlab.com/cli/) | Install and run `glab auth login` |
| Bitbucket | `curl` | Set `BITBUCKET_TOKEN` environment variable |
| Azure DevOps | [ADO MCP](https://github.com/microsoft/azure-devops-mcp) | Configure in `.claude/settings.json` |

- (Optional) [Kusto MCP](https://github.com/nicepkg/kusto-mcp) for telemetry monitoring

### Setup

```bash
git clone https://github.com/msiric/autodocs.git
cd autodocs
./setup.sh
```

The setup wizard will:
1. Ask for your repo path, output directory, ADO details
2. Resolve your repository GUID
3. Generate a config template for you to customize
4. Render all prompts, wrapper scripts, and schedules

### Configure

Edit the generated `config.yaml` in your output directory:

```yaml
# Add your team members
team_members:
  - name: "Alice Engineer"
    ado_id: "abc123-..."

# Add paths that indicate relevance to your feature
relevant_paths:
  - packages/components/your-feature/
  - packages/hooks/your-feature-hooks/

# Add package-to-section mappings for your docs
docs:
  - name: "your-feature-guide.md"
    package_map:
      your-feature: "Architecture"
      your-feature-hooks: "Hooks Reference"
```

### Run

```bash
# Manual run (full daily chain: sync → drift → suggest → apply PR)
autodocs-now

# Structural scan (usually weekly, can run manually)
autodocs-structural-scan.sh
```

### Schedule

```bash
# Daily sync + drift + suggest + apply (macOS)
launchctl load ~/Library/LaunchAgents/com.autodocs.sync.plist

# Weekly structural scan (macOS)
launchctl load ~/Library/LaunchAgents/com.autodocs.structural-scan.plist
```

## Configuration reference

See [docs/configuration.md](docs/configuration.md) for the complete config file reference.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the data flow, security model, and design decisions.

## Example: Channel Pages (Loop in Teams)

The [examples/channel-pages/](examples/channel-pages/) directory contains a complete worked example from a 9-person team at Microsoft working on Teams Channel Pages:
- Config with team members, 11 relevant path prefixes, 3 Kusto queries
- Package-to-section mappings for a 19-section architecture doc
- Sample output: daily report, drift alerts, suggested updates, changelog

## How it works in detail

### Drift detection

1. The daily sync writes `daily-report.md` with PR data including changed file paths
2. The drift prompt reads the PR file lists and your doc's structure
3. For each changed file, it extracts the package and looks up your `package_map`
4. If the package maps to a doc section → **HIGH** confidence alert
5. If the package is in your feature's paths but NOT in the mapping → **CRITICAL** alert (docs may be missing coverage)
6. If file paths aren't available → **LOW** alert (manual review needed)
7. New telemetry error patterns not in your known list → **HIGH** alert

Alerts are grouped by section (not per-file), deduplicated across days, and auto-expire if unresolved.

### Suggested updates + auto-PR

When drift is detected, autodocs reads the flagged doc section and the PR changes, then generates:
- **FIND/REPLACE diffs** — exact text from the doc (verified with line numbers) and the replacement
- **INSERT AFTER operations** — for adding new content (table rows, paragraphs)
- **Self-verification** — each FIND block is confirmed to exist verbatim in the doc
- **Confidence rating** — CONFIDENT for clear factual changes, REVIEW for ambiguous ones
- **Changelog entry** — what changed, why (from PR description), and reviewer context (from PR threads)

If `multi_model` is enabled, autodocs runs the suggest prompt a second time with a variant reasoning path (chain-of-thought variation). Only suggestions where both runs agree on the factual claims are applied via auto-PR. Disputed suggestions stay in drift-suggestions.md for manual review.

If `auto_pr` is enabled in config, autodocs automatically:
1. Compares primary and verify suggestions (if multi-model enabled)
2. Applies AGREED (or all CONFIDENT+VERIFIED if single-model) suggestions to doc files
3. Includes the changelog alongside the edits
4. Creates a branch and opens a PR in ADO (with work item linking)
5. The human reviews and merges — standard code review workflow

### Structural scan

Once a week, autodocs audits your docs against the actual repo:
- Every file path mentioned in a doc → verified via `git ls-files`
- Every file under feature-relevant paths → checked if documented
- Missing files (deleted/renamed) and undocumented files are reported

## Design principles

- **Suggest, never force.** autodocs generates verified FIND/REPLACE suggestions and optionally opens PRs — but a human always reviews before changes reach the main branch.
- **Deterministic classification.** PR relevance is determined by file path matching, not LLM inference.
- **Graceful degradation.** If ADO fails, telemetry still runs (and vice versa). If file paths aren't available, LOW alerts are generated instead of silence.
- **Independent call isolation.** Sync, drift, suggest, verify, and apply run as independent Claude Code calls. Each can fail without corrupting the others.
- **Config-driven.** Team members, paths, queries, and mappings live in config. Prompts are generic templates.

## Security

- **Minimal ADO access.** Calls 1-3 use 5 read-only ADO tools. Call 4 adds `repo_create_pull_request` and `repo_create_branch` — the only write operations, and only to create PRs on feature branches (never direct writes to the target branch).
- **No PII in output.** Prompts explicitly prohibit including internal URLs, stack traces, or user identifiers.
- **Kusto queries are predefined.** The LLM copies queries verbatim from config — it never generates KQL.
- **Write sandbox.** Each prompt can only write to its specific output files. The apply prompt can additionally write to doc files in the repo (gated by `auto_pr` config).
- **Git operations scoped.** Read operations: `git diff-tree`, `git ls-files`, `git fetch`. Write operations (Call 4 only): `git checkout -b`, `git add`, `git commit`, `git push` — always to a feature branch, never to the target branch.
- **Self-verified suggestions.** Each FIND block is confirmed to exist verbatim in the doc before being applied. Unverified suggestions are skipped.
- **Multi-model verification.** When enabled, suggestions are independently generated through two different reasoning paths. Only suggestions where both agree are auto-applied. Disputed suggestions require manual review.
- **Human reviews all changes.** Auto-PRs go through standard ADO review workflow. Branch protection rules apply.

## License

MIT
