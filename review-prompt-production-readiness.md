# Adversarial Review: autodocs Production Readiness Plan

## Your Role

You are a senior/principal engineer reviewing a production readiness plan for **autodocs** — an automated documentation drift detection tool. Your job is to find flaws, gaps, risks, and missed opportunities. Be rigorous and specific. We want to ship a tool that works reliably, not one that looks good on paper.

## Review Scope

1. **Critique the 6-step plan** below — find flaws in logic, missed edge cases, overengineering, underengineering
2. **Identify what we've missed** — are there production concerns not addressed?
3. **Challenge our assumptions** — are we solving the right problems? Are the priorities correct?
4. **Suggest alternatives** — if you'd solve something differently, explain why

## What NOT to review

- The core concept (drift detection via PR analysis). This is proven and working.
- The 6-model adversarial review decisions from the original design phase (never auto-edit source docs, FIND/REPLACE with self-verification, etc.). These are settled.
- Code style or formatting preferences.

---

## Project Context

### What autodocs does

autodocs runs daily via Claude Code headless mode. It detects when merged PRs make documentation stale, generates verified FIND/REPLACE edit suggestions, and opens PRs with the fixes.

### Architecture (5-call daily pipeline)

```
Call 1:  Sync         — Fetch merged PRs from platform (GitHub/ADO/GitLab/Bitbucket),
                        get file changes via git diff-tree (A/M/D/R), targeted diffs,
                        PR descriptions + review threads
                        ↓
         match-helper.py  — Deterministic file→section mapping (Python, 20 TDD tests)
         drift-helper.py  — Pre-process: parse report, group alerts, dedup against
                            existing status, manage lifecycle (Python, 24 TDD tests)
                        ↓
Call 2:  Drift         — Read drift-context.json (pre-processed data), read doc sections,
                        generate "What Changed" descriptions, write drift-report.md,
                        drift-status.md, drift-log.md
                        ↓
         drift-helper.py suggest-dedup — Filter against changelogs + open PRs
                        ↓
Call 3:  Suggest       — Read suggest-context.json, read flagged doc sections + PR diffs,
                        generate FIND/REPLACE suggestions with self-verification,
                        generate changelog entries (what changed + why)
Call 3v: Verify        — Same suggest prompt with variant reasoning path
                        (verify-variation.md template), writes to separate file
Call 4:  Apply         — Compare primary + verify suggestions, apply AGREED ones to
                        doc files in repo, create branch + PR, write feedback tracking

Weekly:  Structural    — Verify doc file references against repo, find undocumented files
```

### What's proven

- 7/7 verified suggestions on Channel Pages (Microsoft production, 1200-line doc, 9-person team)
- 7/7 verified suggestions on demo repo (JWT+RBAC migration, 8 files, 4 change types)
- Auto-PRs on both ADO (work item linked) and GitHub (demo repo)
- 174 BATS tests across 12 files, all passing (unit + integration with mock Claude)
- Deterministic Python pre-processing handles parse/group/dedup/lifecycle — LLM focuses on natural language

### Key design decisions (from 6-model adversarial reviews)

- Never auto-edit source-of-truth docs — all changes go through PR review
- FIND/REPLACE with self-verification — mechanically verifiable
- Stale detection instead of fuzzy matching — if FIND text doesn't match, skip it
- Deterministic matching (Python) instead of LLM matching — tested, 100% reliable
- Dual Opus verification with prompt variation — same model, different reasoning paths

### Current tech stack

- Shell (sync.sh — pipeline orchestrator)
- Python (4 helper scripts — config, feedback, match, drift)
- Markdown prompts (5 templates rendered via envsubst)
- BATS (test framework — 174 tests)
- Platforms: GitHub (gh CLI), ADO (MCP), GitLab (glab CLI), Bitbucket (curl)

---

## The 6 Problems We Identified

### Problem 1: Multi-model verification has 75% false-positive rate (CRITICAL)

In our end-to-end test, 3 out of 8 suggestions were AGREED. 3 were DISPUTED, 2 were UNMATCHED. Detailed analysis found:

**0 out of 3 DISPUTEDs were true disputes.** All were false positives:

| Suggestion | Status | Reality |
|-----------|--------|---------|
| API endpoint table | DISPUTED | Primary lists 9 endpoints with RBAC permissions, Verify lists 6 with Yes/No. Same facts, different presentation. |
| listUsers return type | DISPUTED | Both agree on PaginatedResponse. Primary correctly includes `status` field; Verify omits it. Superset. |
| Auth error cases | DISPUTED | Primary split auth into 2 suggestions; Verify merged into 1. Granularity mismatch. |
| createUser default role | UNMATCHED | Primary claims default changed to `viewer`; source code says `member`. Verify correctly abstained. (Accidental catch.) |

**Root cause**: The apply prompt says "the REPLACE/INSERT content makes the same factual claims." This is evaluated as near-identical text, not semantic equivalence. No superset handling. No granularity normalization.

**Impact**: The system effectively never auto-applies anything meaningful. Every PR requires manual review, defeating auto-PR.

### Problem 2: Feedback loop never bootstraps

