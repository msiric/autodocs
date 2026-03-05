# Review Synthesis: Production Failure Modes (Round 5 — Final)

> 5 models reviewed: Gemini, Opus, Grok, GPT, MiniMax/GLM
> Date: 2026-03-05

## Q1: First Failure Prediction — Two camps, same root

**Camp 1 (Gemini, Opus): Silent zero output**
The pipeline runs, everything succeeds, but nothing useful is produced. Causes:
- Config drift (package_map doesn't match actual repo structure)
- All PRs classified NO (batch of dependency bumps)
- Auth token degradation (gh returns empty arrays, not errors)
- Timestamp advances even when nothing was processed → PRs lost forever

**Camp 2 (Grok, GPT, MiniMax/GLM): Config drift specifically**
New directories emerge, package_map doesn't cover them, changes go undetected.

**Both camps agree on detection**: Add a "liveness ratio" — if merged PRs > 5 but relevant PRs = 0, alert. Track `match_rate` (matched files / total changed files) and alert if < 60%.

**Key Opus insight**: Only advance `last-successful-run` timestamp when relevant PRs were actually processed, not just when the pipeline completes. This prevents "classified all NO → timestamp advances → PRs lost forever."

## Q2: Trust Recovery — Unanimous: implement post-merge edit detection

**5/5 agree**: Implement now, not later.

The mechanism: After a merged autodocs PR, scan for non-autodocs commits that edit the same doc sections within 7 days. Three signal strengths:
- **REVERT** (strong): commit removes autodocs' exact REPLACE text
- **SECTION_EDIT** (medium): same section edited, may be correction
- **FILE_EDIT** (weak): same file edited, likely unrelated

Log to metrics. Alert if REVERT rate > 10%. This is the only automated signal for "merged and wrong" — without it, the 10% error threshold from round 2 is unmeasurable.

## Q3: Ready to Deploy? — Unanimous: YES

**5/5 say ship it.** No remaining blockers.

Key quotes:
- Gemini: "The system is safer than a junior developer and likely more thorough."
- Opus: "None of these are 'corrupts production docs.' Every scenario either produces nothing (safe) or a PR that a human reviews before merge (safe)."
- Grok: "Diminishing returns are evident — further tweaks add complexity without proportional gains."

**Deployment strategy consensus**:
1. Week 1: dry-run / Draft PRs only
2. Week 2: enable PRs, tell team "treat as 80% confidence drafts"
3. Week 4: review metrics, especially REVERT signals

**Pre-deploy additions (small, high-value)**:
- Liveness assertions (10 lines of bash — don't advance timestamp if nothing was relevant)
- Post-merge edit detection (~50 lines of Python)
- Match rate metric (coverage tracking)

## Implementation Action Items

### Before deploying (add to output trust implementation):

1. **Liveness guard**: Only advance `last-successful-run` if relevant PRs were processed or no PRs existed
2. **Match rate metric**: Log `matched_files / total_files` to metrics.jsonl, alert if < 60%
3. **Post-merge edit detection**: Scan for non-autodocs commits to same doc sections within 7 days of merge, classify as REVERT/SECTION_EDIT/FILE_EDIT
4. **Noise blocklist**: Ensure `*.lock`, `dist/`, `node_modules/`, `*.map`, `*.min.*` are excluded from file lists before reaching any LLM call

### Everything else is post-deploy iteration driven by production data.
