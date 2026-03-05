# Plan: Universal Repo & Doc Compatibility

## Project Context

autodocs is an automated documentation drift detection tool supporting 4 platforms (GitHub/ADO/GitLab/Bitbucket). It currently works well for large monorepos with deep package hierarchies and multi-section Markdown architecture docs (proven against Microsoft's teams-modular-packages with 1200-line docs and a GitHub demo repo).

**The gap:** The system is optimized for ONE repo archetype. When users bring small projects, flat repos, Python/Go/Java conventions, simple READMEs, or non-standard structures, the detection quality degrades — sometimes silently.

**72 assumptions were identified** in the codebase. 5 are blocking, 24 are degrading, 43 are cosmetic. This plan addresses the highest-impact degrading assumptions to make autodocs work equally well across the full spectrum of repositories.

## The Spectrum of Repos

| Type | Files | Structure | Docs | % of potential users |
|------|-------|-----------|------|---------------------|
| **Small project** | <50 | Flat `src/` or root-level | README with 3-5 sections | ~40% |
| **Medium library** | 50-500 | 3-10 packages, 1-2 levels deep | Architecture doc + API reference | ~25% |
| **Large monorepo** | 500+ | 50+ packages, deep nesting | Multiple detailed docs | ~15% |
| **Multi-repo** | 10-100 per repo | 1-3 packages per repo | Per-service docs + shared wiki | ~15% |
| **Non-standard** | Varies | Python (`src/mypackage/`), Go (`cmd/`, `internal/`), Java (`src/main/java/`) | Mixed formats | ~5% |

autodocs currently handles the "large monorepo" case well. The "small project" case — the biggest user segment — has the most friction.

## Problems by Repo Type

### Small Projects (flat src/)

**Problem 1: No package hierarchy.** The `package_map` expects directory-based packages (`components-fluid` → "Error Handling"). In a flat repo like `src/api.ts`, `src/auth.ts`, `src/errors.ts`, there's no package to extract. The drift prompt's `/<key>/` matching fails.

**Fix:** Allow file-level keys in `package_map`:
```yaml
package_map:
  "api.ts": "API Endpoints"
  "auth.ts": "Authentication"
  "errors.ts": "Error Handling"
```
The drift prompt extends matching: first try `/<key>/` (directory), then try filename match. This is backwards-compatible — existing configs work unchanged.

**Problem 2: Everything is relevant.** With `relevant_paths: ["src/"]`, every PR is YES. Every change generates a drift alert. No filtering = noise.

**Fix:** During setup, when the repo has <50 files, suggest monitoring ALL code paths by default but with a smarter threshold: if >90% of PRs are classified YES, suggest narrowing `relevant_paths` in the weekly digest.

**Problem 3: Doc is a simple README.** Not a 19-section architecture doc. Maybe 3-5 sections. The structural scan, File Index verification, and package_map are overkill.

**Fix:** Auto-detect doc complexity during setup. Count section headers. If <5 sections, suggest a simplified config:
```yaml
docs:
  - name: "README.md"
    mode: "simple"  # Skips package_map, uses file-level matching
```
The suggest prompt adapts: for `mode: "simple"`, it reads the entire doc (small) and generates suggestions holistically rather than per-section.

### Medium Libraries (standard packages)

**Problem 4: Language-specific conventions.** Python uses `mypackage/module.py`. Go uses `cmd/` and `internal/`. Java uses `src/main/java/com/company/`. The `package_map` key extraction assumes `packages/components/my-package/` nesting.

**Fix:** Make package extraction language-aware. Add an optional `language` field to config:
```yaml
language: python  # or: go, java, typescript (default)
```
The drift prompt adjusts extraction:
- **TypeScript/JS (default):** Extract from `packages/<scope>/<name>/` or `src/<name>/`
- **Python:** Extract from `<package_name>/` (top-level package directory)
- **Go:** Extract from `cmd/<name>/` or `internal/<name>/` or `pkg/<name>/`
- **Java:** Extract from `src/main/java/<path>/` (last 2 segments)

This is a hint, not a requirement. If not set, use the default extraction logic.

**Problem 5: Test/generated file filtering misses custom patterns.** The hardcoded filters (`*.test.*`, `*.spec.*`, `dist/`, `build/`) miss Python tests (`test_*.py`, `*_test.py`), Go tests (`*_test.go`), and custom output dirs (`out/`, `target/`).

**Fix:** Add optional `exclude_patterns` to config:
```yaml
exclude_patterns:
  - "test_*.py"
  - "*_test.go"
  - "target/"
  - "__pycache__/"
```
If not set, use the current defaults (backwards-compatible). The sync prompt uses these patterns to filter files before diffing.

### Large Monorepos

**Problem 6: Sprint noise (15+ alerts per day).** During active development, many PRs touch the same feature area. Each generates drift alerts. The suggest prompt produces many similar suggestions.

**Fix:** Add a daily alert cap with aggregation. In the drift prompt:
```
If more than 10 HIGH alerts target the same doc in one run:
  Instead of 10+ individual alerts, generate ONE aggregated alert:
  "10 PRs affected <doc> this lookback window across sections:
   Error Handling (3 PRs), API Endpoints (4 PRs), Authentication (3 PRs).
   Consider a comprehensive doc review."
  Confidence: REVIEW (not per-section CONFIDENT)
```
This collapses noise into a single actionable signal.

**Problem 7: Shared dependency drift.** A change to `components-fluid` (shared) maps to 5+ doc sections. Most are noise — the change was internal.

**Fix:** The diff-aware suggestions already help here (the model sees the actual code change and can determine if it's internal). Additionally, add a `shared_packages` config field:
```yaml
shared_packages:
  - components-fluid
  - core-services
```
Shared packages generate REVIEW confidence (not CONFIDENT) by default, since changes are often internal.

### Multi-Repo

**Problem 8: Cross-repo drift.** Doc in repo A references API in repo B. API changes in repo B. autodocs on repo A sees nothing.

**Fix (partial):** Out of scope for v1. Document as a known limitation. For teams that need this, suggest: run autodocs on each repo independently, and use a shared changelog that both repos contribute to. Full cross-repo drift detection requires a fundamentally different architecture (monitoring multiple repos, linking APIs to docs across repos).

## Doc Format Handling

### Problem 9: Repeated section names

If "Examples" or "Usage" appears in multiple sections, drift detection may target the wrong one.

**Fix:** The drift prompt should use the FULL heading path (breadcrumb), not just the immediate header:
```
Instead of: "Error Handling" → "Examples"
Use: "Error Handling > Examples" (disambiguated)
```
The package_map and drift alerts use breadcrumb paths when the section name isn't unique.

### Problem 10: Doc without section headers

Some docs are flat prose or use non-standard formatting.

**Fix:** During setup doc validation, warn:
```
Warning: README.md has only 2 section headers.
Drift detection works best with structured sections (## headers).
Consider adding section headers, or use mode: "simple" for holistic suggestions.
```
For `mode: "simple"`, the suggest prompt generates suggestions for the entire doc rather than mapping to specific sections.

### Problem 11: Multiple docs

Some teams have 5+ docs. Configuring each with its own package_map is tedious.

**Fix:** The `setup.sh docs add` subcommand already supports adding multiple docs. Enhance it: when adding a doc, auto-suggest which packages map to it based on file paths referenced in the doc (the `discover_paths` function already does this). For teams with many docs, add a `setup.sh docs discover` command that scans the repo for all markdown files and proposes a multi-doc config.

## Implementation Summary

### Changes to Prompts

| Prompt | Change |
|--------|--------|
| `drift-prompt.md` | Add file-level key matching (not just directory). Add heading breadcrumb disambiguation. Add daily alert cap/aggregation for >10 alerts per doc. Shared packages → REVIEW confidence. |
| `suggest-prompt.md` | Add `mode: "simple"` support (holistic suggestions for small docs). |
| `sync-prompt.md` | Read `exclude_patterns` from config for diff filtering. Read `language` for package extraction hint. |
| `structural-scan-prompt.md` | Adapt file reference extraction for different language conventions. |

### Changes to Config

```yaml
# NEW optional fields:
language: typescript          # python, go, java, typescript (default)
exclude_patterns:             # Custom test/generated file filters
  - "test_*.py"
shared_packages:              # Packages that generate REVIEW, not CONFIDENT
  - components-fluid

docs:
  - name: "README.md"
    mode: "simple"            # "simple" (holistic) or "structured" (per-section, default)
```

### Changes to Setup

- Auto-detect repo complexity (file count, directory depth)
- Suggest appropriate defaults based on repo size
- Validate doc structure (section count, header presence)
- Warn about potential issues (flat repo, few sections, no File Index)

## Implementation Order

1. **File-level package_map matching** (drift-prompt) — enables flat repos
2. **Heading breadcrumb disambiguation** (drift-prompt) — prevents wrong-section targeting
3. **`mode: "simple"` for docs** (suggest-prompt, config) — enables README-only repos
4. **Exclude patterns in config** (sync-prompt, config) — enables Python/Go/Java repos
5. **Daily alert cap/aggregation** (drift-prompt) — reduces monorepo noise
6. **Shared packages config** (drift-prompt, config) — reduces false positives
7. **Setup doc validation** (setup.sh) — guides users to better configs
8. **Language hint** (config, sync-prompt) — adapts package extraction

## What This Does NOT Address

| Gap | Why deferred |
|-----|-------------|
| Cross-repo drift | Fundamentally different architecture. Requires monitoring multiple repos. |
| Non-markdown docs | RST/HTML/AsciiDoc need format-specific parsers. Markdown is ~90% of developer docs. |
| Auto-generated docs (Swagger, TypeDoc) | These tools handle their own drift. autodocs is for hand-written docs. |
| Glob patterns for relevant_paths | Adds regex complexity for marginal benefit. Prefix matching + relevant_pattern covers most cases. |
