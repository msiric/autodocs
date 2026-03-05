# Plan: Feedback Loop — Learning from Suggestion Outcomes

## Project Context

**autodocs** is an automated documentation drift detection tool that runs daily via Claude Code headless mode. It detects when merged PRs make documentation stale, generates verified FIND/REPLACE edit suggestions, and opens PRs with the fixes.

### Current Architecture (proven in production)

```
Call 1: Sync      — Fetch PRs (GitHub/ADO/GitLab/Bitbucket), get file changes
                    with types (A/M/D/R), targeted code diffs, PR descriptions + threads
Call 2: Drift     — Map changed packages to doc sections, flag unmapped files,
                    detect new telemetry patterns, refactoring detection
Call 3: Suggest   — Generate FIND/REPLACE edits with self-verification (line numbers),
                    changelog with WHY, multi-PR conflict detection
Call 3v: Verify   — Dual Opus reasoning paths, only AGREED suggestions auto-applied
Call 4: Apply     — Apply CONFIDENT+VERIFIED+AGREED suggestions to doc files,
                    include changelog, open PR with applied + review sections
Weekly: Scan      — Verify doc file references against repo
```

### What's Proven

- 91 BATS tests, 4 platforms (GitHub/ADO/GitLab/Bitbucket), ~98% market coverage
- 7/7 verified suggestions on Channel Pages (1200-line doc, Microsoft production)
- 7/7 verified suggestions on demo repo stress test (8 files, 4 change types)
- Auto-PR #1490334 on ADO, Auto-PR #2 and #4 on GitHub demo
- Multi-model verification (dual Opus), FIND/REPLACE self-verification
- Diff-aware suggestions, change type classification (A/M/D/R), stale detection
- Auto-detecting setup wizard with config management subcommands

### The Gap

The system generates suggestions and opens PRs but **never learns from outcomes.** When a reviewer merges, modifies, or rejects a suggestion, that signal is lost. The system makes the same quality of suggestions on day 100 as day 1.

## The Feedback Loop

### Three Layers of Feedback

**Layer 1: PR-level outcome tracking (automatic)**

Check the state of previously opened autodocs PRs:

| PR State | Signal | Meaning |
|----------|--------|---------|
| Merged as-is | ACCEPTED | All suggestions were accurate |
| Merged with modifications | MODIFIED | Some suggestions needed tweaking |
| Closed without merge | REJECTED | Suggestions were wrong or unnecessary |
| Open >48 hours | STALE | Needs attention, possibly low quality |

Trackable automatically via `gh pr view --json state,mergedAt,closedAt` (and equivalents for ADO/GitLab/Bitbucket).

**Layer 2: Per-suggestion outcome (diff comparison)**

Compare the autodocs PR's proposed changes against what was actually merged:

For each suggestion that was in the PR:
- If the FIND/REPLACE was kept verbatim in the merged doc → **ACCEPTED**
- If the section was changed but differently from the suggestion → **MODIFIED**
- If the section was NOT changed (suggestion removed before merge) → **REJECTED**

This requires comparing the autodocs branch against the final merged state.

**Layer 3: Reviewer signals (PR comments)**

Parse review comments on autodocs PRs for explicit feedback:
- Positive: "LGTM", "good", approval reviews
- Negative: "wrong", "incorrect", "don't change this", request-changes reviews
- Modification: inline code suggestions (reviewer edited the text)

### Using Feedback to Improve

**1. Few-shot examples from accepted suggestions**

Maintain `feedback/accepted-examples.md` with the 5 most recent accepted suggestions (kept verbatim on merge). Add these to the suggest prompt as few-shot context:

```markdown
## Examples of previously accepted suggestions

These were accepted by reviewers without modification. Match this quality and style.

### Example 1 (architecture.md — Error Handling):
FIND: | File creation | `getFluidOnPageLoad` | Error classification: Duplicate, ...
REPLACE WITH: | File creation | `getFluidOnPageLoad` / `handleFileCreationError` | Error classification: ...
Reasoning: PR #1477230 changed the error classification...
```

This primes the model to produce suggestions that match the team's expectations.

**2. Anti-patterns from rejected suggestions**

Maintain `feedback/rejected-patterns.md` with common rejection reasons:

```markdown
## Common rejection reasons — avoid these patterns

1. Suggesting changes to internal implementation details in a high-level architecture doc
2. Renaming functions in the doc when the code change was a private refactor
3. Adding excessive detail to summary tables (keep entries concise)
```

Add to the suggest prompt as negative examples.

**3. Per-section accuracy tracking**

Store acceptance rates per (doc, section) in `feedback/accuracy.json`:

