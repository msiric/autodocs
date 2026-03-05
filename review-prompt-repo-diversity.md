# Adversarial Review: Universal Repo & Doc Compatibility

You are reviewing a plan to make **autodocs** — an automated documentation drift detection tool — work well across the full spectrum of repositories, from small 10-file Express APIs to massive monorepos with 500+ packages.

Your job is to find flaws, propose alternatives, identify risks, and suggest what ELSE could be done for maximum value. Be adversarial.

---

## Background

autodocs currently:
1. Detects when merged PRs make documentation stale (file path matching + code diffs)
2. Generates verified FIND/REPLACE edit suggestions (self-verified with line numbers)
3. Opens PRs with applied edits + uncertain suggestions in the PR description
4. Runs dual reasoning paths for verification, tracks feedback/outcomes
5. Supports 4 platforms (GitHub/ADO/GitLab/Bitbucket), 110 BATS tests

**Proven against:** Microsoft's teams-modular-packages (1200-line architecture doc, 8-file PR, all 4 change types) and a GitHub demo repo (7 applied edits from a JWT+RBAC migration).

**The problem:** The system is optimized for ONE repo archetype (large TypeScript monorepo with deep package hierarchy and multi-section Markdown architecture docs). 72 assumptions were identified in the codebase:
- 5 blocking (system fails completely)
- 24 degrading (detection quality drops significantly)
- 43 cosmetic (output quality affected)

~40% of potential users have small projects (<50 files, flat src/, README-only docs). These are the most underserved.

---

## The Plan

### For small/flat repos:
1. **File-level package_map matching** — Allow `"api.ts": "API Endpoints"` keys, not just directory-based keys
2. **Doc mode: "simple"** — Holistic suggestions for small docs instead of per-section mapping
3. **Setup auto-detection** — Count files, directory depth, section headers. Suggest appropriate defaults.

### For language diversity:
4. **Language hint in config** — `language: python` adjusts package extraction (e.g., `cmd/` for Go, `src/main/java/` for Java)
5. **Custom exclude patterns** — `exclude_patterns: ["test_*.py", "*_test.go"]` for non-standard test/generated file naming

### For monorepo noise:
6. **Daily alert cap/aggregation** — When >10 alerts target the same doc, collapse into ONE aggregated alert
7. **Shared packages config** — `shared_packages: ["components-fluid"]` → REVIEW confidence, not CONFIDENT

### For doc quality:
8. **Heading breadcrumb disambiguation** — Use "Error Handling > Examples" instead of just "Examples" when section names repeat
9. **Doc structure validation** — Setup warns if <5 section headers, suggests adding structure

### Deferred:
- Cross-repo drift (different architecture needed)
- Non-markdown docs (RST/HTML/AsciiDoc)
- Glob patterns for relevant_paths

---

## Your Review

Answer these specific questions, then provide your top 5 recommendations and suggest what ELSE could be done:

### Q1: File-Level Matching — Does It Scale?
The plan allows `"api.ts": "API Endpoints"` in package_map. But:
- What about files in subdirectories? Does `"api.ts"` match `src/routes/api.ts`?
- What about files with the same name in different directories? `utils.ts` might exist in 5 places.
- How does the matching priority work? If both `"api"` (directory key) and `"api.ts"` (file key) exist?
- Does this create a maintenance burden for repos with 100+ files?

### Q2: "Simple" Mode — Is It Actually Simpler?
The plan introduces `mode: "simple"` for small docs. But:
- Does the suggest prompt need completely different logic for simple vs structured mode?
- What if a README grows from 3 sections to 15 over time? Does the user need to switch modes?
- Could we avoid two modes entirely by making structured mode work for small docs too?
- Is "read the whole doc and generate holistic suggestions" actually better than per-section matching for small docs?

### Q3: Language Hints — Scope Creep Risk?
The plan adds `language: python|go|java|typescript` for package extraction.
- Is this the beginning of language-specific logic that grows unbounded?
- What about multi-language repos (TypeScript frontend + Go backend)?
- Could we instead use a more generic approach (user specifies the extraction pattern directly)?
- How does this interact with the structural scan (which uses `git ls-files`)?

### Q4: Alert Aggregation — When Does It Hurt?
The plan collapses >10 alerts into one aggregated alert.
- What if those 10 alerts are genuinely different and each needs attention?
- Is 10 the right threshold? Should it be configurable?
- Does aggregation lose the per-PR attribution that makes the changelog valuable?
- What about the suggest prompt — does it skip suggestions for aggregated alerts?

### Q5: Heading Breadcrumbs — Implementation Complexity
Using "Error Handling > Examples" instead of "Examples" for disambiguation.
- How does the drift prompt know the full heading path? It would need to parse heading hierarchy from the doc.
- Does this break the existing `package_map` format? Users currently write `"my-package": "Error Handling"`, not `"my-package": "Error Handling > Examples"`.
- What about docs with deeply nested headings (5+ levels)?

### Q6: What Else Could Be Done?
Beyond the 8 proposed improvements, what else would significantly improve autodocs for maximum compatibility across repo types? Consider:
- Onboarding experience for different repo types
- Detection accuracy improvements for edge cases
- Configuration simplification
- Auto-discovery improvements
- Novel approaches for handling repo diversity

---

## Format Your Response

1. **Top 5 Recommendations** (ordered by impact, each with: change, rationale, effort estimate)
2. **Answers to Q1-Q6** (be specific and actionable)
3. **One thing you'd kill from the plan** (if anything)
4. **One thing you'd add that isn't in the plan** (highest-value addition)
5. **Overall assessment**: Does this plan make autodocs truly universal, or does it just add complexity?
