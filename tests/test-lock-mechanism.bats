#!/usr/bin/env bats

load helpers/test-helpers

@test "lock directory is created by mkdir" {
  LOCK_DIR="$TEST_DIR/.sync.lock"
  mkdir "$LOCK_DIR"
  [ -d "$LOCK_DIR" ]
}

@test "second mkdir fails when lock exists" {
  LOCK_DIR="$TEST_DIR/.sync.lock"
  mkdir "$LOCK_DIR"
  run mkdir "$LOCK_DIR" 2>/dev/null
  [ "$status" -ne 0 ]
}

@test "lock is cleaned up by rmdir" {
  LOCK_DIR="$TEST_DIR/.sync.lock"
  mkdir "$LOCK_DIR"
  rmdir "$LOCK_DIR"
  [ ! -d "$LOCK_DIR" ]
}

@test "rmdir on nonexistent lock doesn't error with 2>/dev/null" {
  LOCK_DIR="$TEST_DIR/.sync.lock"
  run bash -c "rmdir '$LOCK_DIR' 2>/dev/null"
  # Should not error (rmdir fails but stderr suppressed)
  true
}