`open-prs.json` is only written by the last step of the last LLM call (Call 4, Step 5). If anything fails after PR creation but before tracking, the PR is permanently orphaned. PRs #2 and #4 on the demo repo were created by previous autodocs runs but are untracked — zero dedup, zero acceptance data.

### Problem 3: Sync lookback picks up already-processed PRs

`gh pr list --search "merged:>=2026-03-04"` uses a **date**, not datetime. Everything merged on March 4th gets re-fetched on March 5th. Monday 72h window triples the overlap. drift-helper dedup prevents duplicate alerts, but the LLM still wastes tokens re-analyzing old PRs.

### Problem 4: Stale autodocs PRs accumulate

PRs #2 and #4 are open and stale — they contain suggestions for the old codebase state. Nobody will merge them. There's no mechanism to close them.

### Problem 5: System only runs on a laptop

launchd on macOS. If the laptop is off, closed, or sleeping, nothing runs. No CI/CD integration.

### Problem 6: Config drift (package_map)

New packages (e.g., `src/middleware/`) aren't in the config's package_map. The structural scan flags undocumented files but doesn't suggest config updates.

---

## The Plan

### Step 1: Fix verification comparison logic

**Current** (apply-prompt.md):
```
- AGREED: FIND targets same text AND REPLACE makes same factual claims
- DISPUTED: Same section, different factual claims
- UNMATCHED: No verify suggestion for this section → skip
```

**Proposed**:
```
- Granularity alignment: combine multi-suggestion groups per section before comparing
- AGREED: No contradictory factual claims (function names, error codes, defaults).
  Supersets are AGREED — apply the more complete version.
- DISPUTED: Only for mutually exclusive claims (e.g., different function names)
- UNMATCHED: Apply with a flag ("review recommended") instead of skipping
```

Also add granularity constraint to verify-variation.md:
```
Produce one suggestion per section header. Do not merge or split across sections.
```

### Step 2: Feedback bootstrap

- Add `discover` operation to feedback-helper.py — searches platform for PRs with "autodocs" in title, backfills open-prs.json
- Run discovery in sync.sh before the feedback state check
- Add `find_text` (first 100 chars of FIND block) to open-prs.json schema for stale detection

### Step 3: Lookback dedup via processed-prs.json

- Record processed PR numbers after Call 1 succeeds
- Add filtering step to sync-prompt.md: skip PRs in processed-prs.json
- 14-day prune cycle (matches activity-log retention)

### Step 4: Stale PR management via stale-helper.py

Three deterministic conditions:
1. SUPERSEDED: newer open autodocs PR targets same (doc, section) pairs
2. EXPIRED_FIND: FIND text from suggestions no longer matches doc on main
3. AGE: open >14 days (configurable)

Auto-close with explanatory comment. Integrated into sync.sh between feedback check and Call 1.

### Step 5: GitHub Actions workflow

- Direct CLI: `npm install -g @anthropic-ai/claude-code`
- Triggers: daily cron (weekdays) + weekly Saturday + manual dispatch
- State files committed back with `[skip ci]`
- `ANTHROPIC_API_KEY` as repository secret

### Step 6: Config drift nudge

Add "Suggested Config Updates" section to structural scan output:
```
| New Directory | Suggested package_map Key | Suggested Section Name |
```

---

## Questions for Reviewers

1. **Is the verification fix correct?** Inverting the default from "same = AGREED" to "no contradictions = AGREED" is a significant change. Does this risk letting through genuinely wrong suggestions?

2. **Should UNMATCHED apply by default?** The current plan applies UNMATCHED with a flag. Is this too permissive? Our data shows 1 UNMATCHED was a structural mismatch (fine to apply) and 1 was correctly abstained (would have applied a wrong suggestion). That's 50/50.

3. **Is processed-prs.json the right solution for lookback?** An alternative is using precise timestamps instead of dates. Another is having the LLM deduplicate against the previous daily-report.md. Which is most robust?

4. **Is auto-closing stale PRs too aggressive?** Should we comment-only for the first N days, then close? Is 14 days the right threshold?

5. **Is there a simpler alternative to multi-model verification entirely?** The original 7/7 results were all single-model. Is dual-model verification adding more noise than signal?

6. **What are we missing for production readiness?** What would you want before deploying this to a 50-person engineering team?

---

## Files for Reference

If you want to inspect the actual code (not required for the review):

| File | What it does |
|------|-------------|
| `templates/sync.sh` | Pipeline orchestrator (333 lines) |
| `templates/apply-prompt.md` | PR creation + multi-model comparison |
| `templates/verify-variation.md` | Verify reasoning variation |
| `templates/drift-prompt.md` | Drift detection (reads drift-context.json) |
| `templates/suggest-prompt.md` | FIND/REPLACE suggestion generation |
| `scripts/drift-helper.py` | Deterministic pre-processing (588 lines) |
| `scripts/feedback-helper.py` | PR tracking (128 lines) |
| `scripts/match-helper.py` | File→section matching (178 lines) |
| `tests/test-integration.bats` | 14 end-to-end tests with mock Claude |
| `config.example.yaml` | Full config template with all features |
| `docs/feedback-roadmap.md` | 4-phase feedback loop plan with activation triggers |
