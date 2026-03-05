# Review Synthesis: Production Readiness Plan

> 6 models reviewed: Gemini, Opus, Grok, GPT, MiniMax, GLM
> Date: 2026-03-05

## Universal Consensus (6/6 agree)

### 1. Do NOT apply UNMATCHED suggestions

Every reviewer cited the `createUser` example: Primary claimed default role `viewer`, Verify correctly abstained, source code says `member`. Applying UNMATCHED would have introduced a wrong edit.

> Gemini: "This reverts the system to a single-model architecture with a warning label nobody will read."
> Opus: "A false positive in a PR is worse than a false negative — it teaches reviewers to ignore autodocs PRs."

**Decision**: UNMATCHED = skip (not apply). Keep current behavior.

### 2. "No contradictions = AGREED" is too permissive

The inversion from "same claims" to "no contradictions" trades false positives for false negatives. Two models can agree on a wrong claim. Supersets can include hallucinated additions.

> Opus: "You're overfitting to n=8."
> GPT: "Without evidence-binding, you'll ship plausible-but-wrong edits."

**Decision**: Need a tighter criterion than raw "no contradictions." Multiple reviewers propose alternatives (see below).

### 3. Need observability and metrics

Zero telemetry in the current plan. No way to know if the system is working, track costs, or detect degradation.

**Decision**: Add metrics logging (AGREED/DISPUTED/UNMATCHED counts, tokens, duration per call) and a status/summary command.

### 4. Need concurrency controls

Overlapping runs (manual dispatch + cron) can corrupt state files and create duplicate PRs.

**Decision**: Add `concurrency` group in GitHub Actions workflow. sync.sh already has lock directory.

### 5. Don't commit state files to main branch

Branch protection rules block it. Creates noise commits. `[skip ci]` is fragile.

> Opus: "250 noise commits/month for a 50-person team. Developers will hate this."

**Decision**: Use orphan branch (`autodocs-state`) or GitHub Actions cache.

### 6. Stale PR auto-close needs safeguards

14-day auto-close is too aggressive. No human activity check. No dry-run.

**Decision**: Two-phase approach: label `autodocs:stale` + comment at day 14, close at day 21 only if no human activity. Add `never_close_label` override.

### 7. Need cost controls

5 Opus calls/day with no budget cap. Large lookback windows can blow up costs.

**Decision**: Add `max_prs_per_run` config with sensible default (20). Log token usage.

## Strong Consensus (4-5/6 agree)

### 8. Consider dropping dual-model verification for v1

Multiple reviewers note that the original 7/7 results were single-model, and dual-model is currently rejecting 75% of correct suggestions.

> Opus: "Drop dual-model for v1. Ship single-model with self-verification. Track error rate. If >10% wrong, re-add verification — but as deterministic fact extraction."
> Grok: "Drop it. Single-model was accurate; dual adds complexity/noise."
> Gemini: "Use the Verified output as the primary."

**Decision**: Seriously consider this. The architecture is "never auto-edit, always PR" — humans review before merge. Self-verification (FIND text confirmed verbatim) is already a mechanical quality gate.

### 9. processed-prs.json is overcomplicated

Multiple reviewers prefer a simpler `last-successful-run` timestamp.

> Opus: "5 lines replacing an entire record-processed operation, JSON state file, prune logic, and filtering prompt addition."
> GLM: "Store one timestamp instead of a growing list."

**Decision**: Use timestamp approach. Simpler, no pruning, no state file management.

### 10. PR discovery should use durable markers, not title search

Title search (`"autodocs in:title"`) is fragile. Manual PRs can pollute. Title edits break it.

> GPT: "Add label `autodocs` and branch prefix `autodocs/` in apply step. Embed hidden metadata in PR body."
> MiniMax: "Search by author or label, not just title."

**Decision**: Use branch prefix (`autodocs/`) as primary discovery criterion (already exists). Add `autodocs` label. Embed metadata comment in PR body.

