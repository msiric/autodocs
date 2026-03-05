# Review Synthesis: Repo Diversity (6 SOTA Models)

## Reviewers
Gemini, Opus, Grok, GPT, MiniMax, GLM

---

## Unanimous Consensus (6/6)

### 1. Kill `language:` hint — replace with pattern-based extraction
Every model says the language enum is scope creep. Multi-language repos break it immediately. The extraction rules grow unbounded.

- **Gemini:** "Kill it. Use `package_extraction_regex` instead."
- **Opus:** "This is exactly how scope creep starts. Kill it."
- **GPT:** "Pattern-based extractors + autodetect covers multi-language repos without scope creep."

**Decision:** Replace with `source_roots` or `package_extraction` patterns. Users specify where meaningful code lives. Zero language-specific logic.

### 2. Kill `mode: "simple"` — make structured mode adaptive
Every model says two modes doubles maintenance, creates transition friction, and is a false dichotomy.

- **Opus:** "Don't build mode: simple. Make structured mode degrade gracefully for small docs."
- **GPT:** "Kill modes. Implement automatic doc segmentation with hysteresis."
- **Gemini:** "Replace with Auto-Chunking."

**Decision:** No explicit modes. If doc has <5 sections, treat holistically. If ≥5, use per-section mapping. If `package_map` is empty, auto-generate from doc sections. Seamless transition as docs grow.

### 3. File-level matching needs path-awareness, not bare filenames
Every model warns that `"api.ts"` matching is ambiguous when `utils.ts` exists in 5 directories.

- **Opus:** "Glob semantics: `"src/auth/"` matches directory, `"*.controller.ts"` matches pattern."
- **GPT:** "Path-matching engine with exact path > glob > directory prefix > basename precedence."
- **GLM:** "Use explicit path patterns with glob support."

**Decision:** Path-aware matching with priority: exact path → glob → directory prefix → basename (only if unique). Longest/most-specific match wins.

### 4. Alert aggregation should preserve per-PR attribution
Every model says collapsing 10 alerts into "review the doc" destroys actionable specificity.

- **Opus:** "Replace with per-section deduplication. 3 PRs touching Error Handling → ONE alert citing all 3 PRs."
- **GPT:** "Do aggregation in the orchestrator with budgets, clustering, and links."
- **Gemini:** "Aggregation should happen in the Presentation Layer, not the Logic Layer."

**Decision:** Per-section deduplication (not per-doc aggregation). Multiple PRs touching same section → one alert with all PR references. Configurable threshold. Never lose per-PR attribution.

---

## Strong Consensus (5/6)

### 5. Setup wizard with repo analysis and live preview
- **Opus:** "Config-free first run with auto-generated configuration."
- **Gemini:** "Interactive Dry Run Wizard — print tree view of mappings."
- **GLM:** "Interactive setup wizard with analysis output."
- **GPT:** "Backtest + shadow mode onboarding with auto-config PR."
- **MiniMax:** "Doc Health Score during setup."

**Decision:** `setup.sh analyze` command that scans repo, proposes config, shows what would be detected. Accept/modify before saving.

### 6. Heading breadcrumbs for disambiguation
5/6 agree breadcrumbs are the right approach but should be capped at 2 levels and implemented via heading hierarchy parsing, not user config.

- **Opus:** "Cap breadcrumbs at 2 levels: parent + section."
- **GLM:** "Simpler alternative: require unique section names, warn during setup."

**Decision:** Implement 2-level breadcrumbs internally. Don't change `package_map` format. Warn during setup if section names aren't unique.

---

## Top Novel Ideas

### 7. Config-free auto-setup for small repos (Opus)
For repos with <50 files and one doc: auto-detect doc, auto-generate package_map from doc section headers + file paths, auto-set relevant_paths. Zero configuration.

### 8. Doc coverage map (Opus)
After setup, show what's covered and what isn't: which packages have doc mappings, which don't, which doc sections have no source mapping.

### 9. Dry-run mode against recent PRs (Opus, GPT)
`autodocs dry-run --last 5` — replay last 5 PRs through detection, show what would have been detected. Validates config before production use.

### 10. Validate package_map during setup (MiniMax)
Warn if a key matches multiple files, if keys conflict, or if directories don't exist.

---

## Revised Priority Order

| # | Improvement | What it replaces | Source |
|---|------------|-----------------|--------|
| 1 | Config-free auto-setup for small repos | Manual setup wizard | Opus, all |
| 2 | Path-aware matching (glob + precedence) | File-level bare filenames | All 6 |
| 3 | Adaptive structured mode (no explicit "simple") | `mode: "simple"` | All 6 |
| 4 | `exclude_patterns` in config | Hardcoded test/generated filters | All 6 (kept from plan) |
| 5 | Per-section dedup (not per-doc aggregation) | Alert cap at 10 | All 6 |
| 6 | `setup.sh analyze` with repo analysis | Basic auto-detection | 5/6 |
| 7 | 2-level heading breadcrumbs | — | 5/6 |
| 8 | Package_map validation warnings | — | MiniMax, GLM |

---

## What Was Killed

| Proposal | Killed By | Replacement |
|----------|-----------|-------------|
| `language: python\|go\|java\|typescript` | All 6 | Generic `source_roots` / extraction patterns |
| `mode: "simple"` | All 6 | Adaptive structured mode (auto-adjust by section count) |
| Alert aggregation (>10 → one alert) | All 6 | Per-section deduplication with per-PR attribution |
| Hardcoded file-level matching (bare `"api.ts"`) | All 6 | Path-aware matching with glob + precedence |
