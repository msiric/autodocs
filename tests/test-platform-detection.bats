#!/usr/bin/env bats

load helpers/test-helpers

# --- Platform detection (extracted from sync.sh) ---

extract_platform() {
  grep "^platform:" "$1" 2>/dev/null | awk '{print $2}' | tr -d '"'
}

@test "extracts github from config" {
  echo "platform: github" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "github" ]
}

@test "extracts ado from config" {
  echo "platform: ado" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "ado" ]
}

@test "extracts gitlab from config" {
  echo "platform: gitlab" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "gitlab" ]
}

@test "extracts bitbucket from config" {
  echo "platform: bitbucket" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "bitbucket" ]
}

@test "handles quoted platform value" {
  echo 'platform: "github"' > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "github" ]
}

@test "returns empty for missing config" {
  result=$(extract_platform "$TEST_DIR/nonexistent.yaml")
  [ -z "$result" ]
}

@test "returns empty for config without platform" {
  echo "owner: test" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ -z "$result" ]
}

@test "ignores commented platform line" {
  printf "# platform: github\nplatform: ado\n" > "$TEST_DIR/config.yaml"
  result=$(extract_platform "$TEST_DIR/config.yaml")
  [ "$result" = "ado" ]
}
