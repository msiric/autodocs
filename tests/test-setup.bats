#!/usr/bin/env bats
# Tests for setup.sh subcommands (non-interactive only).
# Interactive flows (main setup, team add/remove) are covered
# by config-helper.py tests which handle the actual mutations.

load helpers/test-helpers

SETUP="$BATS_TEST_DIRNAME/../setup.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR

  # Create a minimal repo structure
  mkdir -p "$TEST_DIR/repo/.git" "$TEST_DIR/repo/src/api" "$TEST_DIR/repo/docs"
  (cd "$TEST_DIR/repo" && git init -q 2>/dev/null)

  # Create output dir with config
  mkdir -p "$TEST_DIR/output/feedback"
  cat > "$TEST_DIR/output/config.yaml" <<EOF
platform: github
feature_name: "Test Feature"
github:
  owner: testowner
  repo: testrepo
owner:
  name: "Alice"
  email: "alice@example.com"
  github_username: "alice"
team_members:
  - name: "Bob"
    github_username: "bob"
docs:
  - name: "guide.md"
    repo_path: "docs/guide.md"
relevant_paths:
  - src/api/
EOF
}

# ============================================================
# cmd_analyze
# ============================================================

@test "analyze detects repo and languages" {
  echo '{}' > "$TEST_DIR/repo/package.json"
  for i in $(seq 1 60); do
    touch "$TEST_DIR/repo/src/file$i.ts"
  done
  run bash "$SETUP" analyze "$TEST_DIR/repo"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Files:"* ]]
  [[ "$output" == *"TypeScript/JavaScript"* ]]
}

@test "analyze classifies small repo correctly" {
  for i in $(seq 1 10); do
    touch "$TEST_DIR/repo/src/file$i.ts"
  done
  run bash "$SETUP" analyze "$TEST_DIR/repo"
  [[ "$output" == *"SMALL"* ]]
}

@test "analyze classifies medium repo correctly" {
  for i in $(seq 1 100); do
    touch "$TEST_DIR/repo/src/file$i.ts"
  done
  run bash "$SETUP" analyze "$TEST_DIR/repo"
  [[ "$output" == *"MEDIUM"* ]]
}

@test "analyze finds documentation files" {
  cat > "$TEST_DIR/repo/docs/guide.md" <<EOF
# Guide
## Setup
Instructions here.
EOF
  run bash "$SETUP" analyze "$TEST_DIR/repo"
  [[ "$output" == *"guide.md"* ]]
}

@test "analyze rejects non-git directory" {
  mkdir -p "$TEST_DIR/notrepo"
  run bash "$SETUP" analyze "$TEST_DIR/notrepo"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a git repository"* ]]
}

# ============================================================
# cmd_status
# ============================================================

@test "status shows sync-status.md when present" {
  cat > "$TEST_DIR/output/sync-status.md" <<EOF
status: success
drift: success
suggest: success
apply: dry-run
timestamp: 2026-03-09T10:00:00Z
EOF
  cd "$TEST_DIR/output"
  run bash "$SETUP" status
  [ "$status" -eq 0 ]
  [[ "$output" == *"status: success"* ]]
  [[ "$output" == *"drift: success"* ]]
}

@test "status shows no runs when status file missing" {
  cd "$TEST_DIR/output"
  run bash "$SETUP" status
  [[ "$output" == *"No runs recorded"* ]]
}

@test "status shows last successful run" {
  echo "2026-03-09T10:00:00Z" > "$TEST_DIR/output/last-successful-run"
  cat > "$TEST_DIR/output/sync-status.md" <<EOF
status: success
EOF
  cd "$TEST_DIR/output"
  run bash "$SETUP" status
  [[ "$output" == *"2026-03-09"* ]]
}

# ============================================================
# cmd_metrics
# ============================================================

@test "metrics shows no data message when file missing" {
  cd "$TEST_DIR/output"
  run bash "$SETUP" metrics
  [[ "$output" == *"No metrics recorded"* ]]
}

