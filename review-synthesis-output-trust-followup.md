# Review Synthesis: Output Trust Follow-up (Round 4)

> 5 models reviewed: Gemini, Opus, Grok, GPT, MiniMax/GLM
> Date: 2026-03-05

## The Big Question: Q5 (Source File Access)

This was the fork-in-the-road question. The models split into two camps:

**Camp 1: Option B — LLM reads source directly (Gemini, MiniMax)**
- Skip current-state.json entirely
- Include full mapped source files (~1k tokens each)
- Use simple literal verification on REPLACE output
- "Context is King. The LLM cannot document users.ts if it hasn't seen users.ts."
- "Option A (regex extraction) is a maintenance nightmare. Stop building a static analysis engine."

**Camp 2: Option C/D — Both extraction AND source snippets (Opus, GPT, GLM)**
- Keep current-state.json for deterministic gating
- Add targeted source snippets (function bodies, not full files)
- "Option B does NOT eliminate the need for REPLACE verification. The LLM having source reduces error rate but doesn't guarantee correctness."
- "Use both: extractors to gate, snippets to improve quality"

**Grok**: Sided with Option C (both) but recommended tree-sitter for extraction.

### My assessment

Gemini's argument is the most compelling. The entire problem we're solving exists because we tried to give the LLM lossy abstractions (truncated diffs, changelog summaries) instead of the actual source code. Adding another lossy abstraction (regex-extracted JSON) adds complexity without solving the fundamental issue.

**But Opus's counterpoint is valid**: the LLM reading source files improves *generation quality*, but the deterministic REPLACE verifier is the *safety net*. They operate at different layers. Dropping the verifier means trusting the LLM to read code correctly 100% of the time — which is exactly the trust model we're trying to move away from.

**Resolution**: Include source files (Option B) AND keep the simple literal verifier. Skip current-state.json regex extraction. The verifier uses raw source text search, not parsed JSON.

## Consensus on All 5 Questions

| Q | Answer | Agreement |
|---|--------|-----------|
| Q1: Behavioral claims | **UNVERIFIED/REVIEW is correct.** Source in context reduces these. Accept as limitation. | 5/5 |
| Q2: Wrong context | **Function-scoped verification.** Extract function boundaries (brace counting), verify claims within scope. Fall back to file-level for unsupported languages. | 4/5 (Gemini says proximity is fine) |
| Q3: UNVERIFIED rate | **Add: HTTP methods, endpoint paths, numeric literals, error codes.** Current 3 extractors → 7. Target: 70%+ EVIDENCED. | 5/5 |
| Q4: Omissions | **Inherent limitation.** Flag coverage gaps (exports vs doc mentions) as advisory warning in PR body. Don't block. | 5/5 |
| Q5: Source access | **Include source files + keep literal verifier.** Skip regex extraction (current-state.json). | Synthesized |

## Refined Implementation Plan

### Priority 1: Targeted diffs for mapped files
No change from round 3. Prioritize by section relevance, full diff for mapped files.

### Priority 1.5 (NEW): Include mapped source files in suggest context
- For each flagged section, include the current content of the primary mapped source file
- Add to suggest-prompt.md: "These source files are the CURRENT state. When any changelog or drift description contradicts what you see here, the source file is authoritative."
- Cost: ~1k tokens per file, 2-5 files per run = $0.05-0.10
- This is the highest-leverage single change — it eliminates context starvation

### Priority 2: REPLACE value verification
Simplified from round 3 plan:
- Extract backtick identifiers, quoted literals, file paths, HTTP methods, endpoint paths, numeric literals, error codes from REPLACE text
- Search raw source file text (no regex-parsed JSON) + diff content
- Function-scoped verification: extract function boundaries via brace counting, verify co-referenced values within same function body
- Three outcomes: EVIDENCED / MISMATCH / UNVERIFIED
- MISMATCH → block. Zero EVIDENCED → REVIEW. Any EVIDENCED + zero MISMATCH → auto-apply.

### Priority 3: Changelog trust downgrade + supersession
No change from round 3. Changelog is narrative-only. Add supersession annotations.

### What we're NOT building
- current-state.json (regex extraction) — replaced by source file inclusion
- tree-sitter / AST parsing — deferred unless regex verification has coverage gaps
- Behavioral claim verification — accept UNVERIFIED/REVIEW
- Omission auto-detection — flag as advisory, don't gate
