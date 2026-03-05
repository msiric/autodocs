# autodocs — Implementation Plan: Production Readiness

> Created: 2026-03-05
> Scope: 6 issues that move autodocs from prototype to production-grade
> Research basis: 3-agent parallel investigation + end-to-end test results

## Issues (ordered by impact)

1. **Verification false-positive rate: 75%** — rejecting correct suggestions
2. **Feedback loop bootstrapping** — tracking never starts, PRs orphaned
3. **Lookback re-processing** — same PRs analyzed repeatedly
4. **Stale PR accumulation** — old autodocs PRs never closed
5. **GitHub Actions workflow** — replace laptop dependency
6. **Config drift** — package_map doesn't track new packages

## Dependency Graph

```
Step 1 (verification logic)  — standalone, highest impact
Step 2 (feedback bootstrap)  — standalone
Step 3 (lookback dedup)      — standalone
Step 4 (stale PR mgmt)       ← depends on Step 2 (needs open-prs.json populated)
Step 5 (GitHub Actions)      ← after Steps 1-4 (CI should run the fixed pipeline)
Step 6 (config drift nudge)  — standalone, low priority
```

Order: 1 → 2 → 3 → 4 → 5 → 6

---

## Step 1: Fix multi-model verification comparison logic

**Problem**: 0 out of 3 DISPUTEDs were true disputes. All were false positives from:
- String-level comparison instead of semantic equivalence
- No superset/subset handling
- Structural granularity mismatch (Primary produces 2 suggestions for a section, Verify produces 1)

**Root cause in apply-prompt.md lines 27-30**: "REPLACE/INSERT content makes the same factual claims" gives the LLM no guidance on how to distinguish wording differences from factual disagreements.

### Fix: Rewrite comparison criteria in apply-prompt.md

Replace lines 27-34 with:

```markdown
For each CONFIDENT + Verified: YES suggestion in drift-suggestions.md, check if
drift-suggestions-verify.md has a suggestion for the SAME (doc, section):

**Granularity alignment:** If one file has multiple suggestions for the same section
header, treat them as a single combined suggestion for comparison. If one file has
a single suggestion covering content that the other splits into parts, compare
against the combined content.

Comparison criteria — check for CONTRADICTIONS, not identical wording:
- **AGREED**: Both suggestions target the same section AND make no contradictory
  factual claims (function names, error codes, parameter names, default values).
  Different wording, different formatting, or one being more detailed than the other
  are NOT contradictions. If one is a superset of the other (includes all the same
  facts plus additional correct facts), that is AGREED — apply the more complete version.
- **DISPUTED**: The suggestions make mutually exclusive factual claims that cannot both
  be true (e.g., one says the function is called `classifyError`, the other says
  `categorizeError`; one says the default role is `viewer`, the other says `member`).
  Only mark as DISPUTED when there is a clear factual conflict.
- **UNMATCHED**: The verify file has no suggestion for this section. Apply with a note
  in the PR description: "Unmatched — verify model did not generate a corresponding
  suggestion. Review recommended."

Apply AGREED and UNMATCHED suggestions. Skip DISPUTED suggestions.
```

Key changes:
- **Granularity alignment** prevents structural mismatches from causing false disputes
- **"No contradictions" instead of "same factual claims"** — the bar is inverted. Default is AGREED unless there's a clear conflict.
- **Superset handling** — more complete is AGREED, not different
- **UNMATCHED now applies with a flag** instead of skipping entirely. Most UNMATCHED cases are structural (one model consolidated), not quality issues.

### Fix: Enforce consistent granularity in verify-variation.md

Add to the verify variation template:

```markdown
4. Produce one suggestion per section header in the doc (one for "API Endpoints",
   one for "Authentication", etc.). Do not merge multiple sections into one
   suggestion or split one section across multiple suggestions.
```

### Tests

