# Troubleshooting

## Pipeline won't start

**Symptom:** `sync.log` shows `SKIPPED — another sync is running`

**Cause:** A previous run crashed without removing the lock directory.

**Fix:**
```bash
rmdir .autodocs/.sync.lock
```

---

**Symptom:** `sync.log` shows `AUTH FAILED — aborting sync`

**Cause:** The Claude Code CLI session token has expired (when using `llm.backend: cli`).

**Fix:** Open Claude Code interactively once to refresh authentication:
```bash
claude
```
Then exit and re-run the pipeline.

If using `llm.backend: api`, verify your `ANTHROPIC_API_KEY` environment variable is set and valid.

---

**Symptom:** `sync.log` shows `CONFIG ERROR: ...`

**Cause:** The `config.yaml` has a structural error. The error message says what's wrong.

**Common config errors:**
- `missing required field: platform` — add `platform: github` (or gitlab, bitbucket, ado)
- `github platform requires github.owner` — add the `github:` block with owner and repo
- `docs must be a list` — `docs:` should be a YAML list, not a string
- `auto_pr.enabled requires auto_pr.target_branch` — add `target_branch: main`
- `llm.backend must be 'cli' or 'api'` — check spelling

---

## Sync runs but finds no PRs

**Symptom:** `daily-report.md` shows `pr_count: 0`

**Check `last-successful-run`:** If this timestamp is very recent, the lookback window may be too short. The pipeline only fetches PRs merged since the last successful run.

**Fix:** Delete the timestamp to force a 1-day lookback:
```bash
rm .autodocs/last-successful-run
```

**Check platform config:** Verify `github.owner` and `github.repo` (or equivalent for your platform) match your repository.

**Check team members:** The deterministic sync filters PRs to team members. If your team isn't configured, PRs won't appear. Add team members to `config.yaml` or use `setup.sh team discover`.

---

**Symptom:** `daily-report.md` shows `sync_status: partial` with an error

**Cause:** The platform CLI failed. The error message in the report explains why.

**Common platform errors:**
- `gh CLI not found` — install: https://cli.github.com/
- `glab CLI not found` — install: https://gitlab.com/gitlab-org/cli
- `az CLI not found` — install: https://learn.microsoft.com/cli/azure/
- `BITBUCKET_TOKEN environment variable not set` — set the token
- Timeout/connection errors — transient, will retry on next run

---

## All files show UNMAPPED

**Symptom:** `resolved-mappings.md` has all UNMAPPED entries, log shows `WARN: 0/N files matched package_map`

**Cause:** The `package_map` entries in `config.yaml` don't match the file paths in your PRs.

**Fix:** Run `setup.sh analyze` to see your repo structure, then update `docs[].package_map` in `config.yaml`. Common issues:
- Missing `source_roots` (e.g., need `src/` stripped before matching)
- Using basename when you need directory matching
- Glob patterns not covering your file extensions

---

## Suggestions are all REVIEW instead of CONFIDENT

**Check source-context/:** If this directory is empty, the LLM couldn't read your source files. Verify `docs[].repo_path` points to the correct files.

**Check verified-suggestions.json:** If FIND blocks show `status: "FAIL"`, the suggested text doesn't exist in your doc. This usually means the doc was already updated or the LLM quoted incorrectly.

**Check replace-verification.json:** If gate shows `BLOCK`, the code references in the suggestion don't match source files. This is the verification stack working correctly — it caught a wrong value.

---

## PRs never get created

**Check config:** Ensure `auto_pr.enabled: true` is set with `auto_pr.target_branch`.

**Check dry-run:** If `sync-status.md` shows `apply: dry-run`, you ran with `--dry-run`. Run without it to create PRs.

**Check suggestion count:** If `drift-suggestions.md` has `suggestion_count: 0`, no actionable drift was found.

**Check drift severity:** Suggestions are only generated for HIGH or CRITICAL drift alerts. LOW alerts are logged but don't trigger suggestions.

**Check apply log:** If `sync.log` shows `APPLY SUCCESS: 0 applied`, all suggestions were filtered out by verification gates (FIND failed, REPLACE blocked, or REVIEW confidence).

---

## Stale PRs not being managed

**GitHub:** Stale management is fully automated (warn → label → close).

**GitLab/Bitbucket/ADO:** Stale detection works (logged in `pre-sync-result.json`), but verify that your platform CLI (`glab`, `az`, or `BITBUCKET_TOKEN`) is configured and authenticated.

---

## Log files growing too large

The pipeline auto-rotates `sync.log` at 100KB (keeps last 50 lines) and `metrics.jsonl` at 500KB (keeps last 1000 entries). To manually trim:
```bash
tail -500 .autodocs/metrics.jsonl > .autodocs/metrics.jsonl.tmp && mv .autodocs/metrics.jsonl.tmp .autodocs/metrics.jsonl
```

---

## Reading the logs

**`sync.log`** — timestamped entries for debugging failures. Look for `FAILED`, `WARN`, or `ERROR`.

**`metrics.jsonl`** — one JSON line per pipeline stage per run. Use `setup.sh metrics` for a summary.

**`sync-status.md`** — last run's outcome. Shows each stage's status.

---

## Common error patterns

| Error in log | Cause | Fix |
|---|---|---|
| `AUTH FAILED` | Expired Claude session or invalid API key | CLI: open `claude` interactively. API: check `ANTHROPIC_API_KEY` |
| `CONFIG ERROR` | Malformed config.yaml | Read the error message — it says exactly what's wrong |
| `git fetch failed` | Network issue or remote gone | Check git remote and network |
| `gh CLI not found` | GitHub CLI not installed | Install: https://cli.github.com/ |
| `FIND VERIFY: some FIND blocks failed` | Suggested text not in doc | Doc may already be updated |
| `REPLACE VERIFY: some suggestions BLOCKED` | Code reference wrong | Verification caught a hallucination |
| `SKIPPED — open PR limit` | Too many unreviewed PRs | Review and merge/close existing autodocs PRs |
| `telemetry (Kusto) requires LLM sync` | Telemetry configured with API backend | Kusto needs `llm.backend: cli` |
| `APPLY SUCCESS: 0 applied` | All suggestions filtered by gates | Check verification JSONs for reasons |
