# Platform Migration Guide

How to switch autodocs between GitHub, GitLab, Bitbucket, and Azure DevOps.

## Before migrating

1. **Close or merge** all open autodocs PRs on the old platform
2. **Back up** your `config.yaml` and `feedback/open-prs.json`
3. **Note** your current `feature_name`, `docs`, `relevant_paths`, and `package_map` settings — these are platform-independent and will be preserved

## Migration steps

### 1. Update platform and connection

Edit `config.yaml`. Replace the platform and connection block:

**From GitHub:**
```yaml
platform: github
github:
  owner: myorg
  repo: myrepo
```

**To GitLab:**
```yaml
platform: gitlab
gitlab:
  host: gitlab.com          # or your self-hosted instance
  project_path: mygroup/myrepo
```

**To Bitbucket:**
```yaml
platform: bitbucket
bitbucket:
  workspace: myworkspace
  repo: myrepo
```

**To Azure DevOps:**
```yaml
platform: ado
ado:
  org: myorg
  project: myproject
  repo: myrepo
  repo_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # GUID from ADO
```

### 2. Update owner and team usernames

Each platform uses a different username field:

| Platform | Owner field | Team member field |
|---|---|---|
| GitHub | `github_username` | `github_username` |
| GitLab | `gitlab_username` | `gitlab_username` |
| Bitbucket | `bitbucket_username` | `bitbucket_username` |
| ADO | `ado_id` (GUID) | `ado_id` (GUID) |

Update `owner` and each entry in `team_members`.

### 3. Reset feedback state

The old platform's PR numbers won't match the new platform:

```bash
echo "[]" > .autodocs/feedback/open-prs.json
```

### 4. Re-render prompts and scripts

```bash
./setup.sh upgrade
```

This re-renders all prompts and scripts with the correct tool allowlists for your new platform.

### 5. Test with dry-run

```bash
.autodocs/autodocs-sync.sh --dry-run
```

Verify the pipeline discovers PRs and generates drift alerts on the new platform.

## What changes per platform

| Feature | GitHub | GitLab | Bitbucket | ADO |
|---|---|---|---|---|
| PR fetching | Pre-fetched (`gh`) | Live (`glab`) | Live (`curl`) | Live (MCP tools) |
| PR creation | `gh pr create` | `glab mr create` | REST API | MCP tool |
| Stale management | Full (warn + label + close) | Full (warn + label + close) | Partial (warn + close, no labels) | Full (warn + tag + abandon) |
| Auth method | `gh auth` | `glab auth` | `BITBUCKET_TOKEN` env var | `az login` |

## What stays the same

These are platform-independent and don't need changes:

- `feature_name`, `docs`, `relevant_paths`, `relevant_pattern`
- `package_map` and `source_roots`
- `auto_pr` settings (branch prefix, target branch)
- `stale_pr` settings (warn/close days)
- `limits` settings
- All Python helper scripts
- Prompt templates (platform logic is embedded)
- `drift-status.md`, `drift-log.md`, `metrics.jsonl` (historical data)

## Platform prerequisites

| Platform | Required CLI | Install |
|---|---|---|
| GitHub | `gh` | `brew install gh` / [cli.github.com](https://cli.github.com) |
| GitLab | `glab` | `brew install glab` / [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli) |
| Bitbucket | `curl` + `BITBUCKET_TOKEN` | Token from Bitbucket settings → App passwords |
| ADO | `az` + ADO MCP server | `brew install azure-cli` + Claude Code MCP config |