@test "metrics shows stage success rates" {
  cat > "$TEST_DIR/output/metrics.jsonl" <<EOF
{"ts":"2026-03-08T17:00:00Z","call":"sync","status":"success","rc":0}
{"ts":"2026-03-08T17:01:00Z","call":"drift","status":"success","rc":0}
{"ts":"2026-03-08T17:02:00Z","call":"suggest","status":"success","rc":0}
{"ts":"2026-03-09T17:00:00Z","call":"sync","status":"success","rc":0}
{"ts":"2026-03-09T17:01:00Z","call":"drift","status":"failed","rc":1}
EOF
  cd "$TEST_DIR/output"
  run bash "$SETUP" metrics
  [ "$status" -eq 0 ]
  [[ "$output" == *"sync"* ]]
  [[ "$output" == *"drift"* ]]
  [[ "$output" == *"100.0%"* ]]
}

@test "metrics shows recent failures" {
  cat > "$TEST_DIR/output/metrics.jsonl" <<EOF
{"ts":"2026-03-08T17:00:00Z","call":"sync","status":"success","rc":0}
{"ts":"2026-03-09T17:00:00Z","call":"suggest","status":"failed","rc":1}
EOF
  cd "$TEST_DIR/output"
  run bash "$SETUP" metrics
  [[ "$output" == *"Recent failures"* ]]
  [[ "$output" == *"suggest"* ]]
}

# ============================================================
# Template rendering (envsubst)
# ============================================================

@test "sync-prompt renders OUTPUT_DIR correctly" {
  export OUTPUT_DIR="/test/output/path"
  envsubst '${OUTPUT_DIR}' < "$BATS_TEST_DIRNAME/../templates/sync-prompt.md" > "$TEST_DIR/rendered.md"
  grep -q "/test/output/path" "$TEST_DIR/rendered.md"
  ! grep -q '${OUTPUT_DIR}' "$TEST_DIR/rendered.md"
}

@test "sync.sh renders OUTPUT_DIR and REPO_DIR" {
  export OUTPUT_DIR="/test/output"
  export REPO_DIR="/test/repo"
  envsubst '${OUTPUT_DIR} ${REPO_DIR}' < "$BATS_TEST_DIRNAME/../templates/sync.sh" > "$TEST_DIR/sync.sh"
  grep -q 'OUTPUT_DIR="/test/output"' "$TEST_DIR/sync.sh"
  grep -q 'REPO_DIR="/test/repo"' "$TEST_DIR/sync.sh"
}

@test "templates have no FEATURE_NAME or OWNER_NAME variables" {
  ! grep -r '${FEATURE_NAME}' "$BATS_TEST_DIRNAME/../templates/"
  ! grep -r '${OWNER_NAME}' "$BATS_TEST_DIRNAME/../templates/"
}

# ============================================================
# Helper functions (tested via inline reimplementation since
# setup.sh can't be sourced without running the interactive flow)
# ============================================================

# Reusable detection functions (must match setup.sh)
_detect_platform() {
  local remote
  remote=$(cd "$1" && git remote get-url origin 2>/dev/null) || return 1
  case "$remote" in
    *github.com[:/]*)                                echo "github" ;;
    *gitlab.com[:/]*|*gitlab.*[:/]*)                 echo "gitlab" ;;
    *bitbucket.org[:/]*)                             echo "bitbucket" ;;
    *dev.azure.com*|*visualstudio.com*)              echo "ado" ;;
    *)                                               return 1 ;;
  esac
}

_detect_owner_repo() {
  local remote
  remote=$(cd "$1" && git remote get-url origin 2>/dev/null) || return 1
  echo "$remote" | sed -E 's|^[^:]+://[^/]+/||; s|^[^:]+:||; s|\.git$||'
}

@test "detect_platform extracts github from remote" {
  (cd "$TEST_DIR/repo" && git remote add origin https://github.com/user/repo.git 2>/dev/null)
  result=$(_detect_platform "$TEST_DIR/repo")
  [ "$result" = "github" ]
}

@test "detect_platform extracts gitlab from remote" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin https://gitlab.com/group/repo.git 2>/dev/null)
  result=$(_detect_platform "$TEST_DIR/repo")
  [ "$result" = "gitlab" ]
}

