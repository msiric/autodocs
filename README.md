# autodocs

Automated documentation drift detection using LLM-powered analysis + deterministic verification.

When your team merges PRs that change code described in your documentation, autodocs detects which doc sections are stale, generates suggested updates, and maintains a changelog of why things changed.

Supports GitHub, GitLab, Bitbucket, and Azure DevOps. Runs via Claude Code CLI or Anthropic API.

## How it works

```
Your repo (git)         GitHub / ADO / GitLab / Bitbucket    LLM (Claude)
     |                       |                                    |
     |   git diff-tree       |   merged PRs (+ descriptions,      |   drift detection
     |   (change types,      |      review threads, diffs)        |   + suggestions
     |    A/M/D/R + diffs)   |                                    |
     v                       v                                    v
  +---------------------------------------------------------+
  |                    autodocs pipeline                    |
  |                                                         |
  |  Step 1: Sync (deterministic Python)                    |
  |  - Discover relevant PRs via git log + path filter      |
  |  - Fetch PR details from platform API (relevant only)   |
  |  - Get changed files via git diff-tree (local repo)     |
  |  - Fetch PR review threads for relevant PRs             |
  |  - Write: daily-report.md, activity-log.md              |
  |                                                         |
  |  Step 2: Drift Detection (LLM)                          |
  |  - Read sync output + your doc's file index             |
  |  - Map changed packages to doc sections                 |
  |  - Flag new error patterns not in known list            |
  |  - Detect unmapped files (new code not in docs)         |
  |  - Write: drift-report.md, drift-status.md, drift-log   |
  |                                                         |
  |  Step 3: Suggest + Changelog (LLM, if drift found)      |
  |  - Read flagged sections from your actual docs          |
  |  - Generate FIND/REPLACE edit suggestions (verified)    |
  |  - Write changelog entries capturing WHY things changed |
  |  - Write: drift-suggestions.md, changelog-<doc>.md      |
  |                                                         |
  |  Step 3v: Verify (optional, multi-model verification)   |
  |  - Re-run suggest with variant reasoning path           |
  |  - Write: drift-suggestions-verify.md                   |
  |                                                         |
  |  Step 4: Apply as PR (deterministic Python)             |
  |  - Apply FIND/REPLACE to doc files (verified only)      |
  |  - Create branch, commit changes + changelog            |
  |  - Open pull request via platform CLI                   |
  |                                                         |
  |  Weekly: Structural Scan (Saturday)                     |
  |  - Verify every file referenced in docs still exists    |
  |  - Find undocumented files in feature paths             |
  |  - Write: structural-report.md                          |
  +---------------------------------------------------------+
```

The LLM is only used for steps 2 and 3 (drift detection and suggestion generation) — tasks that genuinely need natural language understanding. Everything else is deterministic Python: PR fetching, classification, verification, edit application, git operations, and PR creation.

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

- Git repo checked out locally
- Python 3.9+
- LLM backend (one of):

| Backend | Tool | Setup |
| ------- | ---- | ----- |
| Claude Code CLI (default) | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Install and run `claude` to authenticate |
| Anthropic API | `pip install anthropic` | Set `ANTHROPIC_API_KEY` environment variable |

- Platform CLI:

