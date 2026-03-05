# Adversarial Review: Feedback Loop — Learning from Suggestion Outcomes

You are reviewing a plan to add a feedback loop to **autodocs** — an automated documentation drift detection tool that opens PRs with doc update suggestions. Your job is to find flaws, propose alternatives, identify risks, and suggest what ELSE could be done for maximum value. Be adversarial — assume the plan has blind spots.

---

## Background

autodocs is a tool that:
1. Runs daily via Claude Code headless mode
2. Detects when merged PRs make documentation stale (file path matching + code diffs)
3. Generates FIND/REPLACE edit suggestions with self-verification (each FIND block confirmed verbatim in doc)
4. Runs dual reasoning paths (Opus + Opus variant) — only AGREED suggestions auto-applied
5. Opens PRs on GitHub/ADO/GitLab/Bitbucket with applied edits + uncertain suggestions in description
6. Maintains per-doc changelogs capturing WHY things changed

**The gap:** The system generates suggestions and opens PRs but never learns from the outcome. When a reviewer merges, modifies, or rejects a suggestion, that signal is lost. Accuracy is static — same quality on day 100 as day 1.

**Current metrics:** 7/7 verified in two separate test runs (Channel Pages + demo repo). No production rejection data yet.

---

## The Plan

### Layer 1: PR-Level Outcome Tracking
A new "Call 0" runs before the daily sync chain. It checks the state of previously opened autodocs PRs via platform CLI (merged, closed, modified). Records outcomes in `feedback/outcomes.json`.

### Layer 2: Per-Suggestion Diff Comparison
Compare the autodocs PR's proposed changes against what was actually merged. Each suggestion is classified as ACCEPTED (kept verbatim), MODIFIED (section changed differently), or REJECTED (suggestion removed).

### Layer 3: Using Feedback to Improve
1. **Few-shot examples:** Top 5 accepted suggestions added to the suggest prompt as positive examples
2. **Anti-patterns:** Common rejection reasons added as negative examples
3. **Per-section accuracy:** Track acceptance rates per (doc, section) in JSON. Low-accuracy sections get lower confidence.
4. **Prompt evolution (deferred):** Meta-prompting to rewrite the suggest prompt based on accumulated feedback.

### Storage
```
feedback/
├── open-prs.json           — PRs opened by autodocs (tracking data)
├── outcomes.json            — Aggregate metrics (acceptance rate, by-section)
├── accepted-examples.md     — Top 5 recently accepted suggestions (few-shot)
├── rejected-patterns.md     — Common rejection anti-patterns
└── accuracy.json            — Per-section acceptance rates
```

---

## Your Review

Answer these specific questions, then provide your top 5 recommendations and suggest what ELSE could be done:

### Q1: Is Call 0 the Right Place?
The plan adds a "Call 0" that runs before the sync chain to check PR outcomes. This means:
- An additional Claude Code call every day, even on days with no feedback to process
- The feedback check is coupled to the daily sync schedule
- If the sync fails, feedback is still collected (good) but if feedback fails, the sync still runs (also good)

Is a separate call the right approach? Should feedback checking be:
- Part of Call 1 (sync)? Simpler, fewer calls.
- A separate scheduled job (not tied to the daily sync)? More flexible.
- Event-driven (triggered when a PR state changes)? Most responsive but harder to implement.

### Q2: Per-Suggestion Diff Comparison — Complexity
Comparing the autodocs branch against the merged commit to determine per-suggestion outcomes is non-trivial:
- What if the doc was edited multiple times between the autodocs PR and the final merge?
- What if the reviewer merged the autodocs PR AND also made manual edits in the same merge?
- What if the reviewer applied the suggestion differently (same intent, different wording)?
- How do you attribute "this specific line was changed because of autodocs" vs "this line was changed independently"?

### Q3: Few-Shot Quality
The plan uses the 5 most recent accepted suggestions as few-shot examples. Concerns:
- Are the most RECENT necessarily the most REPRESENTATIVE? A suggestion from 2 weeks ago might be more instructive.
- Could few-shot examples create bias? If all 5 examples are INSERT AFTER operations, the model might prefer INSERT AFTER over REPLACE.
- 5 examples adds ~500 tokens to the suggest prompt. Is this the right number?
- Should examples be per-section (Error Handling examples for Error Handling suggestions) or global?

### Q4: Anti-Pattern Maintenance
The plan stores rejection reasons in `rejected-patterns.md`. But:
- Who writes the anti-patterns? The feedback prompt (LLM inference from rejection data)? The user manually? Both?
- How do you prevent anti-patterns from growing unbounded?
- Could a false anti-pattern (incorrectly attributing a rejection reason) suppress future good suggestions?

### Q5: Per-Section Accuracy — Cold Start
When autodocs first runs, there's no accuracy data. The plan says sections with <70% acceptance get REVIEW confidence. But:
- How many data points are needed before the accuracy is meaningful? (3 suggestions? 10? 50?)
- What if a section only gets 1 suggestion per month? The accuracy number will be noisy.
- Should there be a minimum sample size before accuracy affects confidence?

### Q6: What Else Could Be Done?
Beyond the proposed feedback loop, what else would significantly improve autodocs for maximum value? Consider:
- Alternative feedback signals beyond PR merge/reject
- Ways to improve suggestions WITHOUT a feedback loop
- User experience improvements for the feedback process
- Integration with team workflows (Slack, dashboards, retrospectives)
- Novel approaches to learning from outcomes

---

## Format Your Response

1. **Top 5 Recommendations** (ordered by impact, each with: change, rationale, effort estimate)
2. **Answers to Q1-Q6** (be specific and actionable)
3. **One thing you'd kill from the plan** (if anything)
4. **One thing you'd add that isn't in the plan** (highest-value addition)
5. **Overall assessment**: Is this the right approach to making autodocs self-improving?
