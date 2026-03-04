#!/usr/bin/env bats

load helpers/test-helpers

@test "log rotation triggers at 100KB" {
  LOG_FILE="$TEST_DIR/sync.log"
  # Create a file > 100KB (102400 bytes)
  dd if=/dev/zero bs=1024 count=110 2>/dev/null | tr '\0' 'x' > "$LOG_FILE"
  # Add 100 lines so tail -50 has something to work with
  for i in $(seq 1 100); do echo "line $i" >> "$LOG_FILE"; done

  [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]

  # Run rotation logic
  if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]; then
    tail -50 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
  fi

  # After rotation, should have exactly 50 lines
  [ "$(wc -l < "$LOG_FILE")" -eq 50 ]
}

@test "log rotation skips for small files" {
  LOG_FILE="$TEST_DIR/sync.log"
  echo "small log" > "$LOG_FILE"
  original_size=$(wc -c < "$LOG_FILE")

  if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]; then
    tail -50 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
  fi

  [ "$(wc -c < "$LOG_FILE")" -eq "$original_size" ]
}

@test "log rotation handles missing file" {
  LOG_FILE="$TEST_DIR/nonexistent.log"

  if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]; then
    tail -50 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
  fi

  # Should not create the file
  [ ! -f "$LOG_FILE" ]
}
