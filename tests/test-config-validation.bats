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
