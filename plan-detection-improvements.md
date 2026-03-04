# Plan: Detection & Suggestion Quality Improvements

## Project Context

**autodocs** is an automated documentation drift detection tool. It runs daily via Claude Code headless mode, detects when merged PRs make documentation stale, generates verified FIND/REPLACE edit suggestions, and opens PRs with the fixes.

### Current Architecture (5-call daily chain)

```
Call 1: Sync     — Fetch merged PRs (ADO/GitHub/GitLab/Bitbucket), get changed files
                   via git diff-tree, classify PRs by path matching, run Kusto queries
Call 2: Drift    — Map changed packages to doc sections, flag unmapped files,
                   detect new telemetry patterns
Call 3: Suggest  — Generate FIND/REPLACE edits with self-verification, write changelog
Call 3v: Verify  — Re-run suggest with variant reasoning, compare outputs
Call 4: Apply    — Apply AGREED suggestions to doc files, create branch, open PR
```

### What Works Today

- Package-to-section mapping via `git diff-tree` (proven: 7/7 suggestions verified)
- FIND/REPLACE with self-verification (FIND text confirmed verbatim in doc with line numbers)
- Multi-model verification (two Opus reasoning paths, only AGREED suggestions auto-applied)
- Auto-PR creation on GitHub and ADO (tested: PR #1490334 on ADO, PR #2 on GitHub demo)
- Changelog capturing WHY things changed (from PR descriptions + review threads)
- Weekly structural scan (96 files verified, 12 gaps found)
- 4-platform support (GitHub, ADO, GitLab, Bitbucket)
- 73 BATS tests covering all critical logic

### Where Detection Is Fragile

The system currently uses FILE PATHS as the primary signal. It knows WHICH files changed but not WHAT changed inside them. This creates several failure modes:

## Proposed Improvements

### 1. Diff-Aware Suggestions (Highest Impact)

**Problem:** The suggest prompt infers what changed from PR title and file list. It doesn't see the actual code changes. This leads to vague suggestions ("PR modified error handling code") instead of precise ones ("PR renamed `ComposeOneDriveOutOfStorageError` to `ChannelPageOutOfStorageError` on line 47").

**Solution:** In the sync prompt's Step 3, after `git diff-tree` returns the file list, also run `git diff <merge_commit>^..<merge_commit> -- <file>` for each relevant (YES/MAYBE) file. Include a truncated diff (first 200 lines per file) in daily-report.md under a `Diff:` field.

The suggest prompt reads the diff when generating FIND/REPLACE edits, giving it ground truth about what ACTUALLY changed in the code.

**Changes:**
- `templates/sync-prompt.md` Step 3: add `git diff` command for relevant files
- `templates/sync-prompt.md` Step 8: add `Diff:` field to PR output format
- `templates/suggest-prompt.md` Step 3: use Diff field for precise suggestions

**Token cost:** ~200 lines per file × ~5 relevant files = ~1000 extra lines in daily-report.md. Acceptable for a daily job.

### 2. Change Type Classification (ADD/MODIFY/DELETE)

**Problem:** When a PR deletes a file, our system says "package X was modified" and suggests updating the doc. It should say "FILE DELETED — remove from documentation."

**Solution:** Use `git diff-tree --diff-filter` to classify each file change:
```
git diff-tree --no-commit-id --name-status -r <commitId>
```
This returns:
```
M  src/errors/handler.ts       (modified)
A  src/auth/rate-limiter.ts     (added)
D  src/legacy/old-handler.ts    (deleted)
```

Include the change type in daily-report.md alongside each file path. The drift and suggest prompts use this to:
- MODIFY → suggest updating the doc section
- ADD → suggest adding documentation for the new file (CRITICAL alert for unmapped)
- DELETE → suggest removing the doc reference to the deleted file

**Changes:**
- `templates/sync-prompt.md` Step 3: use `--name-status` instead of `--name-only`
- `templates/sync-prompt.md` Step 8: include change type (A/M/D) per file
- `templates/drift-prompt.md` Step 6: handle DELETE as "doc reference may be stale"
- `templates/suggest-prompt.md` Step 3: generate removal suggestions for DELETE

### 3. Multi-PR Section Merging

**Problem:** Two PRs in the same lookback window change the same doc section. The suggest prompt generates two separate, potentially conflicting suggestions. PR #100 says "add parameter X to foo()" and PR #101 says "rename foo() to bar()." The correct update is "bar() now has parameter X."

**Solution:** In the suggest prompt, when multiple PRs map to the same (doc, section), process them as a GROUP:
1. Read ALL their diffs together
2. Generate ONE combined suggestion that accounts for all changes
3. Reference all contributing PRs in the trigger and changelog

**Changes:**
- `templates/suggest-prompt.md` Step 3: add "If multiple PRs trigger the same section, read all their diffs together and generate ONE combined FIND/REPLACE that accounts for all changes."

### 4. Large PR Detection

**Problem:** A refactoring PR touches 200 files across 15 packages. The system generates 15 HIGH alerts and 15 suggestions — mostly noise. The user loses trust.

**Solution:** In the sync prompt, after collecting file paths, check if:
- File count > 50 (large PR)
- AND >80% of changes are in different packages (spread across codebase)

If detected, classify the PR as "REFACTOR" instead of YES/MAYBE. The drift prompt generates ONE LOW alert: "Large refactoring PR (N files across M packages) — manual review recommended." The suggest prompt skips it entirely.

**Changes:**
- `templates/sync-prompt.md` Step 4: add refactoring detection heuristic
- `templates/drift-prompt.md` Step 6: handle REFACTOR classification as single LOW alert

### 5. Fuzzy FIND Matching in Apply (Resilience)

**Problem:** Between suggestion generation and PR application, someone manually edits the doc. The exact FIND text no longer exists. The apply prompt silently skips the suggestion.

**Solution:** In the apply prompt, if the exact FIND text isn't found:
1. Search for the closest match using first + last line of the FIND block
2. If a close match is found → apply but mark as "fuzzy matched — verify in PR review"
3. If no close match → skip and note in PR description

**Changes:**
- `templates/apply-prompt.md` Step 2: add fuzzy matching fallback with clear warning

## Implementation Order

1. Change type classification (ADD/MODIFY/DELETE) — smallest change, immediate value
2. Diff-aware suggestions — biggest impact on suggestion quality
3. Multi-PR section merging — prevents conflicting suggestions
4. Large PR detection — noise reduction
5. Fuzzy FIND matching — resilience improvement

## What This Does NOT Address (Deferred)

- Config file content analysis (which flag changed, what value)
- Cross-repo drift (changes in a dependency repo affecting your docs)
- Narrative drift (doc says "we do X because Y" but the rationale changed)
- Auto-generating package_map from doc structure (setup improvement, not detection)