| Platform     | Tool                                                     | Setup                                      |
| ------------ | -------------------------------------------------------- | ------------------------------------------ |
| GitHub       | [`gh`](https://cli.github.com/)                          | Install and run `gh auth login`            |
| GitLab       | [`glab`](https://docs.gitlab.com/cli/)                   | Install and run `glab auth login`          |
| Bitbucket    | `curl`                                                   | Set `BITBUCKET_TOKEN` environment variable |
| Azure DevOps | [`az`](https://learn.microsoft.com/cli/azure/)           | Install and run `az login`                 |

- (Optional) [Kusto MCP](https://github.com/nicepkg/kusto-mcp) for telemetry monitoring (requires Claude Code CLI backend)

### Setup

**Starting from scratch (no existing docs):**

```bash
git clone https://github.com/msiric/autodocs.git
cd autodocs
./setup.sh generate /path/to/your-repo /path/to/output-dir --relevant-dirs src/
```

This generates an architecture doc from your codebase and a matching `config.yaml`. Review the generated doc, commit it to your repo, then proceed to the wizard:

**Interactive wizard (or if you already have docs):**

```bash
./setup.sh                  # interactive setup
./setup.sh --quick          # auto-detect everything
```

The setup wizard will:

1. Detect your platform, repo details, and team members
2. Select or generate a doc to track
3. Generate a config with package_map
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

# LLM backend (optional — defaults to Claude Code CLI)
# llm:
#   backend: "api"   # Use Anthropic API instead of Claude Code CLI
```

### Run

```bash
# Manual run (full daily chain: sync → drift → suggest → apply PR)
autodocs-now

# Catchup: process historical PRs for brownfield projects
# Walks through weekly chunks, builds changelog, then creates one fix PR
autodocs-sync.sh --since 2025-09-01

# Dry-run catchup (shows chunk count and estimated time, no LLM calls)
autodocs-sync.sh --since 2025-09-01 --dry-run

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

### Webhook (real-time mode)

Instead of scheduled runs, autodocs can process PRs immediately on merge via webhooks:

```bash
# Start the webhook server
pip install fastapi uvicorn
AUTODOCS_WEBHOOK_SECRET=your-secret OUTPUT_DIR=.autodocs REPO_DIR=. \
  uvicorn scripts.webhook_server:app --port 8080
```

Then configure your platform to send PR merge webhooks to `http://your-host:8080/webhook/github` (or `/gitlab`, `/bitbucket`).

## Configuration reference

See [docs/configuration.md](docs/configuration.md) for the complete config file reference.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the data flow, security model, and design decisions.

## Demo

See [autodocs-demo](https://github.com/msiric/autodocs-demo) for a live example — a Node.js API repo with an architecture doc tracked by autodocs. The [latest autodocs PR](https://github.com/msiric/autodocs-demo/pulls?q=is%3Apr+label%3Aautodocs) shows real pipeline output: auto-applied suggestions, verification data, and changelog entries.

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

### Suggested updates + verification + auto-PR

When drift is detected, autodocs reads the flagged doc section, the PR diffs, and the **current source files** (ground truth), then generates suggestions that go through a multi-layer verification pipeline:

1. **LLM generates FIND/REPLACE** — with self-verification (FIND text confirmed verbatim in doc)
2. **Deterministic FIND verification** (Python) — mechanically confirms every FIND block exists in the target doc file
3. **Deterministic REPLACE verification** (Python) — extracts code references from REPLACE text (backtick identifiers, quoted literals, file paths, error codes) and verifies them against source code:
   - **EVIDENCED** — value found in source → eligible for auto-apply
   - **MISMATCH** — value contradicts source → blocked (prevents wrong edits)
   - **UNVERIFIED** — value can't be checked (behavioral claim) → flagged for human review
4. **Auto-PR** — only CONFIDENT + FIND-verified + REPLACE-verified suggestions are applied. Everything else goes in the PR description for manual review.

Each suggestion also includes:

- **Confidence rating** — CONFIDENT for clear factual changes, REVIEW for ambiguous ones
- **Changelog entry** — what changed, why (from PR description), and reviewer context
- **Source file context** — the LLM reads actual source files, not just diffs, preventing stale changelog entries from poisoning suggestions

If `auto_pr` is enabled in config, autodocs automatically:

1. Applies verified suggestions to doc files in the repo
2. Includes the changelog alongside the edits
3. Creates a branch and opens a PR with the `autodocs` label
4. The human reviews and merges — standard code review workflow

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
- **Three-layer verification.** (1) FIND text confirmed verbatim in doc by Python. (2) REPLACE text values verified against source code by Python — mismatched values are blocked. (3) Source files included in LLM context as ground truth. Unverified or mismatched suggestions are flagged for human review, never auto-applied.
- **Prompt injection mitigation.** PR descriptions and review comments are marked as untrusted user data in all prompts.
- **Human reviews all changes.** Auto-PRs go through standard code review workflow. Branch protection rules apply.

## Best practices for optimal results

- **Keep PRs focused.** autodocs produces the most precise suggestions for PRs with <30 changed files. Large feature PRs (50+ files) still trigger drift detection for all affected sections, but suggestions may be less precise for files beyond the diff budget (150 lines per PR).
- **Use meaningful PR titles and descriptions.** autodocs uses PR titles for `title_hints` matching and descriptions for the "why" in changelogs. Vague titles like "fix stuff" degrade suggestion quality.
- **Structure your docs with section headers.** `## Section Name` headers enable per-section drift detection. Flat prose without headers gets treated as one block — suggestions are less targeted.
- **Keep your package_map current.** When you add new packages to the repo, add them to the config. The structural scan (weekly) flags undocumented files, but the mapping determines suggestion quality.

## Multi-repo / Microservices

For teams with multiple repositories, run a separate autodocs instance for each repo. Each instance monitors its own docs and PRs independently.

Cross-repo drift (API change in repo A making docs in repo B stale) is not detected automatically. For critical cross-repo dependencies, consider:

- Shared documentation in a dedicated docs repo with its own autodocs instance
- Manual review triggers when API contracts change
- Using the weekly structural scan to verify cross-referenced file paths

## Known limitations

- **Large PRs (50+ files):** Drift detection covers all files, but the diff budget (150 lines per PR) means only the most relevant files get detailed diffs. Suggestions for undiffed files are REVIEW confidence (not CONFIDENT). The daily report notes "Diff truncated" when this happens.
- **Cross-repo drift:** Changes in one repo that affect docs in another repo are not detected. See "Multi-repo" section above.
- **Non-markdown docs:** Only `.md` files are supported. RST, HTML, AsciiDoc, and wiki-based docs are not handled.
- **Flat prose without headers:** Docs without `##` section headers are treated as a single "Main" section. Suggestions are less targeted. Consider adding headers for better drift detection.

## License

MIT
