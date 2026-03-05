# Feedback Loop Roadmap

> Based on 6-SOTA-model adversarial review + research from GitHub Copilot, OpenAI Self-Evolving Agents, and Swimm.
> Last updated: 2026-03-05

## Principle

Build the telescope before the autopilot. Track everything. Automate the response only when we have enough data to make meaningful decisions.

---

## Phase 1: Track (IMPLEMENTED)

**Status:** Done. Shipped 2026-03-05.

**What it does:**
- Records every autodocs PR in `feedback/open-prs.json` (number, platform, date, suggestions)
- Checks PR state via bash (`gh pr view`) before each daily sync — no LLM call
- Updates state to merged/closed when PRs are resolved
- Deduplicates: suggest prompt skips sections with pending autodocs PRs
- Surfaces acceptance rate in `sync-status.md`
- 19 TDD tests for the feedback helper

**What it collects:**
- PR-level outcomes: open → merged / closed
- Per-suggestion tracking: doc, section, type (REPLACE/INSERT)
- Acceptance rate: merged / (merged + closed)
- Timeline: when PRs were opened and resolved

**Activation threshold for Phase 2:** n ≥ 20 resolved PRs (merged + closed).

---

## Phase 2: Learn from Examples (after n ≥ 20)

**Goal:** Use accepted suggestions as few-shot examples in the suggest prompt. Use per-section accuracy to adjust confidence.

### 2a. Few-Shot Examples from Accepted Suggestions

**What:** Maintain `feedback/accepted-examples.md` with diverse accepted suggestions. Add to suggest prompt as positive examples.

**Selection strategy (from 6-model review — NOT "5 most recent"):**
- Stratified by operation type: 1 REPLACE, 1 INSERT AFTER, 1 deletion/removal
- Prefer reviewer-MODIFIED suggestions (the delta between proposal and final merge is the signal — Opus recommendation)
- 3-5 examples total, ~100 tokens each
- Rotate from the accepted pool, tagged by operation type and section type
- Quality gate: only include ACCEPTED_VERBATIM or MODIFIED with high similarity

**Implementation:**
- feedback-helper.py: new operation `get-examples --count 5 --diverse`
- suggest-prompt.md: "If `feedback/accepted-examples.md` exists, read it. These are examples of suggestions accepted by reviewers. Match this quality and style."

**What to measure:** Does acceptance rate improve after enabling few-shot? Compare 20-run window before vs after.

### 2b. Per-Section Accuracy with Statistical Rigor

**What:** Track acceptance rates per (doc, section). Adjust confidence thresholds.

**Statistical approach (from Opus + GPT consensus):**
- Minimum sample size: n ≥ 10 per section before affecting confidence
- Bayesian smoothing: `p_smoothed = (accepted + α) / (total + α + β)` with α=3, β=1 (75% prior)
- Hierarchical fallback: section → doc → global (use most specific level with sufficient data)
- Wilson lower bound for conservative estimates

**Confidence adjustment:**
- Wilson LB > 0.90 AND n ≥ 10 → allow CONFIDENT
- Wilson LB < 0.70 AND n ≥ 10 → cap at REVIEW
- Insufficient data → inherit parent level rate

**Implementation:**
- feedback-helper.py: `section-accuracy` operation returning JSON with rates and sample sizes
- suggest-prompt.md: read accuracy data, adjust confidence per section
- Store in `feedback/accuracy.json`

### 2c. Simplified FIND-Block Outcome Check

**What:** For merged PRs, classify per-suggestion outcomes using the simplified approach (from GLM — unanimously endorsed):

```python
if find_text in merged_doc:
    return "REJECTED"      # Original text still there
elif replace_text in merged_doc:
    return "ACCEPTED"      # Our replacement is there
else:
    return "MODIFIED"      # Section changed differently
```

80% accuracy, 20% complexity vs full diff comparison. Honest about uncertainty.

**When to implement:** After n ≥ 10 merged PRs. Requires reading the merged doc from the repo after merge — add to the feedback check.

---

## Phase 3: Human Curation (after n ≥ 50)

**Goal:** Enable human-curated quality controls based on accumulated data.

### 3a. Anti-Pattern Curation via CLI

**What:** `autodocs feedback add-antipattern "Don't suggest changes to internal function names in architecture docs"`

**Rules (from 6-model review):**
- Human-curated ONLY. Never auto-generated from rejection data (model poisoning risk).
- Maximum 10 entries.
- Each entry has a confidence score and last-seen date.
- Entries not triggered in 30 days are flagged for review.
- Stored in `feedback/rejected-patterns.md`, read by suggest prompt.

