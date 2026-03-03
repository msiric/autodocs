# Configuration Reference

autodocs uses a single `config.yaml` file for all runtime settings. Prompts read this file at the start of each sync.

**Changes to config take effect immediately** — no need to re-run `setup.sh`. Only re-run setup if you change the output directory or repo path (these are baked into the rendered prompts).

## Full Schema

### `ado` (required)

Azure DevOps connection details.

```yaml
ado:
  org: "your-org"           # Organization name
  project: "your-project"   # Project name
  repo: "your-repo"         # Repository name (for display only)
  repo_id: "guid-here"      # Repository GUID (setup.sh resolves this)
```

**Finding the repo GUID:** Run `setup.sh` (resolves automatically), or find it in ADO → Project Settings → Repositories → click repo → GUID is in the URL.

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

Catch-all substring pattern for files not covered by `relevant_paths`.

```yaml
relevant_pattern: "*your-feature*"
```

A PR is classified as **MAYBE** if no file matches `relevant_paths` but a file path contains this substring (case-insensitive). Useful for catching new packages not yet in the paths list.

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

### `last_verified` (optional)

Date when the config was last reviewed for accuracy. Informational only.

```yaml
last_verified: "2026-03-01"
```

## Output Files

autodocs generates these files in the output directory:

| File | Written by | Frequency | Description |
|------|-----------|-----------|-------------|
| `daily-report.md` | Sync | Overwritten daily | PR summary, telemetry, anomalies |
| `activity-log.md` | Sync | Appended daily | Owner's activity history (14-day retention) |
| `drift-report.md` | Drift | Overwritten daily | Today's drift alerts + active unresolved |
| `drift-status.md` | Drift | Rewritten daily | Checkbox list (Obsidian-compatible) |
| `drift-log.md` | Drift | Appended daily | Drift alert history (30-day retention) |
| `sync-status.md` | Wrapper | Overwritten daily | success/failed + timestamp |
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

relevant_pattern: "*my-feature*"
```

This produces `daily-report.md` and `activity-log.md` only. No telemetry, no drift detection.
