# Understanding autodocs PRs

When autodocs detects that merged code changes have made your documentation stale, it opens a pull request with suggested updates. This guide explains how to read, review, and act on these PRs.

## What an autodocs PR looks like

autodocs PRs have:
- **Title**: `docs: autodocs suggested updates — YYYY-MM-DD`
- **Label**: `autodocs`
- **Branch**: `autodocs/YYYY-MM-DD`
- **Files changed**: Your documentation files + a changelog file

The PR body has three sections:

### Applied (verified)

Suggestions that passed all quality gates and were applied to the doc files. The changes appear in the PR diff. Each lists:
- Which doc section was updated
- Which PRs triggered the change
- What was changed and why

**Your job**: Review the diff. If the changes look correct, merge. If something is wrong, close the PR or edit the doc manually.

### Needs Manual Review

Suggestions that could not be fully verified. They are NOT applied to files — they appear only in the PR description. Reasons:
- **REVIEW confidence** — the change is ambiguous; the system isn't sure the doc needs updating
- **FIND_FAILED** — the target text was already changed (by a previous PR or manual edit)
- **UNVERIFIED** — the suggestion contains values that couldn't be checked against source code

**Your job**: Read each suggestion. If it's correct, apply it manually. If not, ignore it.

### Blocked (value mismatch)

Suggestions where the REPLACE text contained code references that don't exist in the current source code. These are blocked to prevent incorrect documentation.

**Your job**: Usually nothing — the block prevented a bad edit. If you think the block was wrong, check the source code and apply the change manually.

## Verification levels

Each suggestion goes through deterministic Python verification:

| Level | Meaning | Auto-applied? |
|-------|---------|--------------|
| **EVIDENCED** | All code references in the suggestion exist in the source files | Yes |
| **MISMATCH** | A code reference in the suggestion doesn't exist in source (likely wrong) | No — blocked |
| **UNVERIFIED** | The suggestion contains values that can't be mechanically checked | No — needs review |

## Labels

| Label | Meaning |
|-------|---------|
| `autodocs` | This PR was created by autodocs |
| `autodocs:stale` | This PR has been open for 14+ days without activity |
| `autodocs:keep-open` | Add this label to prevent autodocs from auto-closing the PR |

## What to do when a suggestion is wrong

1. **Close the PR** — autodocs will regenerate suggestions on the next run if the drift is still detected
2. **Edit manually** — fix the doc yourself; the next run will see your changes as the current state
3. **Report it** — if the same wrong suggestion keeps appearing, check whether the `package_map` in config needs updating

## How autodocs decides what to suggest

1. A PR merges that changes files mapped to your documentation
2. autodocs reads the full source files (not just diffs) to understand the current state
3. It generates FIND/REPLACE suggestions targeting specific text in your docs
4. Python verification checks that FIND text exists in the doc and REPLACE values exist in source code
5. Only verified suggestions are applied; everything else is flagged for review

## FAQ

**Q: Can autodocs break my documentation?**
A: No. It creates PRs for human review. Nothing is merged without a reviewer approving it.

**Q: What if I disagree with a suggestion?**
A: Close the PR. If the same suggestion reappears, add context to your config or use the `autodocs:keep-open` label.

**Q: How do I stop autodocs from suggesting changes to a specific section?**
A: Currently, remove that section's package_map entry from config. A section-level ignore mechanism is planned.

**Q: The PR has been open for weeks. Will autodocs close it?**
A: After 14 days, autodocs adds a `autodocs:stale` label and posts a warning comment. After 21 days with no activity, it auto-closes. Add `autodocs:keep-open` to prevent this.
