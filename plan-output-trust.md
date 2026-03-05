# autodocs — Output Trust Plan

> Date: 2026-03-05
> Problem: The system verifies LLM inputs (FIND text exists) but not outputs (REPLACE text is correct)
> Discovery: A factual error ("default role: viewer" vs actual "member") appeared in 2 out of 3 PRs on the demo repo

## The Root Problem

The system has a clear asymmetry:

| Operation | Verified? | How |
|-----------|-----------|-----|
| FIND text exists in doc | Yes | Python `verify_finds()` — deterministic, 0% false positive |
| REPLACE text is factually correct | **No** | Trusted without verification |
| Changelog "Changed" is accurate | **No** | Trusted without verification |
| PR classification (YES/NO) | **No** | LLM instructed to be deterministic but not checked |
| File list from git diff-tree | **No** | LLM transcribes, not verified |

The REPLACE text gap is the most damaging because it's the actual edit that lands in the PR. A wrong REPLACE text with a correct FIND text will be auto-applied, creating incorrect documentation that passes all current quality gates.

## The Specific Failure Chain We Found

1. PR #3 changed `role: data.role ?? 'member'` → `'viewer'` in source code
2. Autodocs changelog correctly recorded: "Default role changed from member to viewer"
3. PR #5 changed it back: `'viewer'` → `'member'`
4. PR #5's diff was truncated at 150 lines; the role revert was in `users.ts` which came last alphabetically and got summarized instead of diffed
5. Autodocs changelog for PR #5 didn't mention the role revert (too many other changes)
6. Future runs read changelog → see "default: viewer" → no contradicting entry → generate suggestions with wrong value "viewer"
7. The FIND text is correct (the doc does say "member" in the original). The REPLACE text is wrong (says "viewer" when code says "member"). FIND verification passes. The wrong edit lands in the PR.

## Full Audit: 20 Unverified Trust Points

The research agent identified 20 specific points where LLM output is trusted without verification. Grouped by severity:

### Critical (wrong output → permanent damage)

| ID | What | Where | Frequency |
|----|------|-------|-----------|
| C8 | **REPLACE text correctness** | suggest-prompt → drift-suggestions.md | HIGH |
| C18 | **Description→suggestion cascade** | drift-prompt → suggest-prompt (2 layers of unverified inference) | MEDIUM |

### High (wrong output → silent incorrect behavior)

| ID | What | Where | Frequency |
|----|------|-------|-----------|
| C1 | PR classification (YES/NO) | sync-prompt → daily-report.md | MEDIUM |
| C6 | "What Changed" descriptions | drift-prompt → drift-report.md → suggest-prompt | HIGH |
| C9 | Changelog "Changed" accuracy | suggest-prompt → changelog-*.md | MEDIUM |
| C10 | Changelog "Why" accuracy | suggest-prompt → changelog-*.md | MEDIUM |
| C14 | Faithful application of edits | apply-prompt → git commit | LOW |
| C16 | Filter compliance in apply | apply-prompt → which suggestions applied | LOW |
| C19 | Changelog poisoning feedback loop | changelog → suggest-dedup → future runs | LOW |

### Medium (wrong output → noise or suboptimal behavior)

C2 (file list), C3 (PR description), C4 (anomaly classification), C7 (drift-context rendering), C11 (confidence rating), C12 (section targeting), C13 (multi-PR conflicts), C15 (PR body accuracy), C20 (fallback path bypasses)

### Low

C5 (refactoring detection), C17 (tracking data)

## Proposed Fixes

### Layer 1: Prompt-level (immediate, zero code changes)

**1a. Changelog staleness warning in suggest prompt**

Add to suggest-prompt.md Rules section:
```
- Changelog entries reflect what was true AT THE TIME of the PR. Later PRs may
  have reverted or changed values. If your suggestion references a specific value
  (function name, default, type, endpoint path) from a changelog entry, verify it
  against the diff. If no diff is available, set confidence to REVIEW and note:
  "Value from changelog — not verified against current code."
```

**1b. Diff prioritization by change magnitude**

Add to sync-prompt.md diff instructions:
```
Prioritize files by number of changed hunks (most changes first), not alphabetically.
This ensures the most significantly modified files get full diff coverage within
the 150-line budget.
```

**1c. Source code verification instruction in suggest prompt**

Add to suggest-prompt.md Step 3:
```
After generating each REPLACE block, verify every concrete value (function name,
default value, parameter type, error code) against the source code diff. If the
diff for this PR doesn't contain the value, read the current source file to confirm.
If you cannot verify a value, mark the suggestion as REVIEW confidence.
```

### Layer 2: Deterministic pre-processing (medium effort, high value)

**2a. Current-state extraction for suggest context**

New operation in `drift-helper.py`: `extract-state <output_dir> <repo_dir>`

