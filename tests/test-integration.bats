#!/usr/bin/env bats

load helpers/integration-helpers

setup() {
  setup_integration_env
}

teardown() {
  teardown_integration_env
}

# ============================================================
# Full pipeline
# ============================================================

@test "full pipeline success writes all stages as success" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures
  create_scenario verify 0
  create_scenario apply 0
  # Enable multi_model + auto_pr for full pipeline
  cat >> "$TEST_DIR/output/config.yaml" <<EOF
multi_model:
  enabled: true
auto_pr:
  enabled: true
  target_branch: main
  branch_prefix: autodocs/
EOF

  run run_sync
  [ "$status" -eq 0 ]
  [ "$(read_status status)" = "success" ]
  [ "$(read_status drift)" = "success" ]
  [ "$(read_status suggest)" = "success" ]
  # Verify is now shadow mode (logs but doesn't gate)
  verify_status=$(read_status verify)
  [[ "$verify_status" == "shadow-success" || "$verify_status" == "skipped" ]]
  [ "$(read_status apply)" = "success" ]
}

# ============================================================
# Call gating
# ============================================================

@test "sync with no PRs produces partial report and skips drift alerts" {
  # No sync fixtures = no fetched-prs.json = partial report
  run run_sync
  [ "$(read_status status)" = "success" ]
  # Drift runs but finds no alerts (no PRs in partial report)
  grep -q "pr_count: 0" "$TEST_DIR/output/daily-report.md"
}

@test "call 2 failure skips suggest and apply" {
  create_sync_fixtures
  create_scenario drift 1

  run run_sync
  [ "$(read_status status)" = "success" ]
  [ "$(read_status drift)" = "failed" ]
  [ "$(read_status suggest)" = "skipped" ]
}

@test "no HIGH/CRITICAL alerts skips suggest" {
  create_sync_fixtures
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 1
---
# Drift Report
## Today's Alerts
| Doc | Section | PRs | Confidence | What Changed |
| guide.md | Auth | #1 | LOW | Manual review |
"

  run run_sync
  [ "$(read_status drift)" = "success" ]
  [ "$(read_status suggest)" = "skipped" ]
}

@test "no CONFIDENT suggestions skips verify" {
  create_sync_fixtures
  create_drift_fixtures
  create_scenario suggest 0
  add_fixture suggest drift-suggestions.md "---
date: 2026-03-05
suggestion_count: 1
---
# Suggested Updates
**Confidence:** REVIEW
"
  echo "multi_model:
  enabled: true" >> "$TEST_DIR/output/config.yaml"

  run run_sync
  [ "$(read_status suggest)" = "success" ]
  [ "$(read_status verify)" = "skipped" ]
}

@test "no multi_model config skips verify" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures

  run run_sync
  [ "$(read_status suggest)" = "success" ]
  [ "$(read_status verify)" = "skipped" ]
}

@test "suggestion_count 0 skips apply" {
  create_sync_fixtures
  create_drift_fixtures
  create_scenario suggest 0
  add_fixture suggest drift-suggestions.md "---
date: 2026-03-05
suggestion_count: 0
---
No suggestions.
"
  echo "auto_pr:
  enabled: true
  target_branch: main" >> "$TEST_DIR/output/config.yaml"

  run run_sync
  [ "$(read_status suggest)" = "success" ]
  [ "$(read_status apply)" = "skipped" ]
}

@test "no auto_pr config skips apply" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures

  run run_sync
  [ "$(read_status suggest)" = "success" ]
  [ "$(read_status apply)" = "skipped" ]
}

# ============================================================
# Match helper integration
# ============================================================

@test "match helper creates resolved-mappings.md" {
  # Provide pre-fetched PR data for deterministic sync
  # Use a recent date so the PR is within the lookback window
  RECENT=$(date -u -v-1d +"%Y-%m-%dT12:00:00Z" 2>/dev/null || date -u -d "1 day ago" +"%Y-%m-%dT12:00:00Z")
  cat > "$TEST_DIR/output/webhook-prs.json" <<PREOF
[{"number":1,"title":"Test PR","body":"","mergedAt":"${RECENT}","mergeCommit":{"oid":"abc123"},"files":[{"path":"src/auth/handler.ts","additions":5,"deletions":2}],"author":{"login":"testuser"},"reviews":[]}]
PREOF
  # Set lookback to cover the PR
  echo "2026-01-01T00:00:00Z" > "$TEST_DIR/output/last-successful-run"
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 0
---
No drift.
"

  run run_sync
  [ -f "$TEST_DIR/output/resolved-mappings.md" ]
  grep -q "src/auth/handler.ts" "$TEST_DIR/output/resolved-mappings.md"
}

# ============================================================
# Lock mechanism
# ============================================================

@test "lock prevents concurrent runs" {
  mkdir -p "$TEST_DIR/output/.sync.lock"

  run run_sync
  [ "$status" -eq 0 ]
  grep -q "SKIPPED" "$TEST_DIR/output/sync.log"
  [ ! -f "$TEST_DIR/output/sync-status.md" ]
}

# ============================================================
# Auth failure
# ============================================================

