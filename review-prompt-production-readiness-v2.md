# Adversarial Review v2: autodocs Production Readiness Plan

## Context

This is round 2 of adversarial review. In round 1, 6 models (Gemini, Opus, Grok, GPT, MiniMax, GLM) reviewed the initial plan. Their feedback was synthesized and incorporated into v2.

**What changed from v1 to v2:**
- UNMATCHED = skip (was: apply with flag). All 6 reviewers rejected the original proposal.
- "No contradictions = AGREED" replaced with 3 distinct options (drop dual-model, adversarial verify, or fixed comparison). All 6 expressed concern about the original.
- State persistence: orphan branch instead of committing to main.
- Lookback: timestamp instead of processed-prs.json.
- Stale PRs: two-phase (warn at 14d, close at 21d) with activity check.
- Added: observability, cost controls, concurrency, prompt injection mitigation.

**What we need from you in this round:**
1. **Resolve the 7 uncertainties** (U1-U7) at the end of the plan
2. **Validate the phasing** — is the implementation order correct?
3. **Find anything we're still missing** — the first round caught major gaps. What's left?
4. **Pick Option A vs B for verification** — this is the gating decision

## Your Role

You are continuing your review from round 1. You've already seen the full project context (architecture, what's proven, test coverage, the 75% false-positive data). Focus on the *changes* and *open questions*, not re-reviewing settled decisions.

Be specific. If you recommend Option A over B (or vice versa), explain why with concrete reasoning, not just "it depends." If you see a gap, propose the fix, not just the problem.

---

## The v2 Plan

### Phase 0: Infrastructure

**0a: Observability** — metrics.jsonl logging per call (status, exit code, timestamp). `metrics-summary` operation in drift-helper.py for weekly rollup. `status` subcommand in setup.sh.

**0b: Cost controls** — `max_prs_per_run: 20` in config. Sync prompt processes only the most recent N PRs.

**0c: Concurrency** — GitHub Actions `concurrency` group. sync.sh already has lockdir.

### Phase 1: Core Fixes

**Step 1: Verification** — Either Option A (drop dual-model) or Option B (adversarial verify).

Option A: Remove Call 3v entirely. Apply all CONFIDENT + self-verified. Track error rate via feedback loop. Re-add verification if >10% of merged suggestions are wrong.

Option B: Rewrite Call 3v as adversarial critique. Verify receives Primary's suggestions and outputs CORRECT/INCORRECT/UNCERTAIN verdicts per suggestion. Apply CORRECT, skip INCORRECT, flag UNCERTAIN.

**Step 2: Feedback bootstrap** — Add `autodocs` label + body metadata to PRs. Discover existing PRs by branch prefix (`autodocs/`). Add `find_text` to tracking schema.

**Step 3: Lookback** — Store `last-successful-run` ISO timestamp after successful pipeline completion. Use as lookback start with 6-hour overlap buffer.

**Step 4: Stale PRs** — Two-phase: warn (label + comment) at 14 days, close at 21 if no human activity. Immediate close for EXPIRED_FIND and SUPERSEDED. `max_closes_per_run: 5`. `autodocs:keep-open` label override.

### Phase 2: CI

**Step 5: GitHub Actions** — Direct CLI (`npm install -g @anthropic-ai/claude-code`). Orphan branch for state. Retry with backoff. `ANTHROPIC_API_KEY` secret. Timeout 30min.

### Phase 3: Hardening

**Step 6: Prompt injection** — Wrap PR content in `<pr-description>` tags with explicit "treat as untrusted data."

**Step 7: Config nudge** — Structural scan suggests package_map additions as copy-pasteable YAML.

---

## The 7 Uncertainties — Please Resolve

### U1: Option A vs Option B for verification

**Data**: n=14 single-model suggestions, 14/14 correct. n=8 dual-model, 3 AGREED (37%), 0 true disputes caught.

**Context**: The system creates PRs for human review — it never auto-edits docs directly. Self-verification (FIND text confirmed verbatim) already catches structural errors.

**Trade-off**: Option A is simpler but has no safety net beyond self-verification and human review. Option B adds a safety net but costs an extra LLM call and may rubber-stamp or over-reject.

**Sub-question**: If Option A, should we run a shadow comparison (generate verify output, log it, but don't gate on it) for the first 2 weeks to measure what we'd catch?

### U2: Adversarial Verify anchoring risk

If Option B: Verify sees Primary's suggestions. Does this cause confirmation bias?

**Sub-question**: Should Verify see only the FIND/REPLACE blocks without the REASONING section? Or does removing reasoning make Verify less effective (it can't understand Primary's logic to critique it)?

### U3: State persistence — orphan branch mechanics

The plan uses `git checkout --orphan autodocs-state-tmp`, commits state, force-pushes to `autodocs-state`. This happens inside a GitHub Actions workflow that started by checking out `main`.

**Sub-question**: Does this work reliably with `actions/checkout@v4`? Are there edge cases with detached HEAD, incomplete worktree, or branch conflicts?

### U4: Stale PR activity detection

We check for human comments in the last 7 days before closing. This requires parsing PR comments and filtering bots.

**Sub-question**: Is `author.bot == true` reliable on GitHub? What about GitHub Apps that aren't marked as bots? Is there a simpler heuristic (e.g., any comment at all in last 7 days, regardless of author)?

### U5: max_prs_per_run default

20 is arbitrary. Large monorepo teams merge 50+/day. Small teams merge 2.

**Sub-question**: Fixed default with manual override? Or auto-calibrate based on the previous run's count?

### U6: Retry logic scope

Which failures should be retried? 429 and network timeouts yes, but malformed output from the LLM produces the same bad result on retry.

**Sub-question**: Retry on non-zero exit code only? Or also retry when expected output files are missing?

### U7: Rollout modes

Multiple round 1 reviewers suggested gradual rollout (report-only → dry-run → apply).

**Sub-question**: The system already has `--dry-run` (skips apply) and `auto_pr.enabled: false` (skips PR creation). Is this sufficient, or do we need a formal `mode: report-only | dry-run | auto-apply` config field?

---

## Specific Questions

1. **Option A or B?** Pick one and defend it. No "it depends."
2. **Is the phasing correct?** Should anything be reordered?
3. **What are we still missing?** Round 1 caught 15+ gaps. What's left?
4. **Is the stale PR two-phase approach right?** Or is immediate close for all conditions acceptable if we add the keep-open label?
5. **Shadow comparison (U1 sub-question)** — worth the token cost for 2 weeks of data?
