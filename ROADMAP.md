# Roadmap

## Phase 1: Zero-friction onboarding (This week)

**Goal:** Any team can go from zero docs to working autodocs in under 5 minutes.

### `autodocs generate` command
- [ ] Generate prompt template (`generate-prompt.md`) that reads repo structure and source files, writes a structured architecture doc
- [ ] Deterministic file discovery + structure analysis (extend `setup.sh analyze`)
- [ ] Auto-generate `config.yaml` with package_map pre-filled from the doc's sections
- [ ] Output doc has `## ` sections immediately compatible with maintenance mode

**Target onboarding flow:**
```bash
cd your-repo
setup.sh --quick        # auto-detect platform, owner, team
setup.sh generate       # write initial doc from codebase
autodocs-now            # first maintenance run
```

---

## Phase 2: Internal adoption (Week 2)

**Goal:** 3 Microsoft teams actively using autodocs with real PRs.

### Deploy to 3 teams
- [ ] Small team: 5-10 people, single repo, one feature area
- [ ] Medium team: 10-20 people, monorepo, 2-3 feature areas
- [ ] Stale-docs team: existing docs they know are out of date

### Metrics to collect
- [ ] Setup time (end-to-end)
- [ ] Suggestions per run
- [ ] Acceptance rate (merged vs closed autodocs PRs)
- [ ] Edit distance (what reviewers change before merging)
- [ ] PR review latency (do teams actually review, or do PRs pile up?)

---

## Phase 3: Monorepo support (Weeks 3-4)

**Goal:** autodocs works efficiently in large monorepos where each team tracks their own code.

### Path-based webhook filtering
- [ ] Webhook server checks changed files against `relevant_paths` before triggering pipeline
- [ ] Skip irrelevant PRs without LLM cost (return `{"status": "ignored"}`)

### Team scope config (if validated by Phase 2 feedback)
- [ ] Named scopes in config: each scope has its own doc, paths, package_map
- [ ] Pipeline processes each scope independently within one run
- [ ] Single output directory per team, multiple scopes per config

### Run trigger improvements
- [ ] Label-based filtering: only run when PRs have specific labels
- [ ] Branch prefix filtering: only run for PRs from specific branch patterns

---

## Phase 4: Feedback loop (Weeks 5-6)

**Activation threshold:** ≥20 resolved PRs across all teams.

### Few-shot examples from accepted suggestions
- [ ] `feedback-helper.py get-examples --count 5 --diverse` operation
- [ ] Select examples stratified by operation type (REPLACE, INSERT AFTER, table update)
- [ ] Prefer reviewer-modified suggestions (the delta is the learning signal)
- [ ] Add to suggest prompt: "These are examples of accepted suggestions. Match this quality."

### Per-section accuracy tracking
- [ ] Track acceptance rate per (doc, section)
- [ ] Surface sections with low acceptance as config recommendations
- [ ] Bayesian smoothing with minimum sample size (n≥10) before affecting confidence

### Confidence calibration
- [ ] Track whether CONFIDENT suggestions are actually accepted more than REVIEW
- [ ] If CONFIDENT acceptance rate <70%, thresholds are too loose

---

## Future (after Phase 4 validation)

### Historical changelog backfill
- `--changelog-only` flag for catchup mode: build changelog from PR history without modifying the doc
- Pairs with `autodocs generate`: generate doc from current state, then backfill changelog from history

### Multi-model support
- `OpenAIRunner` in `llm_runner.py` for Azure OpenAI / GPT-4
- Prompt adaptation for different tool-calling formats
- Only needed for external customers or teams without Claude access

### Dashboard
- Read-only web view of drift status, suggestion history, acceptance trends
- Build after we know what metrics matter from Phase 2-4 data

### CODEOWNERS integration
- Parse `.github/CODEOWNERS`, map changed files to owning teams
- Auto-trigger the correct team's autodocs instance
- Only needed at scale (20+ teams)

### Doc generation modes
- **Snapshot:** Generate from current codebase state (fast, cheap, one LLM call)
- **Historical replay:** Walk PRs chronologically to build docs + changelog (accurate but expensive)
- **Hybrid:** Snapshot for doc content, replay for changelog only (recommended)

---

## Completed

### Architecture transformation
- [x] Bash → Python orchestrator (sync.sh 585 → 23 lines)
- [x] Deterministic sync engine (no LLM for PR fetching/classification)
- [x] Deterministic apply engine (no LLM for FIND/REPLACE/git/PR creation)
- [x] Multi-backend LLM runner (CLI + API with agentic Read/Write loop)
- [x] Storage abstraction (LocalStorage with atomic writes, path traversal protection)
- [x] Pipeline lock in Python (protects all entry points)
- [x] Webhook server (FastAPI, GitHub/GitLab/Bitbucket support)

### Quality improvements
- [x] Three-layer verification (LLM self-check + FIND verify + REPLACE verify)
- [x] Changelog append-only merge (two-layer PR-number dedup)
- [x] LLM artifact post-processing (note stripping, duplicate header removal, blank line collapse)
- [x] Cross-reference check in suggest prompt
- [x] Review thread fetching from all 4 platforms
- [x] Error classification (retryable vs permanent)
- [x] Config schema validation

### Testing & infrastructure
- [x] 126 pytest + 249 BATS = 375 tests
- [x] CI workflow (GitHub Actions: pytest + BATS on push/PR)
- [x] End-to-end validated against autodocs-demo repo
- [x] pyproject.toml with dependency groups
- [x] Zero-question `--quick` setup mode with auto-detection

### Documentation
- [x] README reflects current architecture
- [x] Architecture doc with pipeline diagram and call isolation table
- [x] Configuration reference with all config sections
- [x] Troubleshooting guide with current error messages
- [x] CHANGELOG.md with migration instructions
