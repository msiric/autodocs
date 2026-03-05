# Review Synthesis: Feedback Loop (6 SOTA Models)

## Reviewers
Gemini, Opus, Grok, GPT, MiniMax, GLM

---

## Unanimous Consensus (6/6)

### 1. Kill per-suggestion diff comparison as specified
Every model says the Layer 2 diff comparison is over-engineered and fragile. Squash merges, concurrent edits, semantic equivalence, and multi-commit sequences make it nearly impossible to reliably attribute outcomes to specific suggestions.

- **Gemini:** "Use semantic matching via cheaper LLM, not literal diff"
- **Opus:** "The per-suggestion diff comparison is the hardest part and the plan dramatically underestimates it"
- **GPT:** "You cannot reliably classify ACCEPTED/MODIFIED/REJECTED without stable anchors"
- **GLM:** "Just check if FIND block exists in merged doc — 80% of the signal for 20% of the complexity"

**Decision:** Replace with simplified FIND-block check: if FIND text still in doc → REJECTED. If gone + REPLACE text found → ACCEPTED. If gone + different text → MODIFIED. Simple, implementable, honest about uncertainty.

### 2. Replace "5 most recent" few-shot with diverse curation
All models warn against recency-based selection. Risk of temporal clustering, operation type bias, and self-reinforcement.

- **Opus:** "MODIFIED suggestions (where reviewer changed wording) are the ONLY examples that teach something new"
- **Gemini:** "Maintain one Gold Standard per category, not by recency"
- **GPT:** "Retrieval-based selection with diversity constraints"

**Decision:** Stratified selection: 1 REPLACE example, 1 INSERT example, 1 deletion example. Prefer reviewer-modified suggestions (the delta is the signal). Minimum 3, maximum 5 examples. Curate manually initially.

### 3. Minimum sample size before accuracy affects confidence
All models say n=1-2 data points are meaningless. Recommend n≥5-10 minimum with statistical smoothing.

- **Opus:** "Bayesian smoothing with α=3, β=1 prior. Hierarchical pooling: section → doc → global."
- **GPT:** "Wilson lower bound, n_min=8, hierarchical fallback"
- **GLM:** "Minimum 5, fallback to doc-level then global"

**Decision:** n≥10 minimum before affecting confidence. Use hierarchical fallback (section → doc → global). Bayesian smoothing with conservative prior (75% acceptance baseline).

### 4. Kill automated anti-pattern generation
All models say LLM-inferred rejection reasons are dangerous. False anti-patterns suppress future good suggestions.

- **Gemini:** "KILL automated anti-pattern generation. Model poisoning risk."
- **Opus:** "Having an LLM infer WHY a suggestion was rejected from a diff is the most dangerous part"
- **MiniMax:** "LLM will hallucinate rejection reasons"

**Decision:** Human-curated anti-patterns only. Add via CLI subcommand (`autodocs feedback add-antipattern`). Maximum 10 entries. No auto-generation.

### 5. Make feedback checking conditional (not every day)
All models say running a Claude call daily just to check PR states is wasteful.

**Decision:** Check via bash (gh pr view) in the wrapper script, no LLM call. Only invoke Claude for outcome analysis when a PR state has actually changed.

---

## Strong Consensus (5/6)

### 6. Kill Layer 3 (PR comment parsing)
- **Opus:** "Kill entirely. Parsing comments for 'LGTM' or 'wrong' is brittle NLP on tiny text samples."
- Comments are noisy, platform-specific, often about things other than suggestion quality.

**Decision:** Defer indefinitely. PR merge state is sufficient signal.

### 7. Ship tracking NOW, defer learning LATER
- **Opus:** "Build the telescope before the autopilot. You have 14 verified suggestions and zero rejections — nothing to learn from yet."
- Track everything from day 1. Wire feedback to prompts only after n≥20 outcomes.

**Decision:** Phase 1 = tracking only (no prompt changes). Phase 2 = learning (after sufficient data).

---

## Top Novel Ideas

### 8. Suggestion deduplication (Opus)
Before generating new suggestions, check if the same section already has a pending autodocs PR. Prevents duplicate PRs and corrupted feedback data.

**Decision:** Implement in Phase 1. Simple: load open-prs.json, skip sections with pending suggestions.

### 9. Simplified FIND-block check (GLM)
Instead of full diff comparison:
```python
if find_text in merged_doc:
    return "REJECTED"  # Original text still there, suggestion not applied
elif replace_text in merged_doc:
    return "ACCEPTED"  # Our replacement text is there
else:
    return "MODIFIED"  # Section changed but differently
```

**Decision:** Implement as the per-suggestion outcome classifier. 80% accuracy, 20% complexity.

### 10. Confidence calibration (Opus)
Track whether CONFIDENT suggestions are actually accepted more than REVIEW ones. If CONFIDENT is only accepted 70% of the time, the system is overconfident.

**Decision:** Track in outcomes.json. Surface in weekly digest. Adjust thresholds based on data.

---

## Revised Implementation Plan

| Phase | What | When |
|-------|------|------|
| **Phase 1: Track** | PR-level outcomes (bash, no LLM), open-prs.json, suggestion dedup, simplified FIND-block check | Now |
| **Phase 2: Learn** | Diverse few-shot examples (after n≥20), per-section accuracy with n≥10 minimum + Bayesian smoothing | After 3-4 weeks |
| **Phase 3: Curate** | Human-curated anti-patterns via CLI, weekly digest, confidence calibration | After 6-8 weeks |
| **Defer** | PR comment parsing, automated anti-patterns, prompt evolution/A/B testing, reviewer identity tracking | Future |

---

## What Was Killed

| Proposal | Killed By | Replacement |
|----------|-----------|-------------|
| Per-suggestion diff comparison (full) | All 6 | Simplified FIND-block check |
| "5 most recent" few-shot | All 6 | Stratified diverse curation |
| Automated anti-pattern generation | All 6 | Human-curated via CLI (max 10) |
| Layer 3 (PR comment parsing) | 5/6 | Deferred indefinitely |
| Unconditional daily Call 0 | All 6 | Conditional bash check, LLM only when needed |
