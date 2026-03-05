# Follow-up: Output Trust Implementation Gaps

## Context

We're proceeding with the 3 priorities you recommended in round 3:
1. Targeted diffs for mapped files (input fix)
2. REPLACE value verification with 3-tier gating (output fix)
3. Changelog trust downgrade + supersession (poisoning fix)

Before implementing, we want your input on specific gaps where our confidence is lowest. We've assessed the expected error rates after implementation:

| Error type | Expected rate | Why |
|-----------|---------------|-----|
| Literal value errors (wrong defaults, wrong function names) | ~0% | REPLACE verification catches mechanically |
| Behavioral interpretation errors (wrong description of code behavior) | 5-10% | Better diffs help, but verification can't check "retries 3 times" |
| Correct values in wrong context (right name, wrong attribution) | Unknown | Both values exist in source; verifier sees both as EVIDENCED |
| Omissions (correct but incomplete suggestions) | 10-15% | Inherent to generative systems |

We're confident at 8/10 for literal value errors, but only 4-6/10 for the rest. Help us close those gaps or confirm they're acceptable limitations.

## 5 Specific Questions

### Q1: Behavioral claims that don't map to literals

Example: The REPLACE text says "The endpoint retries 3 times with exponential backoff." The code actually does linear backoff with 5 retries. But `"3"`, `"exponential"`, `"5"`, and `"linear"` don't appear as string literals — they're embedded in logic (`for (let i = 0; i < 5; i++)` and `delay * 2` vs `delay * i`).

Our REPLACE verifier marks these UNVERIFIED (can't confirm or deny). The suggestion gets REVIEW confidence instead of auto-apply.

**Is UNVERIFIED/REVIEW the right fallback for behavioral claims? Or is there a practical way to catch behavioral errors without AST-level code understanding?**

### Q2: Correct values in wrong context

Example: The REPLACE text says "the `createUser` function requires the `admin` role." Both `createUser` and `admin` exist in the source. The verifier marks both as EVIDENCED. But the actual code is `requireJWT(req, 'admin')` on the `deleteUser` function, not `createUser`. The `createUser` function uses `requirePermission(req, 'users:write')`.

The verifier checks existence in the file but not proximity/association between values.

**How do we scope verification to the right context? Options we see:**
- (a) Check if values co-occur within N lines of each other in the source (proximity heuristic)
- (b) Only verify against the specific function body, not the whole file (requires function boundary detection)
- (c) Accept this as a limitation — it's rare enough that REVIEW confidence + human review catches it

### Q3: The UNVERIFIED rate

If our regex extractors miss too many patterns (destructured defaults, arrow functions, computed values), most suggestions end up UNVERIFIED and need human review. The system becomes effectively manual.

**What's the minimum set of extractors needed to keep the EVIDENCED rate above 70%?** Our current plan covers:
- Backtick identifiers (`` `functionName` ``)
- Quoted string literals (`'member'`, `"viewer"`)
- File paths (`src/auth/rbac.ts`)

Is this enough? What patterns are we missing that would cause the most UNVERIFIED results in practice?

### Q4: Omissions

A suggestion correctly updates 4 out of 5 endpoints in a table. The 5th endpoint (newly added) is simply not mentioned. Everything the suggestion says is correct — it just doesn't say enough.

**Is this solvable, or is it an inherent limitation we document and accept?**

One idea: the `current-state.json` extractor could list all exports from mapped files. If the doc section references N exports and the source has N+1, flag "potential missing coverage." But this requires understanding what the doc *should* contain, not just what the suggestion claims.

### Q5: Should the suggest prompt read the actual source file?

This is the question we're most uncertain about. Multiple approaches are on the table:

**Option A: Regex extraction → current-state.json → LLM reads JSON**
- Python extracts function signatures, defaults, exports
- LLM reads structured JSON as ground truth
- Pro: Deterministic, small context
- Con: Regex misses patterns, maintenance burden

**Option B: LLM reads the actual source file directly**
- For each flagged section, include the current content of the primary mapped source file in the suggest prompt context
- Pro: Complete ground truth, no extraction needed, catches behavioral claims too
- Con: ~1k tokens per file (5 mapped files = 5k extra), LLM must parse code itself

**Option C: Both — extract state AND include source**
- Regex extraction for deterministic verification (blocking gate)
- Source file for LLM context (better suggestions)
- Pro: Defense in depth
- Con: Most complex, highest token cost

**Option D: Targeted source snippets (not full file)**
- For each value referenced in a suggestion, extract the surrounding 10-20 lines from the source file
- Pro: Focused, small context, shows the actual code around each claim
- Con: Requires knowing which values to look up (chicken-and-egg with verification)

**Which option do you recommend, and why? If Option B, does this make the regex extraction (current-state.json) unnecessary?**

## What We're NOT Asking About

- The 3 priorities are decided. We're not revisiting targeted diffs, REPLACE verification, or changelog downgrade.
- The implementation order is decided (1→2→3).
- The architectural decisions from rounds 1-2 are settled (single-model, shadow mode, orphan state branch, etc.)

We only want guidance on the 5 questions above to ensure we implement the verification layer correctly.