For each file referenced in the current alert set, extract:
- Function/method signatures (name + parameters)
- Exported constants and their values
- Default parameter values
- Type definitions

Write to `current-state.json`. The suggest prompt reads this as ground truth:
```json
{
  "src/api/users.ts": {
    "functions": [
      {"name": "createUser", "params": "req: Request, data: Partial<User>", "defaults": {"role": "member", "status": "pending"}},
      {"name": "listUsers", "params": "req: Request, cursor?: string, limit: number = 20"}
    ],
    "exports": ["listUsers", "getUser", "createUser", "updateUser", "deleteUser"]
  }
}
```

Extraction uses regex (not AST) — covers TypeScript/JavaScript patterns:
- `export (async )?function (\w+)\(([^)]*)\)` → function signatures
- `(\w+):\s*data\.\w+\s*\?\?\s*['"](\w+)['"]` → default values
- `export (const|class|interface|type) (\w+)` → exports

This is the same philosophy as `match-helper.py` and `drift-helper.py` — deterministic Python for verifiable operations.

**2b. REPLACE value verification**

Extend `verify_finds()` in `drift-helper.py` to also check REPLACE text:

After FIND verification passes, extract concrete values from REPLACE text:
- Backtick-wrapped identifiers: `` `functionName` ``
- Quoted strings: `'member'`, `"viewer"`
- Code references: `src/path/file.ts`

For each extracted value, check if it exists in:
1. The source file(s) referenced by the suggestion's section mapping
2. The current-state.json (if available)

If a value in REPLACE text doesn't exist in the source, flag as `REPLACE_MISMATCH`:
```json
{"doc": "architecture.md", "status": "REPLACE_MISMATCH", "reason": "'viewer' not found in src/api/users.ts; found 'member' instead"}
```

**2c. Changelog supersession detection**

In `suggest-dedup`, when reading changelog entries, check if any of the files from the triggering PRs were also touched by later PRs. If so, add a warning to `suggest-context.json`:

```json
{
  "actionable_alerts": [...],
  "changelog_warnings": [
    {"doc": "architecture.md", "section": "API Endpoints", "pr": 3,
     "warning": "Changelog entry from PR #3 may be superseded — PR #5 also modified src/api/users.ts"}
  ]
}
```

The suggest prompt reads these warnings and treats flagged changelog entries with skepticism.

### Layer 3: Deterministic post-processing (higher effort, highest reliability)

**3a. PR classification verification**

After Call 1 produces daily-report.md, re-run the classification in Python:
- Parse the file list from the report
- Apply the same `relevant_paths` and `relevant_pattern` matching that match-helper.py uses
- Compare Python's classification against the LLM's classification
- Log mismatches; optionally override

**3b. Post-apply diff verification**

After Call 4 creates the git commit, verify that the committed changes match the expected FIND/REPLACE operations:
- Read the git diff of the commit
- For each suggestion that was supposed to be applied, verify the FIND text was removed and REPLACE text was added
- Flag any unexpected changes (edits beyond the FIND/REPLACE scope)

## Implementation Order

```
Phase A: Prompt fixes (immediate, ship today)
  1a: Changelog staleness warning
  1b: Diff prioritization by change magnitude
  1c: Source code verification instruction

Phase B: Deterministic extraction (next session)
  2a: current-state extraction (extract-state operation)
  2b: REPLACE value verification
  2c: Changelog supersession detection

Phase C: Post-processing verification (future)
  3a: PR classification verification
  3b: Post-apply diff verification
```

Phase A addresses the symptom (the LLM doesn't know the changelog is stale). Phase B addresses the root cause (the LLM has no ground truth for current code state). Phase C closes remaining gaps.

## Open Questions for Review

1. **Is regex-based extraction reliable enough for current-state.json?** TypeScript has complex syntax (generics, decorators, overloads). Regex covers 80% of cases. Is 80% good enough, or does this need tree-sitter/AST?

2. **Should REPLACE_MISMATCH block the suggestion or just flag it?** If we block, we might over-reject (the REPLACE text could use different wording than the source). If we flag, we're back to trusting the LLM to notice the flag.

3. **Is the 150-line diff budget the right trade-off?** Increasing to 300 lines doubles the context cost. The truncation directly caused the failure we found. But larger context windows have their own problems (LLM attention degradation, cost).

4. **Should the changelog have a TTL?** Instead of append-only-forever, entries older than N days could be marked `[HISTORICAL]` with a note that values may have changed. This reduces poisoning risk without deleting history.

5. **Is the description→suggestion cascade (C18) solvable?** The drift prompt generates descriptions that the suggest prompt consumes. Two layers of LLM inference means two chances to introduce errors. Should the suggest prompt read the raw data (daily-report.md) instead of the processed drift output?
