#!/usr/bin/env bats

load helpers/test-helpers

# --- Call 3 gating (suggest) ---

@test "call 3 runs when drift report has HIGH" {
  create_config
  create_drift_report
  touch "$TEST_DIR/suggest-prompt.md"

  DRIFT_STATUS="success"
  result=false
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$TEST_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$TEST_DIR/drift-report.md" 2>/dev/null; then
    result=true
  fi
  [ "$result" = "true" ]
}

@test "call 3 skips when drift report has no HIGH/CRITICAL" {
  create_config
  cat > "$TEST_DIR/drift-report.md" <<EOF
---
date: 2026-03-04
drift_alert_count: 0
---
# Drift Report
No documentation drift detected.
EOF
  touch "$TEST_DIR/suggest-prompt.md"

  DRIFT_STATUS="success"
  result=false
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$TEST_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$TEST_DIR/drift-report.md" 2>/dev/null; then
    result=true
  fi
  [ "$result" = "false" ]
}

@test "call 3 skips when drift failed" {
  create_config
  create_drift_report
  touch "$TEST_DIR/suggest-prompt.md"

  DRIFT_STATUS="failed"
  result=false
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$TEST_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$TEST_DIR/drift-report.md" 2>/dev/null; then
    result=true
  fi
  [ "$result" = "false" ]
}

# --- Call 3v gating (verify) ---

@test "call 3v runs when multi_model in config and CONFIDENT in suggestions" {
  create_config
  echo "multi_model:" >> "$TEST_DIR/config.yaml"
  echo "  enabled: true" >> "$TEST_DIR/config.yaml"
  create_suggestions

  SUGGEST_STATUS="success"
  result=false
  if grep -q "multi_model" "$TEST_DIR/config.yaml" 2>/dev/null \
     && grep -q "CONFIDENT" "$TEST_DIR/drift-suggestions.md" 2>/dev/null; then
    result=true
  fi
  [ "$result" = "true" ]
}

@test "call 3v skips when multi_model not in config" {
  create_config
  create_suggestions

  result=false
  if grep -q "multi_model" "$TEST_DIR/config.yaml" 2>/dev/null \
     && grep -q "CONFIDENT" "$TEST_DIR/drift-suggestions.md" 2>/dev/null; then
    result=true
  fi
  [ "$result" = "false" ]
}

# --- Call 4 gating (apply) ---

@test "call 4 runs when auto_pr in config and suggestions exist" {
  create_config
  echo "auto_pr:" >> "$TEST_DIR/config.yaml"
  echo "  enabled: true" >> "$TEST_DIR/config.yaml"
  create_suggestions
  touch "$TEST_DIR/apply-prompt.md"

  result=false
  if [ -f "$TEST_DIR/apply-prompt.md" ] \
     && grep -q "auto_pr" "$TEST_DIR/config.yaml" 2>/dev/null \
     && [ -f "$TEST_DIR/drift-suggestions.md" ] \
     && ! grep -q "suggestion_count: 0" "$TEST_DIR/drift-suggestions.md"; then
    result=true
  fi
  [ "$result" = "true" ]
}

@test "call 4 skips when auto_pr not in config" {
  create_config
  create_suggestions
  touch "$TEST_DIR/apply-prompt.md"

  result=false
  if [ -f "$TEST_DIR/apply-prompt.md" ] \
     && grep -q "auto_pr" "$TEST_DIR/config.yaml" 2>/dev/null \
     && [ -f "$TEST_DIR/drift-suggestions.md" ] \
     && ! grep -q "suggestion_count: 0" "$TEST_DIR/drift-suggestions.md"; then
    result=true
  fi
  [ "$result" = "false" ]
}

@test "call 4 skips when suggestion_count is 0" {
  create_config
  echo "auto_pr:" >> "$TEST_DIR/config.yaml"
  create_empty_suggestions
  touch "$TEST_DIR/apply-prompt.md"

  result=false
  if [ -f "$TEST_DIR/apply-prompt.md" ] \
     && grep -q "auto_pr" "$TEST_DIR/config.yaml" 2>/dev/null \
     && [ -f "$TEST_DIR/drift-suggestions.md" ] \
     && ! grep -q "suggestion_count: 0" "$TEST_DIR/drift-suggestions.md"; then
    result=true
  fi
  [ "$result" = "false" ]
}

@test "call 4 skips when suggestions file doesn't exist" {
  create_config
  echo "auto_pr:" >> "$TEST_DIR/config.yaml"
  touch "$TEST_DIR/apply-prompt.md"

  result=false
  if [ -f "$TEST_DIR/apply-prompt.md" ] \
     && grep -q "auto_pr" "$TEST_DIR/config.yaml" 2>/dev/null \
     && [ -f "$TEST_DIR/drift-suggestions.md" ] \
     && ! grep -q "suggestion_count: 0" "$TEST_DIR/drift-suggestions.md"; then
    result=true
  fi
  [ "$result" = "false" ]
}