Run the end-to-end test again after the fix and verify:
- S1 (endpoint table): should be AGREED (superset, no contradiction)
- S2 (listUsers return): should be AGREED (superset)
- S6 (auth error cases): should be AGREED (granularity aligned)
- S3 (createUser default): should still be caught (if verify abstains, it's UNMATCHED and flagged)

**Files changed**: `templates/apply-prompt.md`, `templates/verify-variation.md`
**Risk**: Medium — changes LLM behavior, needs end-to-end validation

---

## Step 2: Fix feedback loop bootstrapping

**Problem**: `open-prs.json` is only created by Call 4 Step 5 (the last step in the last LLM call). If Call 4 fails/times out after creating the PR but before writing tracking data, the PR is permanently orphaned. PRs #2 and #4 on the demo repo are untracked.

### Fix 2a: Add PR discovery to sync.sh

Before the existing feedback check, search the platform for autodocs PRs and backfill `open-prs.json`:

```bash
# Bootstrap: discover existing autodocs PRs not in tracking file
if command -v python3 >/dev/null 2>&1 && [ -f "$FEEDBACK_HELPER" ]; then
  case "$PLATFORM" in
    github)
      discovered=$(gh pr list -R "$FB_GH_OWNER/$FB_GH_REPO" \
        --search "autodocs in:title" --state open \
        --json number,createdAt --limit 20 2>/dev/null)
      [ -n "$discovered" ] && \
        python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" discover "$discovered" github 2>/dev/null
      ;;
  esac
fi
```

### Fix 2b: Add `discover` operation to feedback-helper.py

```python
def handle_discover(data, args):
    """Backfill open-prs.json from platform PR search results."""
    import json as json_mod
    prs_json = json_mod.loads(args[0])
    platform = args[1] if len(args) > 1 else "github"
    for pr in prs_json:
        number = pr.get("number")
        if not number:
            continue
        # Skip if already tracked
        if any(p.get("pr_number") == number for p in data):
            continue
        data.append({
            "pr_number": number,
            "platform": platform,
            "date": pr.get("createdAt", "")[:10],
            "state": "open",
            "suggestions": [],  # Can't reconstruct, but prevents re-creation
        })
```

### Fix 2c: Add `find_text` to tracking schema

In apply-prompt.md Step 5, extend the suggestions schema:

```json
{"doc": "<doc name>", "section": "<section name>", "type": "<REPLACE or INSERT AFTER>", "find_text": "<first 100 chars of FIND block>"}
```

This enables stale detection in Step 4 (FIND text matching against current doc).

**Files changed**: `templates/sync.sh`, `scripts/feedback-helper.py`, `templates/apply-prompt.md`
**Tests**: Add discover tests to test-feedback-helper.bats
**Risk**: Low — additive, doesn't change existing behavior

---

## Step 3: Fix lookback re-processing

**Problem**: Date-based lookback (`merged:>=2026-03-04`) picks up PRs already processed on the previous day. Monday 72h compounds it.

### Fix: Track processed PRs in state file

Add `processed-prs.json` — a simple list of PR numbers already analyzed.

**drift-helper.py**: Add `record-processed` operation:
```python
def record_processed(output_dir):
    """Record processed PR numbers from daily-report.md."""
    output_dir = Path(output_dir)
    report = parse_report(output_dir / "daily-report.md")

    state_file = output_dir / "processed-prs.json"
    existing = []
    if state_file.exists():
        existing = json.loads(state_file.read_text())

    today = report.get("date", "")
    existing_nums = {e["number"] for e in existing}
    for pr in report.get("prs", []):
        if pr["number"] not in existing_nums:
            existing.append({"number": pr["number"], "date": today})

    # Prune entries older than 14 days
    if today:
        cutoff = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=14)
        existing = [e for e in existing if datetime.strptime(e["date"], "%Y-%m-%d") >= cutoff]

    state_file.write_text(json.dumps(existing, indent=2) + "\n")
```

Note: this reintroduces `timedelta` — add it back to the import.

**sync-prompt.md**: Add filtering step after PR fetch:
```markdown
After fetching PRs, read `${OUTPUT_DIR}/processed-prs.json` (if it exists).
This file contains PR numbers already analyzed in previous runs. Remove any
fetched PRs whose number appears in this list. This prevents re-processing
PRs that were caught by a previous day's sync.
```

**sync.sh**: Call `record-processed` after Call 1 succeeds (after drift-helper pre-process):
```bash
python3 "$DRIFT_HELPER" record-processed "$OUTPUT_DIR" 2>/dev/null || true
```

**Files changed**: `scripts/drift-helper.py`, `templates/sync-prompt.md`, `templates/sync.sh`
**Tests**: Add 3 tests to test-drift-helper.bats (record, prune, filter)
**Risk**: Low — additive state file, graceful on missing

---

## Step 4: Stale PR management

**Problem**: Old autodocs PRs (#2, #4) accumulate and are never closed.

### Fix: Add stale-helper.py

Three staleness conditions (all deterministic):

1. **SUPERSEDED**: A newer open autodocs PR targets any of the same `(doc, section)` pairs
2. **EXPIRED_FIND**: The FIND text from suggestions no longer matches the doc on main
3. **AGE**: Open >14 days without merge (configurable via `stale_pr.max_age_days`)

CLI: `python3 stale-helper.py <open-prs.json> <config.yaml> <repo_dir> list-stale`
Output: `pr_num|reason|details` (one per line, for bash consumption)

### Integration in sync.sh

After feedback check (which updates merged/closed states), before Call 1:
```bash
STALE_HELPER="$SCRIPTS_DIR/stale-helper.py"
if [ -f "$FEEDBACK_FILE" ] && [ -f "$STALE_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  stale_prs=$(python3 "$STALE_HELPER" "$FEEDBACK_FILE" "$OUTPUT_DIR/config.yaml" "$REPO_DIR" list-stale 2>/dev/null)
  if [ -n "$stale_prs" ]; then
    while IFS='|' read -r pr_num reason details; do
      [ -z "$pr_num" ] && continue
      case "$PLATFORM" in
        github)
          gh pr comment "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" \
            --body "## autodocs: closing stale PR

Reason: **$reason**

$details

A fresh PR will be generated on the next sync if changes are still needed." 2>/dev/null
          gh pr close "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" 2>/dev/null
          ;;
      esac
      python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" update-pr "$pr_num" closed
      echo "[$TIMESTAMP] STALE: closed PR #$pr_num ($reason)" >> "$LOG_FILE"
    done <<< "$stale_prs"
  fi
fi
```

### Config extension

```yaml
stale_pr:
  max_age_days: 14
  close_superseded: true
  close_expired_find: true
```

**Files created**: `scripts/stale-helper.py`, `tests/test-stale-helper.bats`
**Files changed**: `templates/sync.sh`, `config.example.yaml`
**Tests**: ~10 tests (superseded, expired-find, age, multi-PR, edge cases)
**Risk**: Medium — auto-closes PRs, but only with explanatory comments

---

## Step 5: GitHub Actions workflow

**Design**: Direct CLI approach (`npm install -g @anthropic-ai/claude-code`), not `claude-code-action@v1`.

### .github/workflows/autodocs.yml

Triggers: daily cron (weekdays 17:00 UTC) + weekly Saturday + manual dispatch.
State files committed back with `[skip ci]` to prevent recursive triggers.

Key adaptations needed:
- `sync.sh` needs `OUTPUT_DIR`/`REPO_DIR` to fall back to env vars when not baked in by envsubst
- PATH augmentation needs `$(npm -g bin)` for CI environments
- State persistence: commit drift-status.md, drift-log.md, activity-log.md, feedback/ back to repo

### setup.sh changes

Add CI option to the scheduling section:
```bash
elif [[ "${CI_MODE:-}" == "true" ]] || confirm "Use GitHub Actions instead of local schedule?"; then
  mkdir -p "$REPO_DIR/.github/workflows"
  # Generate workflow from template
fi
```

**Files created**: `.github/workflows/autodocs.yml` (or `templates/autodocs.yml` as template)
**Files changed**: `templates/sync.sh` (env var fallback), `templates/structural-scan.sh` (same), `setup.sh` (CI option)
**Risk**: Low — additive, doesn't affect existing laptop-based setup

---

## Step 6: Config drift nudge

**Problem**: When the structural scan finds undocumented files in new directories, it flags them but doesn't suggest config updates. The user has to manually figure out what to add.

### Fix: Add config suggestions to structural scan output

In `templates/structural-scan-prompt.md`, add a section:

```markdown
## Suggested Config Updates

If any undocumented files are in directories not covered by the current
`package_map` in config, suggest additions:

| New Directory | Suggested package_map Key | Suggested Section Name |
|---------------|--------------------------|----------------------|
| src/middleware/ | middleware | Middleware |
```

This is LLM-generated (the structural scan already has LLM context) so no Python helper needed. Just a prompt addition.

**Files changed**: `templates/structural-scan-prompt.md`
**Risk**: None — advisory output only

---

## Summary

| Step | Impact | Risk | Tests Added | Key Metric |
|------|--------|------|-------------|------------|
| 1. Verification logic | Critical | Medium | End-to-end | AGREED rate: 37% → target >80% |
| 2. Feedback bootstrap | High | Low | ~5 | Tracked PRs: 1 → all |
| 3. Lookback dedup | Medium | Low | ~3 | Duplicate PRs per run: 3 → 0 |
| 4. Stale PR mgmt | Medium | Medium | ~10 | Open stale PRs: accumulating → 0 |
| 5. GitHub Actions | High | Low | 0 (manual) | Laptop dependency: yes → no |
| 6. Config nudge | Low | None | 0 | Prompt-only change |

**Estimated new test count**: ~18 additional tests
**Total after all steps**: 174 → ~192
