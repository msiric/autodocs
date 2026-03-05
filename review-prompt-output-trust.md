# Adversarial Review: Output Trust Gap

## Context

This is round 3 of adversarial review for **autodocs**, an automated documentation drift detection tool. Previous rounds resolved verification architecture (dropped dual-model, added shadow mode), feedback bootstrapping, stale PR management, and CI deployment.

**This round addresses a newly discovered systemic problem: the system verifies LLM inputs but not outputs.**

## Your Role

You reviewed the previous plan (production readiness v2). All those decisions are settled. Focus entirely on the **output trust gap** — the problem of REPLACE text correctness, changelog poisoning, and the 20 unverified trust points identified below.

Be concrete. If you recommend an approach, specify how it works, what it catches, and what it misses. No hand-waving.

---

## The Problem We Found (with evidence)

### The concrete failure

A factual error appeared in 2 out of 3 autodocs PRs on our demo repo:
- The suggestion says: "New users are assigned the `viewer` role by default"
- The source code says: `role: data.role ?? 'member'`
- The error was auto-applied because FIND text verification passed (the FIND text was correct — it was the REPLACE text that was wrong)

### Root cause chain

1. PR #3 changed default role `'member'` → `'viewer'` (code change)
2. Autodocs changelog correctly recorded: "Default role changed from member to viewer"
3. PR #5 changed it back `'viewer'` → `'member'` (code change)
4. PR #5 had 614 lines of diff; the 150-line budget truncated `users.ts` (alphabetically last). The role revert was never included in the diff the LLM saw.
5. PR #5's changelog entry didn't mention the role revert (focused on error envelopes, rate limiting, other changes)
6. Future runs read the changelog → see "default: viewer" → no contradicting entry → generate suggestions with wrong value

**The LLM isn't hallucinating.** It's correctly reading an incomplete historical record and making a reasonable but wrong inference. The failure is systemic: the system feeds the LLM stale context and has no mechanism to verify the output against ground truth.

### The asymmetry

| What | Verified? | Mechanism |
|------|-----------|-----------|
| FIND text exists in doc | **Yes** | Python `verify_finds()` — deterministic |
| REPLACE text is factually correct | **No** | Nothing |
| Changelog "Changed" is accurate | **No** | Nothing |
| PR classification (YES/NO) is correct | **No** | LLM told to be deterministic, but not checked |

## The Full Audit (20 Trust Points)

A systematic audit identified 20 places where LLM output is consumed without verification. The two critical ones:

**C8: REPLACE text correctness** (Critical, High frequency)
Function names, default values, parameter types, error codes, endpoint paths in REPLACE text are never checked against source code. This is the edit that lands in the PR.

**C18: Description→suggestion cascade** (Critical, Medium frequency)
Call 2 (drift) generates "What Changed" descriptions from PR data. Call 3 (suggest) reads those descriptions and generates FIND/REPLACE. Two layers of unverified LLM inference compound errors. A wrong description in Call 2 produces a wrong suggestion in Call 3.

Additional high-severity gaps: PR classification (C1), changelog accuracy (C9/C10), faithful edit application (C14), filter compliance (C16), changelog poisoning loop (C19).

## Our Proposed Fix (3 Layers)

### Layer 1: Prompt-level (zero code, immediate)

**1a.** Add changelog staleness warning to suggest prompt: "Changelog entries reflect what was true AT THE TIME. Later PRs may have reverted values. If you reference a specific value from a changelog entry, verify against the diff. If no diff available, set confidence to REVIEW."

**1b.** Change diff prioritization from alphabetical to by change magnitude (most hunks first). This would have caught the users.ts role revert which was truncated because it came last alphabetically.

**1c.** Add source code verification instruction: "After generating REPLACE text, verify every concrete value against the source diff. If the diff doesn't contain the value, read the current source file."

### Layer 2: Deterministic Python extraction (medium effort)

**2a.** `extract-state` operation — parse source files referenced by alerts, extract function signatures, defaults, exports. Write `current-state.json`. Suggest prompt reads this as ground truth.

Example output:
```json
{
  "src/api/users.ts": {
    "functions": [
      {"name": "createUser", "defaults": {"role": "member", "status": "pending"}}
    ]
  }
}
```

Regex-based extraction (not AST): `export function (\w+)`, `?? '(\w+)'`, etc.

**2b.** Extend `verify_finds()` to also verify REPLACE text: extract backtick-wrapped identifiers and quoted strings from REPLACE text, check if they exist in the source file. Flag mismatches as `REPLACE_MISMATCH`.

**2c.** Changelog supersession detection: when later PRs touch the same files as a changelog entry, add a warning to suggest-context.json so the LLM treats the old entry with skepticism.

### Layer 3: Deterministic post-processing (higher effort)

**3a.** PR classification verification: Python re-runs path matching independently, compares against LLM classification.

**3b.** Post-apply diff verification: after Call 4 commits, verify the git diff matches expected FIND/REPLACE operations exactly.

## Questions for Reviewers

1. **Is regex-based extraction (2a) reliable enough for current-state.json?** TypeScript generics, decorators, overloads make regex fragile. Does this need tree-sitter? Or is 80% coverage acceptable since it's supplementary context, not the sole source of truth?

2. **Should REPLACE_MISMATCH (2b) block the suggestion or just flag it?** Blocking prevents wrong edits but may over-reject if the REPLACE text uses different wording than the source code. Flagging leaves the decision to the LLM (which is the thing we're trying to not trust).

3. **Is 150 lines the right diff budget?** Increasing to 300 doubles context cost. But 100% of feature PRs in our demo repo exceeded 150 lines, and the truncation directly caused the failure. What's the right trade-off?

4. **Should the changelog have a TTL or supersession mechanism?** Options: (a) mark old entries `[HISTORICAL]` after N days, (b) annotate when later PRs touch the same files, (c) keep append-only and fix it downstream. Which is best?

5. **Is the description→suggestion cascade (C18) fixable?** Should the suggest prompt read raw data (daily-report.md) instead of processed drift output? Or is the cascade inherent to the architecture?

6. **What did we miss?** Are there failure modes in the 20-point audit that we're underweighting? Are there trust points we didn't identify?

7. **Is Layer 2 overengineered?** The prompt fixes (Layer 1) might be sufficient if the LLM follows the "verify against diff, else REVIEW" instruction reliably. Is the Python extraction (Layer 2) worth the complexity? Or will the LLM ignore the instruction under context pressure?

8. **Priority: which 3 things should we implement first?** Given finite time and the goal of maximum correctness improvement per effort.
