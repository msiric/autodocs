#!/usr/bin/env bats

load helpers/test-helpers

HELPER="$BATS_TEST_DIRNAME/../scripts/stale-helper.py"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR

  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
docs:
  - name: "guide.md"
    repo_path: "docs/guide.md"
    package_map:
      auth: "Authentication"
stale_pr:
  warn_after_days: 14
  close_after_days: 21
  max_actions_per_run: 5
EOF

  # Create a mock doc file in a repo structure
  mkdir -p "$TEST_DIR/repo/docs"
  cat > "$TEST_DIR/repo/docs/guide.md" <<EOF
# Guide
## Authentication
All endpoints require auth via Bearer token.
EOF
}

# ============================================================
# SUPERSEDED detection
# ============================================================

@test "detects superseded PR when newer PR covers same sections" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Authentication"}]},
  {"pr_number": 8, "date": "2026-03-05", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Authentication"}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  echo "$result" | grep -q "5|close|Superseded"
  ! echo "$result" | grep -q "^8|"
}

@test "does not supersede when sections differ" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Authentication"}]},
  {"pr_number": 8, "date": "2026-03-05", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Error Handling"}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  [ -z "$result" ]
}

@test "does not supersede when suggestions are empty" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open", "suggestions": []},
  {"pr_number": 8, "date": "2026-03-05", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Authentication"}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  [ -z "$result" ]
}

# ============================================================
# EXPIRED_FIND detection
# ============================================================

@test "detects expired FIND when text no longer in doc" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Auth", "find_text": "This text does not exist in the doc"}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  echo "$result" | grep -q "5|close|All FIND texts"
}

@test "does not expire when FIND text still matches" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Auth", "find_text": "All endpoints require auth via Bearer token."}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  [ -z "$result" ]
}

@test "does not expire when no find_text in suggestions" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 5, "date": "2026-03-01", "state": "open",
   "suggestions": [{"doc": "guide.md", "section": "Auth"}]}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-06")
  [ -z "$result" ]
}

# ============================================================
# AGE-based two-phase (warn then close)
# ============================================================

@test "warns at warn_after_days when no stale label" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number": 5, "date": "2026-02-15", "state": "open", "suggestions": []}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  echo "$result" | grep -q "5|warn|"
}

@test "closes at close_after_days when stale label present" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number": 5, "date": "2026-02-10", "state": "open", "suggestions": []}]
EOF
  # Pass stale_labels as JSON: {5: true}
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05" '{"5": true}')
  echo "$result" | grep -q "5|close|"
}

@test "does not warn before warn_after_days" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number": 5, "date": "2026-03-01", "state": "open", "suggestions": []}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  [ -z "$result" ]
}

# ============================================================
# Limits and edge cases
# ============================================================

@test "respects max_actions_per_run" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
docs: []
stale_pr:
  warn_after_days: 1
  max_actions_per_run: 2
EOF
  cat > "$TEST_DIR/open-prs.json" <<EOF
[
  {"pr_number": 1, "date": "2026-01-01", "state": "open", "suggestions": []},
  {"pr_number": 2, "date": "2026-01-01", "state": "open", "suggestions": []},
  {"pr_number": 3, "date": "2026-01-01", "state": "open", "suggestions": []}
]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  count=$(echo "$result" | grep -c "|")
  [ "$count" -eq 2 ]
}

@test "skips closed PRs" {
  cat > "$TEST_DIR/open-prs.json" <<EOF
[{"pr_number": 5, "date": "2026-01-01", "state": "closed", "suggestions": []}]
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  [ -z "$result" ]
}

@test "handles empty open-prs.json" {
  echo "[]" > "$TEST_DIR/open-prs.json"
  result=$(python3 "$HELPER" "$TEST_DIR/open-prs.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  [ -z "$result" ]
}

@test "handles missing open-prs.json" {
  result=$(python3 "$HELPER" "$TEST_DIR/nonexistent.json" "$TEST_DIR/config.yaml" "$TEST_DIR/repo" list-stale "2026-03-05")
  [ -z "$result" ]
}
