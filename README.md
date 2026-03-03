# autodocs

Automated documentation drift detection using Claude Code + Azure DevOps.

When your team merges PRs that change code described in your documentation, autodocs detects which doc sections may be stale and generates structured alerts — so you review docs that matter, not everything.

## How it works

```
Your repo (git)          Azure DevOps              Kusto (optional)
     |                       |                          |
     |   git diff-tree       |   merged PRs             |   telemetry
     |   (changed files)     |   (team activity)        |   (error patterns)
     v                       v                          v
  +---------------------------------------------------------+
  |              Claude Code (headless mode)                 |
  |                                                         |
  |  Call 1: Sync                                           |
  |  - Fetch merged PRs from ADO                            |
  |  - Get changed files via git diff-tree (local repo)     |
  |  - Classify PRs by path matching                        |
  |  - Run predefined Kusto queries (if configured)         |
  |  - Write: daily-report.md, activity-log.md              |
  |                                                         |
  |  Call 2: Drift Detection                                |
  |  - Read sync output + your doc's file index             |
  |  - Map changed packages to doc sections                 |
  |  - Flag new error patterns not in known list            |
  |  - Detect unmapped files (new code not in docs)         |
  |  - Write: drift-report.md, drift-status.md, drift-log  |
  +---------------------------------------------------------+
                          |
                          v
                    Output files
              (markdown, YAML frontmatter)
```

## Key innovation: `git diff-tree`

The ADO MCP doesn't expose changed files for a PR. autodocs works around this by extracting the merge commit SHA from the PR response, then running `git diff-tree` against the local repo to get the exact file list. This enables precise, file-level drift detection that maps changed code to specific documentation sections.

## What it produces

**daily-report.md** — Structured daily summary with YAML frontmatter:
- Team PRs (classified by feature relevance, with full file lists)
- Owner's activity (reviews, authored PRs)
- Telemetry metrics (reliability, error breakdown, anomalies)

**drift-report.md** — Documentation drift alerts:
- Which doc sections may be stale, triggered by which PRs
- Confidence levels (CRITICAL / HIGH / LOW)
- New error patterns not in your known patterns list

**drift-status.md** — Active alert tracker (Obsidian-compatible checkboxes):
- Check off alerts you've resolved
- LOW alerts auto-expire after 7 days
- Deduplicates across days

**drift-log.md** — Append-only history (30-day retention)

## Quick start

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- [Azure DevOps MCP](https://github.com/nicepkg/azure-devops-mcp) configured in your project's `.claude/settings.json`
- Git repo checked out locally
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
4. Render the prompts and wrapper script

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
# Manual run
autodocs-now

# Or run the sync directly
./autodocs-sync.sh
```

### Schedule

autodocs generates a launchd plist (macOS) for daily automated runs:

```bash
launchctl load ~/Library/LaunchAgents/com.autodocs.sync.plist
```

## Configuration reference

See [docs/configuration.md](docs/configuration.md) for the complete config file reference.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the data flow, security model, and design decisions.

## Example: Channel Pages (Loop in Teams)

The [examples/channel-pages/](examples/channel-pages/) directory contains a complete worked example:
- Config for a 9-person team working on Microsoft Teams Channel Pages
- 3 predefined Kusto queries for feature reliability monitoring
- Package-to-section mappings for a 19-section architecture doc
- Sample output files showing real drift alerts

## How drift detection works

1. The daily sync writes `daily-report.md` with PR data including changed file paths
2. The drift prompt reads the PR file lists and your doc's structure
3. For each changed file, it extracts the package and looks up your `package_map`
4. If the package maps to a doc section → **HIGH** confidence alert
5. If the package is in your feature's paths but NOT in the mapping → **CRITICAL** alert (docs may be missing coverage)
6. If file paths aren't available → **LOW** alert (manual review needed)
7. New telemetry error patterns not in your known list → **HIGH** alert

Alerts are grouped by section (not per-file), deduplicated across days, and auto-expire if unresolved.

## Design principles

- **Detect, never edit.** autodocs flags stale sections — it never modifies your documentation.
- **Deterministic classification.** PR relevance is determined by file path matching, not LLM inference.
- **Graceful degradation.** If ADO fails, telemetry still runs (and vice versa). If file paths aren't available, LOW alerts are generated instead of silence.
- **Two-call isolation.** The sync and drift prompts run independently. Drift failure can't corrupt sync output.
- **Config-driven.** Team members, paths, queries, and mappings live in config. Prompts are generic.

## Security

- **Read-only ADO access.** Only 4 ADO MCP tools are allowed (list PRs, get PR details, search code, get repo). No write operations.
- **No PII in output.** Prompts explicitly prohibit including internal URLs, stack traces, or user identifiers.
- **Kusto queries are predefined.** The LLM copies queries verbatim from config — it never generates KQL.
- **Write sandbox.** Each prompt can only write to its specific output files.
- **Git operations scoped.** Only `git diff-tree` and `git fetch` are used — no modifications to the repo.

## License

MIT
