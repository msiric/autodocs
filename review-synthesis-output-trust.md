# Review Synthesis: Output Trust (Round 3)

> 5 models reviewed: Gemini, Opus, Grok, GPT, MiniMax/GLM (shared response)
> Date: 2026-03-05

## The Critical Reframe

Gemini nailed the core insight: **"The root cause is not lack of verification. The root cause is Context Starvation."** The LLM made a wrong decision because it literally did not see the code that reverted the change. Fixing only the output (verification) treats the symptom. Fixing the input (what the LLM sees) treats the cause.

Opus formalized this: "Defense in depth means both, but lead with input fidelity."

## Consensus on the 8 Questions

### Q1: Regex vs AST — Start regex, upgrade later
**5/5 agree**: Regex now, tree-sitter later if gaps appear. The key insight from multiple reviewers: don't try to parse code structure — just check if specific values exist in the source file. Symbol existence checking (grep) is simpler and more reliable than semantic extraction (regex/AST).

### Q2: REPLACE_MISMATCH — Block contradictions, REVIEW unknowns
**5/5 agree on blocking.** The nuance from Opus and GPT:
- **MISMATCH** (value in REPLACE contradicts source) → **BLOCK**
- **UNVERIFIED** (can't determine if correct) → **REVIEW / Draft PR**
- **EVIDENCED** (value confirmed in source/diff) → **auto-apply**

This three-tier model replaces the binary pass/fail.

### Q3: Diff budget — Targeted extraction, not bigger budget
**Divergence resolved.** Gemini says 500 for mapped files. Grok says 300. GPT/MiniMax/GLM say keep 150 but change the strategy. Opus proposes the cleanest solution: **targeted diffs** — full diff for mapped files, stat-only for unmapped. This inverts the model from "budget across all files" to "full context for relevant files."

**Consensus approach**: Prioritize by section relevance (files mapped in package_map get full diffs first), not alphabetical. This would have caught the `users.ts` revert because it's a mapped file.

### Q4: Changelog — Supersession annotation, narrative-only trust
**5/5 agree**: Option (b) supersession. Additionally, GPT's framing is the sharpest: "Stop using changelog text as authority for values. It remains narrative only." The suggest prompt should never copy values from changelog entries — only use them to identify which sections need attention.

### Q5: Description→Suggestion cascade — Feed raw data to Suggest
**5/5 agree**: The Suggest prompt should receive structured deterministic context (drift-context.json, relevant diffs, current-state.json) rather than drift-report.md prose. The drift report becomes human-facing only.

### Q6: What we missed
New gaps identified:
- **Unicode normalization** (Opus): smart quotes vs straight quotes in FIND/REPLACE matching
- **Test/fixture contamination** (GPT): verification might match test files instead of production code
- **Absent evidence** (Opus): missing information (endpoint not documented) isn't caught by any verification
- **Comment contamination** (GPT): strip code comments before regex verification

### Q7: Layer 2 overengineered? — No, Layer 1 alone is insufficient
**5/5 agree**: Prompt instructions alone won't work because the LLM can't verify against data it doesn't have (truncated diffs). Layer 2 is the minimum viable safety net.

### Q8: Priority — Top 3

| Rank | Gemini | Opus | Grok | GPT/MiniMax/GLM |
|------|--------|------|------|-----------------|
| P1 | Context budget (targeted diffs) | Targeted diffs | Diff prioritization | REPLACE verifier + gating |
| P2 | Changelog supersession | REPLACE verification | Current-state extraction | Decouple Suggest from prose |
| P3 | Symbol existence block | Changelog supersession | REPLACE verification | Current-state extractor |

**Synthesis**: Two camps. Gemini/Opus prioritize **fixing the input** (targeted diffs, better context). GPT/MiniMax/GLM prioritize **verifying the output** (REPLACE checking, blocking). Grok is in between.

**The right answer is both, in this order:**
1. **Targeted diffs for mapped files** (input fix — prevents the error from being generated)
2. **REPLACE value verification with 3-tier gating** (output fix — catches what input fix misses)
3. **Changelog supersession + trust downgrade** (prevents poisoning feedback loop)

## Final Implementation Plan

### Priority 1: Targeted diff extraction

Replace the flat 150-line budget with relevance-based allocation:
- Files mapped in `package_map` → full diff (no truncation)
- Files in `relevant_paths` but unmapped → 50-line summary
- All other files → stat line only (`+20 -5 src/utils/helpers.ts`)

Add to sync-prompt.md diff instructions. This is the root cause fix — the `users.ts` role revert would have been included because `api` is a mapped package.

### Priority 2: REPLACE value verification

Extend `verify_finds()` in drift-helper.py:
1. Parse REPLACE text for backtick identifiers and quoted literals
2. For each value, search the mapped source file(s) + diff content
3. Three outcomes: EVIDENCED / MISMATCH / UNVERIFIED
4. MISMATCH → block. UNVERIFIED → REVIEW. EVIDENCED → auto-apply.

Strip comments from source before searching. Exclude test directories.

### Priority 3: Changelog trust downgrade + supersession

Two changes:
1. **Suggest prompt**: "Use changelog only to identify topics/sections. Never copy values from changelog entries — verify against diff or current source."
2. **suggest-dedup**: If a changelog entry's files were modified by a later PR, annotate as `[SUPERSEDED CANDIDATE]` in suggest-context.json.

### Deferred

- **Current-state.json (regex extraction)**: Deferred. REPLACE verification achieves the same goal (catching wrong values) without needing parsed state. The symbol-existence approach (search source text) is simpler and more reliable.
- **Tree-sitter AST**: Phase 4+ if regex verification has coverage gaps.
- **Post-apply diff verification (3b)**: Phase 3. Low probability of failure.
- **PR classification verification (3a)**: Low priority. Misclassification doesn't create wrong docs.
