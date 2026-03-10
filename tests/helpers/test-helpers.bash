# Shared test helpers for autodocs BATS tests

# Create a temporary directory for each test
setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
}

# Clean up after each test
teardown() {
  rm -rf "$TEST_DIR"
}

# Create a minimal config file
create_config() {
  local platform="${1:-github}"
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: $platform

github:
  owner: "testuser"
  repo: "testrepo"

owner:
  name: "Test User"
  email: "test@example.com"
  github_username: "testuser"

team_members: []

relevant_paths:
  - src/

relevant_pattern: "test-feature"

last_verified: "2026-01-01"
EOF
}

# Create a minimal daily-report.md
create_daily_report() {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-04
sync_status: success
pr_count: ${1:-1}
feature_prs: ${2:-1}
owner_reviews: 0
owner_authored: ${2:-1}
anomaly_count: 0
---
# Work Report — 2026-03-04

## Team PRs (last 24h)
- PR #1: "Test PR" by Test User — merged
  Description: Test description
  API: YES (src/api/)
  Files: src/api/users.ts

## Owner Activity (Test User)
- Authored/Merged: PR #1
EOF
}

# Create a minimal drift-report.md with HIGH alerts
create_drift_report() {
  cat > "$TEST_DIR/drift-report.md" <<EOF
---
date: 2026-03-04
drift_alert_count: 1
drift_critical: 0
active_unresolved: 1
---
# Drift Report — 2026-03-04

## Today's Alerts

| Doc | Section | PRs | Confidence | What Changed |
|-----|---------|-----|------------|--------------|
| test-guide.md | API Endpoints | #1 | HIGH | Modified src/api/ |

## Active Unresolved
- 2026-03-04 | test-guide.md | API Endpoints | PR #1 | HIGH
EOF
}

# Create a minimal drift-suggestions.md
create_suggestions() {
  local count="${1:-1}"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
---
date: 2026-03-04
suggestion_count: $count
verified: $count/$count
---
# Suggested Updates — 2026-03-04

## test-guide.md — API Endpoints
**Triggered by:** PR #1 "Test PR"
**Confidence:** CONFIDENT

### FIND (in test-guide.md, section "API Endpoints"):
> GET /api/users — Returns all users

### REPLACE WITH:
> GET /api/users — Returns all users. Rate limited: 100 req/min.

**Verified:** YES — FIND text confirmed in doc (line 10)

### Reasoning:
PR #1 added rate limiting to the users endpoint.
EOF
}

# Create an empty suggestions file
create_empty_suggestions() {
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
---
date: 2026-03-04
suggestion_count: 0
---
# Suggested Updates — 2026-03-04

No new suggestions needed.
EOF
}

# Create a minimal drift-status.md
create_drift_status() {
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-04 | test-guide.md | API Endpoints | PR #1 | HIGH
- [x] 2026-03-01 | test-guide.md | Error Handling | PR #0 | HIGH | resolved
EOF
}
