# Troubleshooting

## Pipeline won't start

**Symptom:** `sync.log` shows `SKIPPED — another sync is running`

**Cause:** A previous run crashed without removing the lock directory.

**Fix:**
```bash
rmdir .autodocs/.sync.lock
```

---

**Symptom:** `sync-status.md` shows `error: Claude Code auth expired`

**Cause:** The Claude Code CLI session token has expired.

**Fix:** Open Claude Code interactively once to refresh authentication:
```bash
claude
```
Then exit and re-run the pipeline.

---

## Sync runs but finds no PRs

**Symptom:** `daily-report.md` shows `pr_count: 0`

**Check `last-successful-run`:** If this timestamp is very recent, the lookback window may be too short. The pipeline only fetches PRs merged since the last successful run.

**Fix:** Delete the timestamp to force a 1-day lookback:
```bash
rm .autodocs/last-successful-run
```

**Check platform config:** Verify `github.owner` and `github.repo` (or equivalent for your platform) match your repository.

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

**Check config:** Ensure `auto_pr.enabled: true` is set, not just `auto_pr:`.

**Check dry-run:** If `sync-status.md` shows `apply: dry-run`, you ran with `--dry-run`. Run without it to create PRs.

**Check suggestion count:** If `drift-suggestions.md` has `suggestion_count: 0`, no actionable drift was found.

**Check drift severity:** Suggestions are only generated for HIGH or CRITICAL drift alerts. LOW alerts are logged but don't trigger suggestions.

---

## Stale PRs not being managed

**GitHub:** Stale management is fully automated (warn → label → close).

**GitLab/Bitbucket/ADO:** Stale detection works (logged in `pre-sync-result.json`), but verify that your platform CLI (`glab`, `az`, or `BITBUCKET_TOKEN`) is configured and authenticated.

---

## Log files growing too large

The pipeline auto-rotates `sync.log` at 100KB (keeps last 50 lines). `metrics.jsonl` grows unbounded. To trim old metrics:
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
| `AUTH FAILED` | Expired Claude session | Open `claude` interactively |
| `git fetch failed` | Network issue or remote gone | Check git remote and network |
| `FIND VERIFY: some FIND blocks failed` | Suggested text not in doc | Doc may already be updated |
| `REPLACE VERIFY: some suggestions BLOCKED` | Code reference wrong | Verification caught a hallucination |
| `SKIPPED — open PR limit` | Too many unreviewed PRs | Review and merge/close existing autodocs PRs |
