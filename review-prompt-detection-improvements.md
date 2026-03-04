# Adversarial Review: Detection & Suggestion Quality Improvements

You are reviewing a plan to significantly improve the detection accuracy and suggestion quality of **autodocs** — an automated documentation drift detection tool. Your job is to find flaws, propose alternatives, identify risks, and suggest what ELSE could be done for maximum value. Be adversarial — assume the plan has blind spots.

---

## Background

autodocs is a tool that:
1. Runs daily via Claude Code headless mode on a developer's machine
2. Fetches merged PRs from GitHub/ADO/GitLab/Bitbucket
3. Gets changed files via `git diff-tree` against the local repo
4. Classifies PRs by path matching (deterministic, not LLM)
5. Maps changed packages to documentation sections using a config-defined `package_map`
6. Generates FIND/REPLACE edit suggestions with self-verification (each FIND block confirmed verbatim in the doc with line numbers)
7. Runs dual reasoning paths (Opus + Opus with chain-of-thought variation) — only AGREED suggestions are auto-applied via PR
8. Opens PRs with applied edits + uncertain suggestions in the description
9. Maintains a per-doc changelog organized by section, capturing WHY things changed from PR descriptions

**Current limitations:**
- Detection is FILE-PATH based only. It knows WHICH files changed but not WHAT changed inside them.
- The suggest prompt infers changes from PR title + file list. No actual code diffs.
- Multiple PRs affecting the same section generate separate (potentially conflicting) suggestions.
- Large refactoring PRs generate excessive noise (one alert per package).
- Deleted files aren't distinguished from modified files.
- If the doc is edited between suggestion and application, the FIND text may not match.

**Proven results:**
- 7/7 suggestions verified on Channel Pages (1200-line architecture doc, 19 sections)
- Correctly identified a mapping false positive (Site Provisioning → actually Section 5.4)
- Auto-PR #1490334 in ADO with 6 applied edits
- Auto-PR #2 on GitHub demo with 7 applied edits
- 73 BATS tests, 4-platform support (GitHub/ADO/GitLab/Bitbucket)

---

## The Plan

### Improvement 1: Diff-Aware Suggestions
Add actual code diffs to daily-report.md. For each relevant PR, run `git diff <commit>^..<commit> -- <file>` and include truncated diffs (200 lines per file). The suggest prompt reads diffs for precise FIND/REPLACE edits.

### Improvement 2: Change Type Classification (ADD/MODIFY/DELETE)
Use `git diff-tree --name-status` instead of `--name-only`. Include A/M/D change type per file. Deleted files → suggest removing doc references. Added files → CRITICAL alert for unmapped code.

### Improvement 3: Multi-PR Section Merging
When multiple PRs in the same lookback window affect the same doc section, process them as a group. Generate ONE combined suggestion referencing all PRs, not separate conflicting suggestions.

### Improvement 4: Large PR Detection
If a PR touches >50 files across many packages, classify as REFACTOR. Generate ONE LOW alert instead of 15+ individual alerts. Skip detailed suggestions.

### Improvement 5: Fuzzy FIND Matching
If exact FIND text isn't found in the doc during apply, search for the closest match. Apply with a "fuzzy matched — verify" warning. Improves resilience against concurrent doc edits.

---

## Your Review

Answer these specific questions, then provide your top 5 recommendations and suggest what ELSE could be done:

### Q1: Diff-Aware Suggestions — Value vs Cost
The plan adds ~1000 lines of code diffs to daily-report.md. This increases Claude's context by ~15K tokens per sync.
- Is this worth the accuracy improvement?
- What if a diff is 500+ lines for a single file? Should there be a per-file limit?
- Could we be smarter about WHICH files to diff (only the ones that map to doc sections, not all relevant files)?
- What about binary files, generated files, or test files in the diff — should they be filtered?

### Q2: Change Type Classification — Completeness
ADD/MODIFY/DELETE covers most cases. What about:
- RENAME (file moved from one path to another)?
- COPY (file duplicated)?
- Type change (symlink, permissions)?
Are these relevant for documentation drift? What edge cases might we miss?

### Q3: Multi-PR Section Merging — Complexity
Processing multiple PRs together for one suggestion requires the model to understand the combined intent. This is harder than processing single PRs.
- How do we ensure the combined suggestion doesn't lose context from individual PRs?
- What if the PRs were intentionally independent (e.g., one fixes a bug, another adds a feature)?
- Should we limit merging to PRs by the same author? Same day? Same branch?
- What about PRs that partially overlap (some files in common, some different)?

### Q4: Large PR Detection — Threshold
The plan uses >50 files as the threshold.
- Is 50 the right number? What about repos where normal PRs touch 30-40 files?
- Should the threshold be configurable per team?
- Instead of a hard threshold, could we detect patterns (e.g., "90% of changes are import renames" → refactoring, even if only 20 files)?
- What about split PRs — a refactoring done in 5 PRs of 20 files each?

### Q5: Fuzzy FIND Matching — Safety
Fuzzy matching introduces the risk of applying edits to the wrong location.
- What similarity threshold is safe (80%? 90%? 95%)?
- Should fuzzy matches ever be auto-applied, or always marked for manual review?
- What if the doc was intentionally rewritten (making the suggestion obsolete)?
- Could fuzzy matching accidentally match a different section entirely?

### Q6: What Else Could Be Done?
Beyond the 5 proposed improvements, what else would significantly improve autodocs for maximum value? Consider:
- Detection accuracy improvements
- Suggestion quality improvements
- User experience improvements
- Reliability and monitoring improvements
- Integration with other tools
- Novel approaches not considered in the plan

---

## Format Your Response

1. **Top 5 Recommendations** (ordered by impact, each with: change, rationale, effort estimate)
2. **Answers to Q1-Q6** (be specific and actionable)
3. **One thing you'd kill from the plan** (if anything)
4. **One thing you'd add that isn't in the plan** (highest-value addition)
5. **Overall assessment**: Is this the right direction for the project?