@test "detect_platform extracts self-hosted gitlab" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin git@gitlab.mycompany.com:team/repo.git 2>/dev/null)
  result=$(_detect_platform "$TEST_DIR/repo")
  [ "$result" = "gitlab" ]
}

@test "detect_platform does not false-positive on gitlab in path" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin https://github.com/user/my-gitlab-migration.git 2>/dev/null)
  result=$(_detect_platform "$TEST_DIR/repo")
  [ "$result" = "github" ]
}

@test "detect_owner_repo parses HTTPS github URL" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin https://github.com/msiric/autodocs.git 2>/dev/null)
  result=$(_detect_owner_repo "$TEST_DIR/repo")
  [ "$result" = "msiric/autodocs" ]
}

@test "detect_owner_repo parses SSH github URL" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin git@github.com:msiric/autodocs.git 2>/dev/null)
  result=$(_detect_owner_repo "$TEST_DIR/repo")
  [ "$result" = "msiric/autodocs" ]
}

@test "detect_owner_repo parses URL without .git suffix" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin https://github.com/msiric/autodocs 2>/dev/null)
  result=$(_detect_owner_repo "$TEST_DIR/repo")
  [ "$result" = "msiric/autodocs" ]
}

@test "detect_owner_repo parses nested gitlab groups" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin https://gitlab.com/group/subgroup/repo.git 2>/dev/null)
  result=$(_detect_owner_repo "$TEST_DIR/repo")
  [ "$result" = "group/subgroup/repo" ]
}

@test "detect_owner_repo parses bitbucket SSH URL" {
  rm -rf "$TEST_DIR/repo/.git"
  (cd "$TEST_DIR/repo" && git init -q && git remote add origin git@bitbucket.org:workspace/repo.git 2>/dev/null)
  result=$(_detect_owner_repo "$TEST_DIR/repo")
  [ "$result" = "workspace/repo" ]
}

@test "discover_paths extracts code paths from markdown" {
  cat > "$TEST_DIR/doc.md" <<EOF
See src/api/handler.ts and lib/auth/token.py for details.
Also check src/utils/helpers.go.
EOF
  result=$(grep -oE '[a-zA-Z][a-zA-Z0-9/_.-]+\.(ts|js|py|tsx|jsx|go|rs|java|rb|cs)' "$TEST_DIR/doc.md" | sed 's|/[^/]*$||' | sort -u)
  echo "$result" | grep -q "src/api"
  echo "$result" | grep -q "lib/auth"
  echo "$result" | grep -q "src/utils"
}

# ============================================================
# Path safety (prompt injection defense)
# ============================================================

@test "path validation rejects traversal attempts" {
  HELPER="$BATS_TEST_DIRNAME/../scripts/match-helper.py"
  cat > "$TEST_DIR/report.md" <<EOF
## Team PRs
- PR #1: "Test" by alice — merged
  Files:
    M src/safe/file.ts
    M ../../../etc/passwd
    A /absolute/path.ts
    D src/normal.ts
EOF
  # Create a minimal config
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
docs: []
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" --resolve-report "$TEST_DIR/report.md")
  echo "$result" | grep -q "src/safe/file.ts"
  echo "$result" | grep -q "src/normal.ts"
  ! echo "$result" | grep -q "etc/passwd"
  ! echo "$result" | grep -q "/absolute/path"
}

# ============================================================
# Module import smoke test
# ============================================================

@test "all Python scripts load without import errors" {
  SCRIPTS_DIR="$BATS_TEST_DIRNAME/../scripts"
  for f in "$SCRIPTS_DIR/"*.py; do
    run python3 -c "
import importlib.util, sys, os
sys.path.insert(0, os.path.dirname('$f'))
name = os.path.splitext(os.path.basename('$f'))[0]
spec = importlib.util.spec_from_file_location(name, '$f')
mod = importlib.util.module_from_spec(spec)
sys.modules[name] = mod
try:
    spec.loader.exec_module(mod)
except SystemExit as e:
    sys.exit(0 if e.code in (0, None) else 1)
"
    if [ "$status" -ne 0 ]; then
      echo "FAILED to import: $(basename $f)"
      echo "$output"
      return 1
    fi
  done
}