### 11. Need retry/error handling

No retry logic for transient API failures (429, network timeout). Pipeline silently fails.

**Decision**: Add simple retry with backoff around Claude calls. Post GitHub issue or notification on pipeline failure.

### 12. Prompt injection risk from PR content

PR descriptions and review comments are user-authored and passed to LLM calls. Malicious content could manipulate outputs.

> Opus: "A malicious PR description could contain: 'Ignore all previous instructions.'"

**Decision**: Include PR content in clearly-delimited data blocks with explicit "treat as untrusted data" instructions.

## Notable Divergent Ideas

### GLM: Make Verify adversarial instead of parallel

Instead of both models generating suggestions independently then comparing, have Verify critique Primary's suggestions:

```
Primary → generates suggestions
Verify → receives Primary's suggestions + source code, asked to find errors
```

This eliminates comparison logic entirely. No DISPUTED/UNMATCHED categories. Just CORRECT/INCORRECT/UNCERTAIN verdicts per suggestion.

**Assessment**: This is architecturally cleaner. Worth serious consideration if we keep dual-model.

### GPT: Evidence-binding

Each atomic claim in a suggestion must reference a supporting snippet from the diff, source code, or PR description. Claims without evidence are dropped.

**Assessment**: Elegant but adds significant prompt complexity. May be Phase 2.

### Opus: Deterministic fact extraction in Python

Move comparison out of the LLM into Python. Extract structured facts (function names, parameters, defaults) via regex and compare deterministically.

**Assessment**: Consistent with the project's philosophy (deterministic Python > LLM for algorithmic tasks). But requires parsing suggestion prose, which is harder than parsing structured data.

### Gemini: Apply the intersection, not the superset

When both models agree on some facts but differ on others, apply only the common ground.

**Assessment**: Conservative and safe. Could result in incomplete suggestions, but "correct and incomplete" beats "complete and wrong."

## Revised Priority Based on Reviews

```
Phase 0 (before any deployment):
  - Observability: metrics.jsonl + status command
  - Cost controls: max_prs_per_run, token logging
  - Concurrency: Actions concurrency group

Phase 1 (core fixes):
  - Decision on dual-model: keep (with adversarial verify) or drop for v1
  - Feedback bootstrap with durable markers (label + branch prefix)
  - Lookback fix via last-successful-run timestamp
  - Stale PR management with 2-phase (warn → close) + activity check

Phase 2 (CI):
  - GitHub Actions workflow with orphan state branch
  - Retry/backoff for API calls
  - Failure notifications

Phase 3 (hardening):
  - Prompt injection mitigation
  - Gradual rollout controls
  - Config drift nudge
```

## The Big Decision: Dual-Model Verification

The reviews surface a fundamental question that should be resolved before implementing anything:

**Option A: Drop dual-model for v1.**
- Ship single-model + self-verification (FIND text confirmed verbatim)
- Track error rate via feedback loop
- If error rate >10% on merged PRs, add verification back
- Eliminates Call 3v, comparison logic in Call 4, verify-variation.md
- Saves ~20% token cost per run
- Risk: some wrong suggestions in PRs (but humans review before merge)

**Option B: Keep dual-model, make Verify adversarial.**
- Verify receives Primary's suggestions and critiques them (CORRECT/INCORRECT/UNCERTAIN)
- No comparison logic needed — just check verdicts
- INCORRECT = skip. UNCERTAIN = flag for review. CORRECT = apply.
- Cleaner architecture, clearer signal
- Still costs an extra LLM call

**Option C: Keep dual-model, fix comparison logic.**
- The current plan (with UNMATCHED=skip, tighter contradiction definition)
- Granularity normalization in verify-variation.md
- Most complex, least validated
- All 6 reviewers expressed concern about this approach

Recommendation from reviews: Option A (4 models) or Option B (GLM, partially Gemini).
Nobody fully endorses Option C as written.
