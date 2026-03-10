#!/usr/bin/env bats

load helpers/test-helpers

# --- daily-report.md schema ---

@test "daily report has YAML frontmatter delimiters" {
  create_daily_report
  head -1 "$TEST_DIR/daily-report.md" | grep -q "^---$"
  grep -c "^---$" "$TEST_DIR/daily-report.md" | grep -q "2"
}

@test "daily report has required frontmatter fields" {
  create_daily_report
  grep -q "^date:" "$TEST_DIR/daily-report.md"
  grep -q "^sync_status:" "$TEST_DIR/daily-report.md"
  grep -q "^pr_count:" "$TEST_DIR/daily-report.md"
  grep -q "^feature_prs:" "$TEST_DIR/daily-report.md"
  grep -q "^owner_reviews:" "$TEST_DIR/daily-report.md"
  grep -q "^owner_authored:" "$TEST_DIR/daily-report.md"
}

@test "daily report has Team PRs section" {
  create_daily_report
  grep -q "## Team PRs" "$TEST_DIR/daily-report.md"
}

@test "daily report has Owner Activity section" {
  create_daily_report
  grep -q "## Owner Activity" "$TEST_DIR/daily-report.md"
}

# --- drift-report.md schema ---

@test "drift report has required frontmatter fields" {
  create_drift_report
  grep -q "^date:" "$TEST_DIR/drift-report.md"
  grep -q "^drift_alert_count:" "$TEST_DIR/drift-report.md"
  grep -q "^drift_critical:" "$TEST_DIR/drift-report.md"
  grep -q "^active_unresolved:" "$TEST_DIR/drift-report.md"
}

@test "drift report has Today's Alerts section" {
  create_drift_report
  grep -q "## Today's Alerts" "$TEST_DIR/drift-report.md"
}

@test "drift report has Active Unresolved section" {
  create_drift_report
  grep -q "## Active Unresolved" "$TEST_DIR/drift-report.md"
}

# --- drift-suggestions.md schema ---

@test "suggestions have verified count in frontmatter" {
  create_suggestions
  grep -q "^verified:" "$TEST_DIR/drift-suggestions.md"
}

@test "suggestions have suggestion_count in frontmatter" {
  create_suggestions
  grep -q "^suggestion_count:" "$TEST_DIR/drift-suggestions.md"
}

@test "suggestions have FIND block" {
  create_suggestions
  grep -q "### FIND" "$TEST_DIR/drift-suggestions.md"
}

@test "suggestions have Verified status" {
  create_suggestions
  grep -q "Verified:" "$TEST_DIR/drift-suggestions.md"
}

# --- drift-status.md schema ---

@test "drift status has checkbox format" {
  create_drift_status
  grep -q "^\- \[ \]" "$TEST_DIR/drift-status.md"
}

@test "drift status unchecked entries come before checked" {
  create_drift_status
  first_unchecked=$(grep -n "^\- \[ \]" "$TEST_DIR/drift-status.md" | head -1 | cut -d: -f1)
  last_checked=$(grep -n "^\- \[x\]" "$TEST_DIR/drift-status.md" | tail -1 | cut -d: -f1)
  [ "$first_unchecked" -lt "$last_checked" ]
}