```json
{
  "architecture.md": {
    "Error Handling": { "accepted": 8, "modified": 1, "rejected": 1, "rate": 0.80 },
    "API Endpoints": { "accepted": 5, "modified": 2, "rejected": 3, "rate": 0.50 }
  }
}
```

Sections with <70% acceptance → always REVIEW confidence, never CONFIDENT.
Sections with >90% acceptance → higher confidence in auto-apply.

## Implementation Plan

### Phase 1: Outcome Tracking

**New file: `templates/feedback-prompt.md`**

A lightweight prompt (Call 0) that runs BEFORE the sync chain. It checks the state of previously opened autodocs PRs and records outcomes.

```
Read ${OUTPUT_DIR}/feedback/open-prs.json (list of autodocs PRs we've opened).
For each PR, check its current state via platform CLI:
  - GitHub: gh pr view <number> --json state,mergedAt,closedAt
  - ADO: mcp__azure-devops__repo_get_pull_request_by_id

Record outcomes in ${OUTPUT_DIR}/feedback/outcomes.json.
Update ${OUTPUT_DIR}/feedback/accepted-examples.md with newly accepted suggestions.
Update ${OUTPUT_DIR}/feedback/accuracy.json with per-section rates.
```

**New file: `feedback/open-prs.json`** (written by Call 4)

When Call 4 opens a PR, append to this file:
```json
[
  {
    "pr_number": 4,
    "platform": "github",
    "date": "2026-03-05",
    "suggestions": [
      { "doc": "architecture.md", "section": "Error Handling", "type": "REPLACE" },
      { "doc": "architecture.md", "section": "API Endpoints", "type": "REPLACE" }
    ]
  }
]
```

**Wrapper script change:**

Add Call 0 before Call 1:
```bash
# Call 0: Check feedback from previously opened PRs
if [ -f "$OUTPUT_DIR/feedback-prompt.md" ] && [ -f "$OUTPUT_DIR/feedback/open-prs.json" ]; then
  claude -p "$(cat "$OUTPUT_DIR/feedback-prompt.md")" ...
fi
```

**Output: `feedback/outcomes.json`**

```json
{
  "total_prs": 4,
  "merged": 3,
  "closed": 0,
  "modified": 1,
  "acceptance_rate": 0.85,
  "suggestions": {
    "total": 21,
    "accepted": 18,
    "modified": 2,
    "rejected": 1
  },
  "by_section": {
    "Error Handling": { "accepted": 5, "modified": 0, "rejected": 0 },
    "API Endpoints": { "accepted": 4, "modified": 1, "rejected": 1 }
  }
}
```

### Phase 2: Few-Shot Examples

**Suggest prompt update:**

Add to the beginning of Step 3:
```
If ${OUTPUT_DIR}/feedback/accepted-examples.md exists, read it. These are
examples of suggestions that were accepted by reviewers. Use them as
reference for the quality, style, and level of detail expected.

If ${OUTPUT_DIR}/feedback/rejected-patterns.md exists, read it. Avoid
generating suggestions that match these anti-patterns.
```

**Feedback prompt update:**

When a PR is merged as-is, extract the top suggestions and append to `accepted-examples.md`. Keep only the 5 most recent examples (trim older ones).

When a PR is rejected or suggestions are removed, analyze the pattern and update `rejected-patterns.md`.

### Phase 3: Confidence Adjustment (deferred)

Read `accuracy.json` in the suggest prompt. For sections with <70% acceptance, cap confidence at REVIEW. For sections with >90%, allow CONFIDENT.

### Phase 4: Prompt Evolution (deferred)

Weekly meta-prompting: feed accuracy data to an LLM and ask it to suggest improvements to the suggest prompt itself. Versioned prompts with A/B testing.

## Files to Create/Modify

| File | Action |
|------|--------|
| `templates/feedback-prompt.md` | NEW — check PR outcomes, update metrics |
| `templates/apply-prompt.md` | MODIFY — write to open-prs.json after PR creation |
| `templates/suggest-prompt.md` | MODIFY — read accepted-examples.md + rejected-patterns.md |
| `templates/sync.sh` | MODIFY — add Call 0 before Call 1 |
| `feedback/` directory | NEW — outcomes.json, accepted-examples.md, rejected-patterns.md, open-prs.json, accuracy.json |
| `setup.sh` | MODIFY — render feedback-prompt.md |

## Implementation Order

1. Create feedback directory structure + open-prs.json format
2. Update apply-prompt.md to write PR tracking data
3. Create feedback-prompt.md (outcome checking)
4. Add Call 0 to wrapper script
5. Update suggest-prompt.md with few-shot reading
6. Test end-to-end: open PR → merge → next run reads feedback → suggest uses examples