@test "auth failure writes error status" {
  echo "1" > "$TEST_DIR/scenarios/auth.exit"

  run run_sync
  [ "$status" -eq 1 ]
  grep -q "Claude Code auth expired" "$TEST_DIR/output/sync-status.md"
  grep -q "AUTH FAILED" "$TEST_DIR/output/sync.log"
}

# ============================================================
# Feedback loop
# ============================================================

@test "feedback check updates merged PR state" {
  cat > "$TEST_DIR/output/feedback/open-prs.json" <<EOF
[{"pr_number": 5, "platform": "github", "date": "2026-03-04", "state": "open", "suggestions": []}]
EOF
  cat > "$TEST_DIR/bin/gh" <<'GHEOF'
#!/bin/bash
echo "MERGED"
GHEOF
  chmod +x "$TEST_DIR/bin/gh"

  create_sync_fixtures
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 0
---
No drift.
"

  run run_sync

  state=$(python3 -c "import json;d=json.load(open('$TEST_DIR/output/feedback/open-prs.json'));print(d[0]['state'])")
  [ "$state" = "merged" ]
  grep -q "FEEDBACK: PR #5 merged" "$TEST_DIR/output/sync.log"
}

# ============================================================
# Missing prompt file
# ============================================================

@test "missing drift-prompt.md gracefully skips drift" {
  rm "$TEST_DIR/output/drift-prompt.md"
  create_sync_fixtures

  run run_sync
  [ "$(read_status status)" = "success" ]
  [ "$(read_status drift)" = "skipped" ]
}

# ============================================================
# Dry-run mode
# ============================================================

@test "dry-run skips apply and writes dry-run status" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures
  echo "auto_pr:
  enabled: true
  target_branch: main" >> "$TEST_DIR/output/config.yaml"

  run run_sync --dry-run
  [ "$(read_status suggest)" = "success" ]
  [ "$(read_status apply)" = "dry-run" ]
  grep -q "DRY RUN" "$TEST_DIR/output/sync.log"
}

# ============================================================
# Date computation + lookback
# ============================================================

@test "current-date.txt and lookback-date.txt are written before sync" {
  create_sync_fixtures
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 0
---
No drift.
"

  run run_sync
  [ -f "$TEST_DIR/output/current-date.txt" ]
  [ -f "$TEST_DIR/output/lookback-date.txt" ]
  # Current date should be today
  today=$(date -u +"%Y-%m-%d")
  [ "$(cat "$TEST_DIR/output/current-date.txt")" = "$today" ]
}

@test "last-successful-run written on success with relevant PRs" {
  create_sync_fixtures
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 0
---
No drift.
"

  run run_sync
  [ -f "$TEST_DIR/output/last-successful-run" ]
}

# ============================================================
# Source context + match rate
# ============================================================

@test "source-context directory created during suggest phase" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures

  run run_sync
  [ -d "$TEST_DIR/output/source-context" ]
}

@test "match rate logged to metrics" {
  create_sync_fixtures
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 0
---
No drift.
"

  run run_sync
  [ -f "$TEST_DIR/output/metrics.jsonl" ]
  grep -q "match-rate" "$TEST_DIR/output/metrics.jsonl"
}

# ============================================================
# Metrics logging
# ============================================================

@test "metrics logged for each pipeline stage" {
  create_sync_fixtures
  create_drift_fixtures
  create_suggest_fixtures

  run run_sync
  [ -f "$TEST_DIR/output/metrics.jsonl" ] || { echo "metrics.jsonl missing"; echo "log:"; cat "$TEST_DIR/output/sync.log" 2>/dev/null; false; }
  grep -q '"call": "sync"' "$TEST_DIR/output/metrics.jsonl" || grep -q '"call":"sync"' "$TEST_DIR/output/metrics.jsonl"
  grep -q '"call": "drift"' "$TEST_DIR/output/metrics.jsonl" || grep -q '"call":"drift"' "$TEST_DIR/output/metrics.jsonl"
  grep -q '"call": "suggest"' "$TEST_DIR/output/metrics.jsonl" || grep -q '"call":"suggest"' "$TEST_DIR/output/metrics.jsonl"
}

# ============================================================
# Open PR limit
# ============================================================

@test "open PR limit skips sync when too many PRs" {
  # Create feedback with many open PRs
  mkdir -p "$TEST_DIR/output/feedback"
  python3 -c "
import json
prs = [{'pr_number': i, 'state': 'open', 'platform': 'github', 'date': '2026-03-01', 'suggestions': []} for i in range(1, 15)]
json.dump(prs, open('$TEST_DIR/output/feedback/open-prs.json', 'w'))
"
  # Set limit low
  echo "limits:" >> "$TEST_DIR/output/config.yaml"
  echo "  max_open_prs: 5" >> "$TEST_DIR/output/config.yaml"

  create_scenario sync 0

  run run_sync
  [ "$status" -eq 0 ]
  grep -q "open PR limit" "$TEST_DIR/output/sync-status.md"
  grep -q "skipped" "$TEST_DIR/output/sync-status.md"
}
