#!/bin/bash
set -euo pipefail

# autodocs structural scan — weekly documentation audit
# Verifies that files referenced in docs exist in the repo.

OUTPUT_DIR="${OUTPUT_DIR}"
REPO_DIR="${REPO_DIR}"
LOG_FILE="$OUTPUT_DIR/sync.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.claude/local:$PATH"

# Prevent concurrent runs
LOCK_DIR="$OUTPUT_DIR/.scan.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$TIMESTAMP] SCAN SKIPPED — another scan running" >> "$LOG_FILE"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

# Rotate log if >100KB
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]; then
  tail -50 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# Preemptive auth check
if ! (cd "$REPO_DIR" && claude -p "Reply with OK" --output-format text 2>/dev/null | grep -qx "OK"); then
  echo "[$TIMESTAMP] SCAN AUTH FAILED — aborting" >> "$LOG_FILE"
  exit 1
fi

cd "$REPO_DIR"
git fetch origin --quiet 2>/dev/null || true

SCAN_OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/structural-scan-prompt.md")" \
  --add-dir "$OUTPUT_DIR" \
  --allowedTools "Read,Bash(git:*),Write" \
  --output-format text \
  2>&1) && SCAN_RC=0 || SCAN_RC=$?

if [ $SCAN_RC -eq 0 ]; then
  echo "[$TIMESTAMP] STRUCTURAL SCAN SUCCESS" >> "$LOG_FILE"
else
  echo "[$TIMESTAMP] STRUCTURAL SCAN FAILED (exit $SCAN_RC)" >> "$LOG_FILE"
  echo "$SCAN_OUTPUT" | tail -10 >> "$LOG_FILE"
fi
