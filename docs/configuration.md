# Configuration Reference

autodocs uses a single `config.yaml` file for all runtime settings. Prompts read this file at the start of each sync.

**Changes to config take effect immediately** — no need to re-run `setup.sh`. Only re-run setup if you change the output directory or repo path (these are baked into the rendered prompts).

## Full Schema

### `platform` (required)

The git hosting platform. Determines how PRs are fetched and auto-PRs are created.

```yaml
platform: github  # or: gitlab, bitbucket, ado
```

### Platform connection (one required, matching `platform`)

**GitHub:**
```yaml
github:
  owner: "your-username"     # GitHub user or organization
  repo: "your-repo"          # Repository name
```

**GitLab:**
```yaml
gitlab:
  host: "gitlab.com"         # or self-hosted: "gitlab.mycompany.com"
  project_path: "group/repo" # full project path
```

**Bitbucket:**
```yaml
bitbucket:
  workspace: "my-workspace"
  repo: "my-repo"
# Auth: set BITBUCKET_TOKEN environment variable
```

**Azure DevOps:**
```yaml
ado:
  org: "your-org"
  project: "your-project"
  repo: "your-repo"
  repo_id: "guid-here"      # Repository GUID (setup.sh resolves this)
```

### `owner` (required)

The feature owner. Their activity gets a dedicated section in daily reports.

```yaml
owner:
  name: "Your Name"
  email: "you@company.com"
  ado_id: "guid-here"       # Your ADO user GUID
```

**Finding your ADO ID:** In ADO, go to your profile → the GUID is in the URL. Or use the `core_get_identity_ids` MCP tool.

### `team_members` (required)

Team members whose PRs are tracked. The owner is implicitly included.

```yaml
team_members:
  - name: "Alice"
    email: "alice@company.com"
    ado_id: "guid-here"
  - name: "Bob"
    ado_id: "guid-here"     # email is optional
```

### `relevant_paths` (required)

File path prefixes that indicate a PR is relevant to your feature. Used for deterministic classification.

```yaml
relevant_paths:
  - packages/your-feature/
  - packages/components/your-hooks/
  - config/your-feature/
```

A PR is classified as **YES** if any of its changed files start with any of these prefixes.

### `relevant_pattern` (optional)

Catch-all substring for files not covered by `relevant_paths`. Matched as a case-insensitive substring against each file path (not glob matching).

```yaml
relevant_pattern: "your-feature"
```

A PR is classified as **MAYBE** if no file matches `relevant_paths` but a file path contains this substring. Useful for catching new packages not yet in the paths list.

### `telemetry` (optional)

Kusto telemetry configuration. Remove this section entirely to disable telemetry monitoring.

```yaml
telemetry:
  enabled: true
  cluster: "your-cluster.region.kusto.windows.net"
  database: "your-database-id"
  queries:
    - name: "Query display name"
      description: "What this query measures"
      query: |
        YourTable
        | where Timestamp > ago(24h)
        | summarize count() by Category
```

**Query rules:**
- Queries are copied EXACTLY by the LLM — it never modifies or generates KQL
- Each query should be self-contained (no parameters or variables)
- Use `ago(24h)` for daily windows
- Avoid returning PII (user IDs, email addresses)
- Keep result sets small (use `summarize`, `top`, or `take`)

### `docs` (optional)

Reference docs for drift detection. Remove this section to disable drift detection (only the sync will run).

Each doc entry can have:

#### `name` (required)

Filename of the doc. Must exist in the output directory.

```yaml
docs:
  - name: "your-guide.md"
```

#### `repo_path` (optional, required for auto-PR)

Path to the doc file within the git repo. Used by Call 4 (apply) to locate the file for editing.

```yaml
    repo_path: "docs/your-feature/your-guide.md"
```

#### `package_map` (optional)

Maps package names to doc section names. Used for PR drift detection.

**Simple mapping** — package maps to one section:

```yaml
    package_map:
      your-feature: "Architecture"
      your-hooks: "Hooks Reference"
```

**Complex mapping** — package spans multiple sections, PR title narrows it down:

```yaml
    package_map:
      your-shared-package:
        default: "Shared Package (multiple sections)"
        title_hints:
          "error,fault,exception": "Error Handling"
          "auth,token": "Authentication"
```

The `title_hints` keys are comma-separated keywords. If the PR title contains any keyword from a key, the corresponding section is used. If no hint matches, `default` is used.

#### `known_patterns_section` (optional)

Section title in the doc that lists known error/failure patterns. Used for telemetry drift detection.

```yaml
  - name: "telemetry-guide.md"
    known_patterns_section: "Known Failure Patterns"
```

When the sync detects a NEW error pattern (not in this section), a HIGH confidence drift alert is generated.

#### `ignore_packages` (optional)

Packages to skip in unmapped file detection. Shared packages that appear in many PRs but aren't feature-specific.

```yaml
    ignore_packages:
      - i18n-resources
      - test-utilities
```

### `auto_pr` (optional)

Enables Call 4: automatically apply CONFIDENT + VERIFIED suggestions to doc files in the repo and open an ADO pull request. Disabled by default.

```yaml
auto_pr:
  enabled: true
  target_branch: "master"           # PR target branch
  branch_prefix: "autodocs/"        # Branch name: <prefix><YYYY-MM-DD>
  work_item_ids: "12345"            # ADO work item ID(s) to link to each PR
```

Requires `repo_path` on each doc entry (see docs section above) so the apply prompt knows where to find the files in the repo.

### `multi_model` (optional)

Enables multi-model verification for suggestions. When enabled, the suggest prompt runs a second time with a chain-of-thought reasoning variation (same model, different reasoning path). Only suggestions where both runs agree are applied via auto-PR. Disputed suggestions stay in drift-suggestions.md for manual review.

```yaml
multi_model:
  enabled: true
```

Based on [ACL 2025 research](https://aclanthology.org/2025.findings-acl.606.pdf) showing simple majority voting captures most gains from multi-agent debate, and [Anthropic's Best-of-N verification recommendation](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations).

### `last_verified` (optional)

Date when the config was last reviewed for accuracy. Informational only.

```yaml
last_verified: "2026-03-01"
```

## Output Files

autodocs generates these files in the output directory:

| File | Written by | Frequency | Description |
|------|-----------|-----------|-------------|
| `daily-report.md` | Sync | Overwritten daily | PR summary (with descriptions, files, threads), telemetry, anomalies |
| `activity-log.md` | Sync | Appended daily | Owner's activity history (14-day retention) |
| `drift-report.md` | Drift | Overwritten daily | Today's drift alerts + active unresolved |
| `drift-status.md` | Drift | Rewritten daily | Checkbox list (Obsidian-compatible) |
| `drift-log.md` | Drift | Appended daily | Drift alert history (30-day retention) |
| `drift-suggestions.md` | Suggest | Overwritten daily | FIND/REPLACE edit suggestions, self-verified (only when HIGH/CRITICAL drift) |
| `changelog-<doc>.md` | Suggest | Appended daily | Per-doc change history organized by section (permanent, never trimmed) |
| `structural-report.md` | Scan | Overwritten weekly | Missing files + undocumented files audit |
| `drift-suggestions-verify.md` | Verify | Overwritten daily | Independent verification suggestions (only when multi_model enabled) |
| `sync-status.md` | Wrapper | Overwritten daily | status + drift + suggest + verify + apply + timestamp |
| ADO pull request | Apply | When CONFIDENT+VERIFIED suggestions exist | Branch with doc edits + changelog, linked to work items |
| `sync.log` | Wrapper | Appended | One-line log per run |

## Minimal Config (sync only, no telemetry, no drift)

```yaml
ado:
  org: "my-org"
  project: "my-project"
  repo: "my-repo"
  repo_id: "00000000-..."

owner:
  name: "My Name"
  email: "me@company.com"
  ado_id: "00000000-..."

team_members:
  - name: "Teammate"
    ado_id: "00000000-..."

relevant_paths:
  - src/my-feature/

relevant_pattern: "my-feature"
```

This produces `daily-report.md` and `activity-log.md` only. No telemetry, no drift detection.