### 3b. Section Blocklist

**What:** Allow users to mark sections as "don't touch" — autodocs will never suggest changes to these.

```json
{
  "blocklist": [
    {"doc": "architecture.md", "section": "Internal Design Notes", "reason": "Maintained manually by tech lead"}
  ]
}
```

Simpler and safer than abstract anti-patterns (Opus recommendation).

### 3c. Weekly Digest

**What:** `feedback/weekly-digest.md` summarizing:
- PRs opened / merged / closed this week
- Acceptance rate trend (this week vs last 30 days vs all time)
- Modified suggestions (reviewer changed wording — review these for style patterns)
- Sections with lowest acceptance rates

Generated by the feedback check, no LLM call needed.

### 3d. Confidence Calibration

**What:** Track whether CONFIDENT suggestions are actually accepted more than REVIEW ones. If CONFIDENT is only accepted 70% of the time, the system is overconfident and thresholds should be raised (Opus recommendation).

```json
{
  "calibration": {
    "CONFIDENT": {"accepted": 40, "total": 45, "rate": 0.89},
    "REVIEW": {"accepted": 8, "total": 15, "rate": 0.53}
  }
}
```

---

## Phase 4: Prompt Evolution (after n ≥ 100)

**Goal:** The suggest prompt itself improves based on accumulated feedback.

### 4a. Versioned Prompts

**What:** Store multiple versions of the suggest prompt. Track which version produced which PRs. Compare acceptance rates across versions.

```
prompts/
├── suggest-prompt.v1.md     # Original
├── suggest-prompt.v2.md     # After Phase 2 learning
└── prompt-metadata.json      # Version → PR mapping → acceptance rates
```

### 4b. Meta-Prompting

**What:** Periodically (weekly), feed accuracy data + rejection examples to an LLM and ask it to suggest improvements to the suggest prompt. Human reviews and applies.

From OpenAI's Self-Evolving Agents cookbook: "A dedicated optimization agent rewrites the base prompt based on structured grader feedback."

### 4c. Style Learning

**What:** Track the edit distance between suggestions and final merged text. Detect systematic reviewer preferences (active vs passive voice, concise vs comprehensive, table format preferences).

From Gemini: "Style Drift Detection — measure Edit Distance between Suggestion and Final Merge."

---

## What We Explicitly Won't Build (and Why)

| Feature | Why not |
|---------|---------|
| Automated anti-pattern generation | Model poisoning risk (all 6 models agreed) |
| PR comment parsing (Layer 3) | Brittle NLP, noisy, redundant with merge state (5/6 agreed) |
| Full diff comparison for per-suggestion outcomes | Too complex, too many failure modes (all 6 agreed). Use simplified FIND-block check. |
| "Closed PR = rejected" as strong signal | PRs close for many reasons (duplicates, release freezes, vacations). Only treat as weak negative. |
| Reviewer identity tracking | Interesting but confounding. Defer until we have enough data to separate reviewer preference from suggestion quality. |

---

## Activation Triggers

| Phase | Trigger | Action |
|-------|---------|--------|
| Phase 1 → 2 | n ≥ 20 resolved PRs | Enable few-shot examples + per-section accuracy |
| Phase 2 → 3 | n ≥ 50 resolved PRs | Enable human curation tools + weekly digest |
| Phase 3 → 4 | n ≥ 100 resolved PRs | Enable prompt versioning + meta-prompting |
| Any phase | Acceptance rate < 70% for 2 consecutive weeks | Investigate: is the problem drift detection, suggestion quality, or prompt structure? |
| Any phase | Acceptance rate > 95% for 4 consecutive weeks | Focus on coverage (finding more drift) rather than accuracy |

---

## References

- [GitHub Copilot Metrics](https://resources.github.com/learn/pathways/copilot/essentials/measuring-the-impact-of-github-copilot/) — acceptance rate tracking, rejection training (23% → 78% improvement)
- [OpenAI Self-Evolving Agents](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining/) — versioned prompts, meta-prompting, grader-based optimization
- [Swimm Documentation](https://swimm.io/enterprise-documentation-platform) — acceptance rate, thumbs up/down, collaborative feedback
- [Few-Shot Prompt Optimization](https://arize.com/blog/prompt-optimization-few-shot-prompting/) — CPE, dynamic example selection, diversity constraints
- 6-SOTA-model adversarial review (Gemini, Opus, Grok, GPT, MiniMax, GLM) — see `review-synthesis-feedback-loop.md`
