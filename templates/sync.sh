#!/bin/bash
set -euo pipefail

# autodocs — automated documentation drift detection
# https://github.com/msiric/autodocs

OUTPUT_DIR="${OUTPUT_DIR}"
REPO_DIR="${REPO_DIR}"
STATUS_FILE="$OUTPUT_DIR/sync-status.md"
LOG_FILE="$OUTPUT_DIR/sync.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Ensure PATH includes typical Claude Code install locations (launchd has minimal PATH)
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.claude/local:$PATH"

# Prevent concurrent runs (mkdir is atomic on all filesystems)
LOCK_DIR="$OUTPUT_DIR/.sync.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$TIMESTAMP] SKIPPED — another sync is running" >> "$LOG_FILE"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

# Rotate log if >100KB (keep last 50 lines)
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 102400 ]; then
  tail -50 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# Preemptive auth check (fail fast, don't waste an expensive call)
if ! (cd "$REPO_DIR" && claude -p "Reply with OK" --output-format text 2>/dev/null | grep -qx "OK"); then
  cat > "$STATUS_FILE" <<EOF
status: failed
drift: skipped
timestamp: $TIMESTAMP
error: Claude Code auth expired
likely_cause: Re-open Claude Code interactively to refresh authentication.
EOF
  echo "[$TIMESTAMP] AUTH FAILED — aborting sync" >> "$LOG_FILE"
  exit 1
fi

# Fetch latest remote refs so git diff-tree can resolve merge commits from teammates' PRs
cd "$REPO_DIR"
git fetch origin --quiet 2>/dev/null || echo "[$TIMESTAMP] git fetch failed (non-fatal)" >> "$LOG_FILE"

# Track results — status is written ONCE at the end
SYNC_STATUS="failed"
DRIFT_STATUS="skipped"

# Call 1: Main sync (PRs + telemetry)
SYNC_TOOLS="mcp__azure-devops__repo_list_pull_requests_by_repo_or_project"
SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__repo_get_pull_request_by_id"
SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__repo_list_pull_request_threads"
SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__search_code"
SYNC_TOOLS="$SYNC_TOOLS,mcp__kusto-mcp__kusto_query"
SYNC_TOOLS="$SYNC_TOOLS,Bash(git:*),Write"

OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/sync-prompt.md")" \
  --add-dir "$OUTPUT_DIR" \
  --allowedTools "$SYNC_TOOLS" \
  --output-format text \
  2>&1) && SYNC_RC=0 || SYNC_RC=$?

if [ $SYNC_RC -eq 0 ] && [ -f "$OUTPUT_DIR/daily-report.md" ]; then
  SYNC_STATUS="success"
  echo "[$TIMESTAMP] SYNC SUCCESS" >> "$LOG_FILE"

  # Call 2: Drift detection (reads sync output + doc indexes, writes drift files)
  # Runs independently — failure here does NOT affect sync status
  if [ -f "$OUTPUT_DIR/drift-prompt.md" ]; then
    DRIFT_OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/drift-prompt.md")" \
      --add-dir "$OUTPUT_DIR" \
      --allowedTools "Read,Write" \
      --output-format text \
      2>&1) && DRIFT_RC=0 || DRIFT_RC=$?

    if [ $DRIFT_RC -eq 0 ]; then
      DRIFT_STATUS="success"
      echo "[$TIMESTAMP] DRIFT SUCCESS" >> "$LOG_FILE"
    else
      DRIFT_STATUS="failed"
      echo "[$TIMESTAMP] DRIFT FAILED (exit $DRIFT_RC)" >> "$LOG_FILE"
      echo "$DRIFT_OUTPUT" | tail -10 >> "$LOG_FILE"
    fi
  fi

  # Call 3: Suggested updates + changelog (only if drift found actionable alerts)
  SUGGEST_STATUS="skipped"
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$OUTPUT_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$OUTPUT_DIR/drift-report.md" 2>/dev/null; then
    SUGGEST_OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/suggest-prompt.md")" \
      --add-dir "$OUTPUT_DIR" \
      --allowedTools "Read,Write" \
      --output-format text \
      2>&1) && SUGGEST_RC=0 || SUGGEST_RC=$?

    if [ $SUGGEST_RC -eq 0 ]; then
      SUGGEST_STATUS="success"
      echo "[$TIMESTAMP] SUGGEST SUCCESS" >> "$LOG_FILE"
    else
      SUGGEST_STATUS="failed"
      echo "[$TIMESTAMP] SUGGEST FAILED (exit $SUGGEST_RC)" >> "$LOG_FILE"
      echo "$SUGGEST_OUTPUT" | tail -10 >> "$LOG_FILE"
    fi
  fi
else
  echo "[$TIMESTAMP] SYNC FAILED (exit $SYNC_RC)" >> "$LOG_FILE"
  echo "$OUTPUT" | tail -20 >> "$LOG_FILE"
fi

# Write status ONCE at the end
cat > "$STATUS_FILE" <<EOF
status: $SYNC_STATUS
drift: $DRIFT_STATUS
suggest: ${SUGGEST_STATUS:-skipped}
timestamp: $TIMESTAMP
EOF
