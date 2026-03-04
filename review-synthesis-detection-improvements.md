# Review Synthesis: Detection Improvements (6 SOTA Models)

## Reviewers
Gemini, Opus, Grok, GPT, MiniMax, GLM

---

## Unanimous Consensus (6/6)

### 1. Kill Fuzzy FIND Matching — Replace with Stale Suggestion Detection
Every model recommends killing or severely restricting fuzzy matching. The reasoning is consistent: it undermines the core trust model (verified verbatim FIND blocks). A 90% similarity match can hit an adjacent paragraph or different section.

- **Gemini:** "Critical No-Go on auto-applying fuzzy matches"
- **Opus:** "I'd kill this feature entirely. The core trust model rests on verified FIND blocks."
- **GPT:** "Kill blind fuzzy. Replace with context-anchored patching and HEAD re-verification."
- **GLM:** "Replace with Stale Suggestion Detection and Reporting"

**Decision:** Kill Improvement 5. Replace with stale detection: if FIND text not found, check if section was modified after suggestion was generated. Report as EXPIRED with context.

### 2. Add RENAME Detection (git diff-tree -M)
All 6 flag RENAME as the biggest gap in Change Type Classification. Renames are the most common cause of doc staleness that isn't a logic change — docs reference old file paths.

- **Decision:** Use `git diff-tree -M -r --name-status` instead of `--name-only`. Handle `R` status as "update references" not "delete + add."

### 3. Smart Diff Filtering, Not Blind Truncation
All 6 reject "first 200 lines per file." The change might be at line 850.

- **Gemini:** "Use `git diff -U5` and filter out tests. Fatal for large files where change is at line 850."
- **Opus:** "Replace with hunk-header extraction. Use `-U3` with total token budget per PR (~150 lines)."
- **GPT:** "Replace with deterministic change events plus minimal targeted hunks."

**Decision:** Use `git diff -U3` (3 lines context), filter test/generated/binary files, cap at 150 lines per PR total. Only diff files that map to doc sections.

### 4. Adaptive Large PR Detection (Not Hard Threshold)
All 6 say >50 files is arbitrary and wrong for most repos.

- **Opus:** "Replace with 3 × median(PR size last 30 days)"
- **Grok:** "Pattern-based: if >70% of lines are renames/imports → refactoring"
- **GPT:** "Use path entropy and rename ratios, not just file count"

**Decision:** Content-based detection: if >80% of diff hunks are single-line import/rename changes → REFACTOR classification regardless of file count. Plus configurable threshold as fallback.

---

## Strong Consensus (5/6)

### 5. Sequential Multi-PR Handling + Conflict Detection (Not Merging)
- **Opus:** "Don't try to merge. Sort chronologically, generate sequentially, detect overlap."
- **GPT:** "Merge events deterministically, detect conflicts. If conflicts → escalate."
- **MiniMax:** "Generate individual suggestions, flag when two touch same doc lines."
- **GLM:** "Kill multi-PR merging as currently specified. Implement conflict detection instead."

**Decision:** Sequential processing + conflict detection. If suggestion N's FIND block overlaps with suggestion N-1's REPLACE block → flag as CONFLICT, don't auto-apply either.

### 6. Confidence Scoring (Not Just Binary AGREE/DISAGREE)
- **MiniMax:** "Confidence score based on FIND uniqueness, diff clarity, mapping confidence, verification agreement."
- **GLM:** "Binary decisions too brittle. Humans need nuance."
- **Opus:** "CERTAIN (identical), HIGH (same intent, minor wording), LOW (different), CONFLICT (contradictory)."

**Decision:** Defer to post-implementation. Current AGREE/DISAGREE + CONFIDENT/REVIEW is sufficient for v1. Add scoring as a refinement.

---

## Top Novel Ideas (Not in Original Plan)

### 7. PR Review Comment Mining (Opus)
Parse review threads for keywords: "doc", "documentation", "breaking", "migration", "deprecat." If found → boost PR classification to YES. Reviewers are already doing drift detection manually.
**Decision:** High value, defer to next iteration.

### 8. Revert/Rollback Detection (GLM)
If a PR reverts a previous PR that caused drift, cancel the pending suggestion instead of generating a new one.
**Decision:** Good idea, defer to next iteration.

### 9. Stale Suggestion Detection (Opus, GLM)
Instead of fuzzy matching: check git blame on the target section. If modified after suggestion was generated → report as EXPIRED.
**Decision:** Implement now (replaces fuzzy matching).

### 10. Public vs Private Filtering (Gemini)
Only flag changes to exported/public API surface. Internal changes rarely need doc updates.
**Decision:** Defer. Requires language-aware parsing (autodocs-engine integration).

---

## Revised Priority Order

| Priority | Improvement | Source |
|----------|------------|--------|
| 1 | Change type classification (A/M/D/**R**) with rename detection | All 6 |
| 2 | Smart diff inclusion (hunk-based, filtered, per-PR budget) | All 6 |
| 3 | Kill fuzzy matching → stale suggestion detection | All 6 |
| 4 | Adaptive large PR detection (pattern-based) | All 6 |
| 5 | Sequential multi-PR handling + conflict detection | 5/6 |
| — | ~~Fuzzy FIND matching~~ | **Killed by all 6** |
| — | ~~Multi-PR merging (intent synthesis)~~ | **Replaced by conflict detection** |

---

## Rejected from Reviews (YAGNI for now)

| Suggestion | Source | Why deferred |
|------------|--------|-------------|
| Language-aware AST analysis | GPT, Gemini | Requires autodocs-engine integration (Phase 3) |
| Confidence scoring (1-5 scale) | MiniMax, GLM | Current AGREE/DISAGREE is sufficient for v1 |
| PR review comment mining | Opus | High value but separate feature, not detection improvement |
| Revert detection | GLM | Edge case, can add later |
| Suggestion rejection learning | GLM, MiniMax | Needs feedback loop infrastructure, post-launch |
| Event ledger / change events | GPT | Over-engineered for current architecture |
| Doc-code contradiction detection | MiniMax | Hard problem, requires semantic understanding beyond diffs |
