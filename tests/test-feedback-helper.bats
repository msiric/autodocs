#!/usr/bin/env bats

load helpers/test-helpers

HELPER="$BATS_TEST_DIRNAME/../scripts/feedback-helper.py"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  # Create a feedback file with sample data
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {
    "pr_number": 4,
    "platform": "github",
    "date": "2026-03-05",
    "state": "open",
    "suggestions": [
      {"doc": "architecture.md", "section": "Error Handling", "type": "REPLACE"},
      {"doc": "architecture.md", "section": "API Endpoints", "type": "INSERT AFTER"}
    ]
  },
  {
    "pr_number": 2,
    "platform": "github",
    "date": "2026-03-04",
    "state": "merged",
    "merged_date": "2026-03-04",
    "suggestions": [
      {"doc": "architecture.md", "section": "Authentication", "type": "REPLACE"}
    ]
  }
]
EOF
}

# ============================================================
# PR tracking operations
# ============================================================

@test "add-pr adds a new PR entry" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" add-pr 5 github 2026-03-06 '[{"doc":"guide.md","section":"Intro","type":"REPLACE"}]'
  python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 5
}

@test "add-pr is idempotent" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" add-pr 4 github 2026-03-05 '[]'
  count=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs | grep -c "^4$")
  [ "$count" -eq 1 ]
}

@test "list-prs shows all PR numbers" {
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs)
  echo "$result" | grep -q "^4$"
  echo "$result" | grep -q "^2$"
}

@test "list-prs --open-only filters to open state" {
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs --open-only)
  echo "$result" | grep -q "^4$"
  ! echo "$result" | grep -q "^2$"
}

@test "has-pr returns 0 for existing PR" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 4
}

@test "has-pr returns 1 for non-existent PR" {
  run python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 999
  [ "$status" -eq 1 ]
}

@test "update-pr changes state to merged" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" update-pr 4 merged 2026-03-06
  # Should no longer appear in --open-only
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs --open-only)
  ! echo "$result" | grep -q "^4$"
}

@test "update-pr changes state to closed" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" update-pr 4 closed
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs --open-only)
  ! echo "$result" | grep -q "^4$"
}

@test "update-pr on non-existent PR is no-op" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" update-pr 999 merged 2026-03-06
  # Should not add PR 999
  run python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 999
  [ "$status" -eq 1 ]
}

# ============================================================
# Pending sections (deduplication support)
# ============================================================

@test "pending-sections returns open PR sections" {
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" pending-sections)
  echo "$result" | grep -q "architecture.md|Error Handling"
  echo "$result" | grep -q "architecture.md|API Endpoints"
}

@test "pending-sections excludes merged PRs" {
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" pending-sections)
  ! echo "$result" | grep -q "architecture.md|Authentication"
}

@test "pending-sections excludes closed PRs" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" update-pr 4 closed
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" pending-sections)
  [ -z "$result" ]
}

# ============================================================
# Acceptance rate
# ============================================================

@test "acceptance-rate with all merged returns 1.0" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number":1,"state":"merged"},{"pr_number":2,"state":"merged"}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" acceptance-rate)
  [[ "$result" == 1.00* ]]
  [[ "$result" == *"2 merged"* ]]
}

@test "acceptance-rate with mixed returns correct ratio" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number":1,"state":"merged"},{"pr_number":2,"state":"closed"},{"pr_number":3,"state":"merged"}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" acceptance-rate)
  [[ "$result" == 0.67* ]]
  [[ "$result" == *"2 merged"* ]]
  [[ "$result" == *"1 rejected"* ]]
}

@test "acceptance-rate with no resolved data returns n/a" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number":1,"state":"open"}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" acceptance-rate)
  [ "$result" = "n/a" ]
}

@test "acceptance-rate excludes open PRs" {
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" acceptance-rate)
  # Only PR #2 is resolved (merged). PR #4 is open. Rate = 1/1 = 1.00
  [[ "$result" == 1.00* ]]
}

@test "acceptance-rate excludes auto-closed PRs from rejection count" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number":1,"state":"merged"},
  {"pr_number":2,"state":"closed","close_reason":"superseded"},
  {"pr_number":3,"state":"closed","close_reason":"expired_find"},
  {"pr_number":4,"state":"closed","close_reason":"age_stale"},
  {"pr_number":5,"state":"closed","close_reason":"changes_applied"},
  {"pr_number":6,"state":"closed"}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" acceptance-rate)
  # 1 merged, 1 human-rejected (#6, no close_reason), 4 auto-closed
  [[ "$result" == 0.50* ]]
  [[ "$result" == *"1 merged"* ]]
  [[ "$result" == *"1 rejected"* ]]
  [[ "$result" == *"4 auto-closed"* ]]
}

# ============================================================
# Edge cases
# ============================================================

@test "operations on missing file create it" {
  python3 "$HELPER" "$TEST_DIR/new-file.json" add-pr 1 github 2026-03-01 '[]'
  [ -f "$TEST_DIR/new-file.json" ]
  python3 "$HELPER" "$TEST_DIR/new-file.json" has-pr 1
}

@test "add-pr preserves existing entries" {
  python3 "$HELPER" "$TEST_DIR/open-prs.json" add-pr 10 github 2026-03-10 '[]'
  # Original entries should still exist
  python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 4
  python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 2
  python3 "$HELPER" "$TEST_DIR/open-prs.json" has-pr 10
}

@test "list-prs on empty file returns nothing" {
  echo "[]" > "$TEST_DIR/open-prs.json"
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" list-prs)
  [ -z "$result" ]
}
