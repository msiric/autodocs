# Shared helpers for integration tests

INTEGRATION_TEMPLATES="$BATS_TEST_DIRNAME/../templates"

setup_integration_env() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR

  # Create directories
  mkdir -p "$TEST_DIR/output" "$TEST_DIR/output/scripts" "$TEST_DIR/output/feedback"
  mkdir -p "$TEST_DIR/repo" "$TEST_DIR/bin" "$TEST_DIR/scenarios"

  # Init a git repo (sync.sh does git fetch)
  (cd "$TEST_DIR/repo" && git init -q)

  # Install mock claude
  cp "$BATS_TEST_DIRNAME/helpers/mock-claude.bash" "$TEST_DIR/bin/claude"
  chmod +x "$TEST_DIR/bin/claude"

  # Copy helper scripts
  cp "$BATS_TEST_DIRNAME/../scripts/"*.py "$TEST_DIR/output/scripts/" 2>/dev/null || true

  # Create minimal config
  cat > "$TEST_DIR/output/config.yaml" <<EOF
platform: github
github:
  owner: testuser
  repo: testrepo
owner:
  name: "Test User"
  github_username: "testuser"
team_members: []
relevant_paths:
  - src/
relevant_pattern: "test-feature"
docs:
  - name: "guide.md"
    package_map:
      auth: "Authentication"
last_verified: "2026-01-01"
EOF

  # Create stub prompt files (contain keywords the mock uses to identify calls)
  cat > "$TEST_DIR/output/sync-prompt.md" <<EOF
You are a work context summarizer. Test stub.
EOF
  cat > "$TEST_DIR/output/drift-prompt.md" <<EOF
You are a documentation drift detector. Test stub.
EOF
  cat > "$TEST_DIR/output/suggest-prompt.md" <<EOF
You are a documentation update advisor. Test stub.
EOF
  cat > "$TEST_DIR/output/apply-prompt.md" <<EOF
You are a documentation update applicator. Test stub.
EOF

  export MOCK_SCENARIO_DIR="$TEST_DIR/scenarios"
}

# Create a scenario directory with fixture files and exit codes
create_scenario() {
  local call="$1"
  local exit_code="${2:-0}"
  mkdir -p "$TEST_DIR/scenarios/$call"
  echo "$exit_code" > "$TEST_DIR/scenarios/$call.exit"
}

# Add a fixture file to a scenario
add_fixture() {
  local call="$1"
  local filename="$2"
  local content="$3"
  mkdir -p "$TEST_DIR/scenarios/$call"
  echo "$content" > "$TEST_DIR/scenarios/$call/$filename"
}

# Run sync.sh with the test environment
run_sync() {
  OUTPUT_DIR="$TEST_DIR/output" \
  REPO_DIR="$TEST_DIR/repo" \
  MOCK_SCENARIO_DIR="$TEST_DIR/scenarios" \
  PATH="$TEST_DIR/bin:$PATH" \
  bash "$INTEGRATION_TEMPLATES/sync.sh" "$@" 2>&1
}

# Read a field from sync-status.md
read_status() {
  grep "^$1:" "$TEST_DIR/output/sync-status.md" 2>/dev/null | awk '{print $2}'
}

# Standard success-path fixture helpers — compose as needed, override per test

create_sync_fixtures() {
  create_scenario sync 0
  add_fixture sync daily-report.md "---
date: 2026-03-05
sync_status: success
pr_count: 1
feature_prs: 1
---
# Work Report
## Team PRs (last 24h)
- PR #1: \"Test PR\" by Alice — merged
  API: YES (src/)
  Files:
    M src/auth/handler.ts
"
}

create_drift_fixtures() {
  create_scenario drift 0
  add_fixture drift drift-report.md "---
date: 2026-03-05
drift_alert_count: 1
drift_critical: 0
active_unresolved: 1
---
# Drift Report
## Today's Alerts
| Doc | Section | PRs | Confidence | What Changed |
| guide.md | Authentication | #1 | HIGH | Modified auth |
"
  add_fixture drift drift-status.md "# Active Drift Alerts
- [ ] 2026-03-05 | guide.md | Authentication | PR #1 | HIGH
"
}

create_suggest_fixtures() {
  create_scenario suggest 0
  add_fixture suggest drift-suggestions.md "---
date: 2026-03-05
suggestion_count: 1
verified: 1/1
---
# Suggested Updates
## guide.md — Authentication
**Confidence:** CONFIDENT
**Verified:** YES
"
}

teardown_integration_env() {
  rm -rf "$TEST_DIR"
}
