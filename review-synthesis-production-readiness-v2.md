# Review Synthesis v2: Production Readiness (Actual Round 2)

> 6 models reviewed the v2 plan with resolved uncertainties
> Date: 2026-03-05

## Verification Decision: Unanimous

**6/6 chose Option A (drop dual-model) with shadow mode.**

No dissent. The data settled it.

## Resolved Uncertainties — Final Answers

| # | Question | Answer | Agreement |
|---|----------|--------|-----------|
| U1 | Option A vs B | **Option A + 2-week shadow** | 6/6 |
| U2 | Verify anchoring | N/A now; if B later: hide REASONING, show only FIND/REPLACE | 6/6 |
| U3 | Orphan branch | Works; scope file checkout explicitly; handle first-run | 6/6 |
| U4 | Activity detection | Any comment in last 7 days (don't filter by bot) | 5/6 |
| U5 | max_prs_per_run | Fixed default 20, manual override | 6/6 |
| U6 | Retry scope | Non-zero exit code only, 3 attempts, exponential backoff | 6/6 |
| U7 | Rollout modes | Existing flags sufficient (--dry-run + auto_pr.enabled) | 6/6 |

## New Gaps Identified in Round 2

### Universally flagged (4+/6)

**1. Shadow mode needs sharp exit criteria** (Opus, Gemini, GPT)
Don't just "evaluate after 2 weeks." Define now:
- Minimum 10 suggestion sets before deciding
- If shadow flags INCORRECT and that suggestion was later reverted → implement Option B
- If shadow agrees with everything → permanently remove verify
- If <10 data points in 2 weeks → extend shadow period

**2. Deterministic FIND verification in Python** (Opus — new, critical)
Between Call 3 (suggest) and Call 4 (apply), mechanically verify every FIND block exists in the target doc file. This is ~20 lines of Python and closes the last gap where correctness depends on LLM compliance. The system's philosophy is "deterministic Python for verifiable operations" — this is the obvious missing application of that principle.

**3. First-run edge case** (Opus, MiniMax, GLM)
No `last-successful-run` file on first run. Default lookback should be short (24h) to avoid hitting `max_prs_per_run` on high-activity repos. Document and make configurable.

**4. Global open PR limit** (Gemini — new)
`max_prs_per_run` limits new PRs per run, but doesn't limit total open PRs. If runs accumulate 60 open PRs, the team disables the tool. Add `max_open_prs: 10` — skip sync if already at limit.

**5. Secret/diff sanitization** (Gemini — new)
Diffs sent to the LLM could contain accidentally committed secrets. Pre-flight check for high-entropy strings or known secret patterns (`sk-`, `AKIA`, etc.) before including diffs in prompts.

**6. Failure alerting** (Gemini, Grok, GLM)
If the pipeline fails, nobody knows. CI workflow should create a GitHub issue or post to webhook on failure.

**7. Prompt injection should move to Phase 1** (GLM, Grok)
It's a security vulnerability that exists today. Don't defer to Phase 3.

### Flagged by 2-3/6

**8. Scoped orphan branch checkout** (Opus)
`git checkout origin/autodocs-state -- .` restores ALL files. Scope to explicit state file list to prevent contamination.

**9. Post-merge error detection** (Opus)
To measure the 10% error threshold: track if autodocs-modified sections are edited by non-autodocs commits within 7 days of merge. Automatable proxy for "suggestion was wrong."

**10. Merge conflict detection for stale PRs** (GLM)
PRs with `mergeable: false` should be closed immediately — they can't be merged anyway.

**11. Config validation at startup** (GLM)
Catch malformed config.yaml before wasting LLM calls.

**12. `autodocs:keep-open` label check must be first** (GLM, MiniMax)
Before any stale logic runs, check for override label.

## Phasing Adjustments

Two reorders from round 2:

**1. Move prompt injection to Phase 1** (GLM, Grok)
Security fix, not hardening. Should ship before CI deployment.

**2. Feedback bootstrap (Step 2) before verification change (Step 1)** (Opus)
The error rate safety net for Option A requires a working feedback loop. Bootstrap feedback first, then drop verification.

**Revised implementation order:**
```
Phase 0: Infrastructure
  0a: Metrics logging + status command
  0b: Cost controls (max_prs_per_run + max_open_prs)
  0c: Retry wrapper
  0d: Failure alerting (CI issue creation)

Phase 1: Core Fixes
  Step 1: Feedback bootstrap (discover + durable markers) — FIRST
  Step 2: Lookback timestamp — quick win
  Step 3: Deterministic FIND verification (Python, between Call 3 and 4) — NEW
  Step 4: Drop dual-model (shadow mode) — now safe, feedback is live
  Step 5: Prompt injection mitigation — MOVED from Phase 3
  Step 6: Stale PR management (two-phase + activity + keep-open)

Phase 2: CI
  Step 7: GitHub Actions (orphan state, concurrency, pinned version, alerting)

Phase 3: Polish
  Step 8: Config drift nudge
  Step 9: Post-merge error detection (for 10% threshold)
  Step 10: Config validation
```

## Final Test Estimate

Round 2 reviews correctly noted 18 tests is too low. Realistic count:

| Component | Tests |
|-----------|-------|
| stale-helper.py | 10 |
| feedback-helper discover | 4 |
| retry wrapper | 3 |
| deterministic FIND verification | 4 |
| metrics logging | 2 |
| lookback timestamp | 2 |
| shadow mode (log-only, no-gate) | 2 |
| max_open_prs limit | 1 |
| config validation | 2 |
| **Total** | **30** |

**Final total: 174 → ~204**
