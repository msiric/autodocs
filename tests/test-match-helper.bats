#!/usr/bin/env bats

load helpers/test-helpers

HELPER="$BATS_TEST_DIRNAME/../scripts/match-helper.py"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  # Create a config with package_map
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "architecture.md"
    package_map:
      "src/auth/handler.ts": "Authentication"
      "src/controllers/*.ts": "API Endpoints"
      auth: "Authentication"
      errors: "Error Handling"
      api: "API Endpoints"
      "utils.ts": "Utilities"

source_roots:
  - "src/"
EOF
}

# ============================================================
# Priority 1: Exact path match
# ============================================================

@test "exact path match works" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/auth/handler.ts")
  [ "$result" = "Authentication" ]
}

@test "exact path match takes priority over directory" {
  # "auth" directory key also matches, but exact path should win
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/auth/handler.ts")
  [ "$result" = "Authentication" ]
}

# ============================================================
# Priority 2: Glob match
# ============================================================

@test "glob match works for wildcard" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/controllers/users.ts")
  [ "$result" = "API Endpoints" ]
}

@test "glob match works for different file in same directory" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/controllers/admin.ts")
  [ "$result" = "API Endpoints" ]
}

@test "glob does not match different extension" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/controllers/README.md")
  [ "$result" = "UNMAPPED" ]
}

# ============================================================
# Priority 3: Directory match (/<key>/)
# ============================================================

@test "directory match works" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "packages/components/errors/handler.ts")
  [ "$result" = "Error Handling" ]
}

@test "directory match uses longest key" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map:
      api: "General API"
      api-v2: "API V2"
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "packages/api-v2/handler.ts")
  [ "$result" = "API V2" ]
}

# ============================================================
# Priority 4: Basename match
# ============================================================

@test "basename match works for unique file" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/somewhere/utils.ts")
  [ "$result" = "Utilities" ]
}

# ============================================================
# Source roots prefix stripping
# ============================================================

@test "source roots strips prefix before matching" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map:
      auth: "Authentication"
source_roots:
  - "src/"
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/auth/handler.ts")
  [ "$result" = "Authentication" ]
}

@test "source roots with longest prefix wins" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map:
      core: "Core Module"
source_roots:
  - "src/"
  - "src/packages/"
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/packages/core/index.ts")
  [ "$result" = "Core Module" ]
}

# ============================================================
# Unmapped files
# ============================================================

@test "unmapped file returns UNMAPPED" {
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "totally/unknown/file.ts")
  [ "$result" = "UNMAPPED" ]
}

# ============================================================
# Complex mappings (title_hints)
# ============================================================

@test "complex mapping with title hint" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map:
      fluid:
        default: "Fluid Engine"
        title_hints:
          "error,fault": "Error Handling"
          "title,rename": "Title Sync"
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "packages/fluid/src/error.ts" "Fix error handling")
  [ "$result" = "Error Handling" ]
}

@test "complex mapping falls back to default" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map:
      fluid:
        default: "Fluid Engine"
        title_hints:
          "error,fault": "Error Handling"
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "packages/fluid/src/loader.ts" "Update loader performance")
  [ "$result" = "Fluid Engine" ]
}

# ============================================================
# Edge cases
# ============================================================

@test "missing config file returns UNMAPPED" {
  result=$(python3 "$HELPER" "$TEST_DIR/nonexistent.yaml" "src/api.ts")
  [ "$result" = "UNMAPPED" ]
}

@test "empty package_map returns UNMAPPED" {
  cat > "$TEST_DIR/config.yaml" <<EOF
docs:
  - name: "guide.md"
    package_map: {}
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/api.ts")
  [ "$result" = "UNMAPPED" ]
}

@test "config without docs section returns UNMAPPED" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
EOF
  result=$(python3 "$HELPER" "$TEST_DIR/config.yaml" "src/api.ts")
  [ "$result" = "UNMAPPED" ]
}
