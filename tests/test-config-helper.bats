#!/usr/bin/env bats

load helpers/test-helpers

HELPER="$BATS_TEST_DIRNAME/../scripts/config-helper.py"

# --- Fixtures ---

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  # Create a minimal github config
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: testuser
  repo: testrepo
owner:
  name: Test User
  github_username: testuser
team_members:
  - name: alice
    github_username: alice
  - name: bob
    github_username: bob
relevant_paths:
  - src/api/
  - src/auth/
docs:
  - name: guide.md
    repo_path: docs/guide.md
EOF
}

# ============================================================
# Team operations
# ============================================================

@test "list team prints member names" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team)
  echo "$result" | grep -q "alice"
  echo "$result" | grep -q "bob"
}

@test "list team on empty team returns nothing" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
team_members: []
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team)
  [ -z "$result" ]
}

@test "add team adds a member" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add team carol github_username carol
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team)
  echo "$result" | grep -q "carol"
}

@test "add team is idempotent" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add team alice github_username alice
  count=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team | grep -c "alice")
  [ "$count" -eq 1 ]
}

@test "remove team removes a member" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" remove team bob
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team)
  ! echo "$result" | grep -q "bob"
}

@test "remove team is idempotent" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" remove team nonexistent
  # Should not error, alice and bob still present
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list team)
  echo "$result" | grep -q "alice"
}

@test "has team returns 0 for existing member" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" has team alice
}

@test "has team returns 1 for non-existent member" {
  run python3 "$HELPER" "$TEST_DIR/config.yaml" has team nonexistent
  [ "$status" -eq 1 ]
}

@test "add team uses gitlab_username for gitlab platform" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: gitlab
team_members: []
EOF
  python3 "$HELPER" "$TEST_DIR/config.yaml" add team carol gitlab_username carol
  grep -q "gitlab_username: carol" "$TEST_DIR/config.yaml"
}

@test "add team uses ado_id for ado platform" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: ado
team_members: []
EOF
  python3 "$HELPER" "$TEST_DIR/config.yaml" add team carol ado_id "00000000-0000-0000-0000-000000000001"
  grep -q "ado_id" "$TEST_DIR/config.yaml"
}

# ============================================================
# Doc operations
# ============================================================

@test "list docs prints doc names" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list docs)
  echo "$result" | grep -q "guide.md"
}

@test "list docs on empty config returns nothing" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list docs)
  [ -z "$result" ]
}

@test "add doc adds a doc entry" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add doc api.md docs/api.md
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list docs)
  echo "$result" | grep -q "api.md"
}

@test "add doc is idempotent" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add doc guide.md docs/guide.md
  count=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list docs | grep -c "guide.md")
  [ "$count" -eq 1 ]
}

@test "remove doc removes a doc entry" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" remove doc guide.md
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list docs)
  ! echo "$result" | grep -q "guide.md"
}

@test "has doc returns 0 for existing doc" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" has doc guide.md
}

@test "has doc returns 1 for non-existent doc" {
  run python3 "$HELPER" "$TEST_DIR/config.yaml" has doc nonexistent.md
  [ "$status" -eq 1 ]
}

# ============================================================
# Path operations
# ============================================================

@test "list paths prints paths" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  echo "$result" | grep -q "src/api/"
  echo "$result" | grep -q "src/auth/"
}

@test "list paths on empty config returns nothing" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
relevant_paths: []
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  [ -z "$result" ]
}

@test "add path adds a path" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add path src/errors/
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  echo "$result" | grep -q "src/errors/"
}

@test "add path appends trailing slash if missing" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add path src/errors
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  echo "$result" | grep -q "src/errors/"
}

@test "add path is idempotent" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add path src/api/
  count=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths | grep -c "src/api/")
  [ "$count" -eq 1 ]
}

@test "remove path removes a path" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" remove path src/auth/
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  ! echo "$result" | grep -q "src/auth/"
}

@test "has path returns 0 for existing path" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" has path src/api/
}

@test "has path returns 1 for non-existent path" {
  run python3 "$HELPER" "$TEST_DIR/config.yaml" has path nonexistent/
  [ "$status" -eq 1 ]
}

# ============================================================
# Generic operations
# ============================================================

@test "get platform returns platform value" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" get platform)
  [ "$result" = "github" ]
}

@test "get returns empty for missing field" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" get nonexistent)
  [ -z "$result" ]
}

# ============================================================
# Edge cases
# ============================================================

@test "operations on missing config file fail gracefully" {
  run python3 "$HELPER" "$TEST_DIR/nonexistent.yaml" list team
  [ "$status" -eq 0 ]
}

@test "add preserves existing config fields" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" add team carol github_username carol
  # Platform should still be github
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" get platform)
  [ "$result" = "github" ]
  # Existing members should still be present
  python3 "$HELPER" "$TEST_DIR/config.yaml" has team alice
}

@test "remove preserves other entries" {
  python3 "$HELPER" "$TEST_DIR/config.yaml" remove team bob
  # alice should still be present
  python3 "$HELPER" "$TEST_DIR/config.yaml" has team alice
  # paths should be untouched
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" list paths)
  echo "$result" | grep -q "src/api/"
}
