#!/usr/bin/env bats

load helpers/test-helpers

@test "github config has required fields" {
  create_config "github"
  grep -q "^platform:" "$TEST_DIR/config.yaml"
  grep -q "owner:" "$TEST_DIR/config.yaml"
  grep -q "repo:" "$TEST_DIR/config.yaml"
}

@test "ado config example has required fields" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: ado
ado:
  org: "testorg"
  project: "testproject"
  repo: "testrepo"
  repo_id: "00000000-0000-0000-0000-000000000000"
owner:
  name: "Test"
  ado_id: "00000000-0000-0000-0000-000000000000"
EOF
  grep -q "^platform: ado" "$TEST_DIR/config.yaml"
  grep -q "org:" "$TEST_DIR/config.yaml"
  grep -q "project:" "$TEST_DIR/config.yaml"
  grep -q "repo_id:" "$TEST_DIR/config.yaml"
}

@test "gitlab config has required fields" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: gitlab
gitlab:
  host: "gitlab.com"
  project_path: "group/repo"
owner:
  name: "Test"
  gitlab_username: "testuser"
EOF
  grep -q "^platform: gitlab" "$TEST_DIR/config.yaml"
  grep -q "project_path:" "$TEST_DIR/config.yaml"
  grep -q "gitlab_username:" "$TEST_DIR/config.yaml"
}

@test "bitbucket config has required fields" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: bitbucket
bitbucket:
  workspace: "myworkspace"
  repo: "myrepo"
owner:
  name: "Test"
  bitbucket_username: "testuser"
EOF
  grep -q "^platform: bitbucket" "$TEST_DIR/config.yaml"
  grep -q "workspace:" "$TEST_DIR/config.yaml"
  grep -q "bitbucket_username:" "$TEST_DIR/config.yaml"
}

@test "auto_pr config has target_branch when enabled" {
  create_config
  cat >> "$TEST_DIR/config.yaml" <<EOF
auto_pr:
  enabled: true
  target_branch: "main"
  branch_prefix: "autodocs/"
EOF
  grep -q "target_branch:" "$TEST_DIR/config.yaml"
  grep -q "branch_prefix:" "$TEST_DIR/config.yaml"
}

@test "relevant_paths is a list" {
  create_config
  grep -q "relevant_paths:" "$TEST_DIR/config.yaml"
  grep -q "  - src/" "$TEST_DIR/config.yaml"
}

# ============================================================
# read_config function (mirrors sync.sh's read_config)
# ============================================================

# Define read_config for testing — same logic as sync.sh
_read_config() {
  local config_path="$1"
  local key="$2"
  python3 -c "
import yaml, sys
c = yaml.safe_load(open(sys.argv[1]))
keys = sys.argv[2].split('.')
v = c
for k in keys:
    v = v.get(k, '') if isinstance(v, dict) else ''
print('true' if v is True else 'false' if v is False else v)
" "$config_path" "$key" 2>/dev/null
}

@test "read_config returns simple top-level value" {
  create_config "github"
  result=$(_read_config "$TEST_DIR/config.yaml" "platform")
  [ "$result" = "github" ]
}

@test "read_config returns dotted nested value" {
  create_config "github"
  result=$(_read_config "$TEST_DIR/config.yaml" "github.owner")
  [ "$result" = "testuser" ]
}

@test "read_config returns true for boolean true" {
  create_config
  cat >> "$TEST_DIR/config.yaml" <<EOF
telemetry:
  enabled: true
EOF
  result=$(_read_config "$TEST_DIR/config.yaml" "telemetry.enabled")
  [ "$result" = "true" ]
}

@test "read_config returns false for boolean false" {
  create_config
  cat >> "$TEST_DIR/config.yaml" <<EOF
telemetry:
  enabled: false
EOF
  result=$(_read_config "$TEST_DIR/config.yaml" "telemetry.enabled")
  [ "$result" = "false" ]
}

@test "read_config returns empty for missing key" {
  create_config
  result=$(_read_config "$TEST_DIR/config.yaml" "nonexistent.key")
  [ -z "$result" ]
}

@test "read_config returns empty for missing config file" {
  result=$(_read_config "$TEST_DIR/nonexistent.yaml" "platform" || true)
  [ -z "$result" ]
}

# ============================================================
# Schema validation (schema-helper.py)
# ============================================================

SCHEMA_HELPER="$BATS_TEST_DIRNAME/../scripts/schema_helper.py"

@test "schema: valid github config passes" {
  create_config "github"
  python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
}

@test "schema: valid gitlab config passes" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: gitlab
gitlab:
  project_path: "group/repo"
EOF
  python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
}

@test "schema: valid bitbucket config passes" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: bitbucket
bitbucket:
  workspace: "myws"
  repo: "myrepo"
EOF
  python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
}

@test "schema: valid ado config passes" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: ado
ado:
  org: "myorg"
  project: "myproj"
EOF
  python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
}

@test "schema: missing platform fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
github:
  owner: "test"
  repo: "test"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "missing required field: platform"
}

@test "schema: invalid platform value fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: svn
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "platform must be one of"
}

@test "schema: missing github.owner fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  repo: "myrepo"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "github.owner"
}

@test "schema: missing github block entirely fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "github.owner"
}

@test "schema: docs as string fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
docs: "not a list"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "docs must be a list"
}

@test "schema: docs entry missing name fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
docs:
  - repo_path: "docs/guide.md"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "docs\[0\] missing required field: name"
}

@test "schema: package_map as string fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
docs:
  - name: "guide.md"
    package_map: "not a dict"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "package_map must be a mapping"
}

@test "schema: relevant_paths as string fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
relevant_paths: "not a list"
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "relevant_paths must be a list"
}

@test "schema: auto_pr enabled without target_branch fails" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
auto_pr:
  enabled: true
EOF
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "auto_pr.enabled requires auto_pr.target_branch"
}

@test "schema: minimal valid config passes" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
github:
  owner: "test"
  repo: "test"
EOF
  python3 "$SCHEMA_HELPER" "$TEST_DIR/config.yaml"
}

@test "schema: missing config file fails" {
  run python3 "$SCHEMA_HELPER" "$TEST_DIR/nonexistent.yaml"
  [ "$status" -eq 1 ]
}
