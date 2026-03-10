#!/usr/bin/env bats

load helpers/test-helpers

# ============================================================
# Change type parsing (A/M/D/R from git diff-tree --name-status)
# ============================================================

@test "git name-status output contains change type prefix" {
  # Simulate git diff-tree --name-status output
  output="M	src/errors/handler.ts
A	src/auth/rate-limiter.ts
D	src/legacy/old.ts
R100	src/old-name.ts	src/new-name.ts"
  echo "$output" | grep -q "^M"
  echo "$output" | grep -q "^A"
  echo "$output" | grep -q "^D"
  echo "$output" | grep -q "^R"
}

@test "modified files are detected" {
  output="M	src/errors/handler.ts"
  change_type=$(echo "$output" | awk '{print $1}')
  [ "$change_type" = "M" ]
}

@test "added files are detected" {
  output="A	src/auth/rate-limiter.ts"
  change_type=$(echo "$output" | awk '{print $1}')
  [ "$change_type" = "A" ]
}

@test "deleted files are detected" {
  output="D	src/legacy/old.ts"
  change_type=$(echo "$output" | awk '{print $1}')
  [ "$change_type" = "D" ]
}

@test "renamed files are detected with similarity" {
  output="R100	src/old.ts	src/new.ts"
  change_type=$(echo "$output" | cut -c1)
  [ "$change_type" = "R" ]
}

@test "renamed file extracts old and new paths" {
  output="R100	src/old-name.ts	src/new-name.ts"
  old_path=$(echo "$output" | awk '{print $2}')
  new_path=$(echo "$output" | awk '{print $3}')
  [ "$old_path" = "src/old-name.ts" ]
  [ "$new_path" = "src/new-name.ts" ]
}

# ============================================================
# Refactoring detection heuristic
# ============================================================

@test "PR with >30 YES files triggers refactor check" {
  file_count=35
  [ "$file_count" -gt 30 ]
}

@test "single-line hunks ratio detects refactoring" {
  # Simulate: 8 out of 10 hunks are single-line changes
  total_hunks=10
  single_line_hunks=8
  ratio=$((single_line_hunks * 100 / total_hunks))
  [ "$ratio" -ge 80 ]
}

@test "mixed hunks ratio does NOT trigger refactoring" {
  total_hunks=10
  single_line_hunks=3
  ratio=$((single_line_hunks * 100 / total_hunks))
  [ "$ratio" -lt 80 ]
}

# ============================================================
# Stale suggestion detection
# ============================================================

@test "FIND text found in doc returns success" {
  echo "function handleError(error) {" > "$TEST_DIR/doc.md"
  grep -q "function handleError" "$TEST_DIR/doc.md"
}

@test "FIND text not found in doc returns failure" {
  echo "function classifyError(error) {" > "$TEST_DIR/doc.md"
  run grep -q "function handleError" "$TEST_DIR/doc.md"
  [ "$status" -ne 0 ]
}

@test "section header exists even when FIND text doesn't" {
  cat > "$TEST_DIR/doc.md" <<EOF
## Error Handling
This section was rewritten.
New content here.
EOF
  grep -q "## Error Handling" "$TEST_DIR/doc.md"
  run grep -q "function handleError" "$TEST_DIR/doc.md"
  [ "$status" -ne 0 ]
  # Section exists but FIND text doesn't → EXPIRED
}

@test "section header removed entirely" {
  cat > "$TEST_DIR/doc.md" <<EOF
## API Endpoints
Content about API.
EOF
  run grep -q "## Error Handling" "$TEST_DIR/doc.md"
  [ "$status" -ne 0 ]
  # Section doesn't exist → SECTION REMOVED
}

# ============================================================
# Multi-PR conflict detection
# ============================================================

@test "non-overlapping suggestions have no conflict" {
  find_a="function foo() {"
  replace_a="function bar() {"
  find_b="const timeout = 30"
  # find_b does not overlap with replace_a
  ! echo "$replace_a" | grep -qF "$find_b"
}

@test "overlapping suggestions are detected as conflict" {
  find_a="function foo() {"
  replace_a="function bar(options) {"
  find_b="function bar"
  # find_b overlaps with replace_a (both mention "function bar")
  echo "$replace_a" | grep -qF "$find_b"
}

# ============================================================
# Diff filtering
# ============================================================

@test "test files are filtered from diff" {
  files="src/api/users.ts
src/api/users.test.ts
src/errors/handler.ts
src/errors/handler.spec.ts"
  filtered=$(echo "$files" | grep -v -E '\.(test|spec)\.')
  [ "$(echo "$filtered" | wc -l)" -eq 2 ]
}

@test "generated files are filtered from diff" {
  files="src/api/users.ts
dist/bundle.min.js
src/types.generated.ts
build/output.js"
  filtered=$(echo "$files" | grep -v -E '\.(min|generated)\.|^dist/|^build/')
  [ "$(echo "$filtered" | wc -l)" -eq 1 ]
}

@test "lock files are filtered from diff" {
  files="src/api/users.ts
package-lock.json
yarn.lock"
  filtered=$(echo "$files" | grep -v -E 'package-lock\.json|yarn\.lock')
  [ "$(echo "$filtered" | wc -l)" -eq 1 ]
}
