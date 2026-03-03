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

# Preemptive auth check (fail fast, don't waste an expensive call)
if ! (cd "$REPO_DIR" && claude -p "Reply with OK" --output-format text 2>/dev/null | grep -q "OK"); then
  cat > "$STATUS_FILE" <<EOF
status: failed
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

# Call 1: Main sync (PRs + telemetry)
SYNC_TOOLS="mcp__azure-devops__repo_list_pull_requests_by_repo_or_project"
SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__repo_get_pull_request_by_id"
SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__search_code"
SYNC_TOOLS="$SYNC_TOOLS,mcp__kusto-mcp__kusto_query"
SYNC_TOOLS="$SYNC_TOOLS,Bash(git:*),Write"

OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/sync-prompt.md")" \
  --add-dir "$OUTPUT_DIR" \
  --allowedTools "$SYNC_TOOLS" \
  --output-format text \
  2>&1) || true

EXIT_CODE=${PIPESTATUS[0]:-$?}

if [ $EXIT_CODE -eq 0 ] && [ -f "$OUTPUT_DIR/daily-report.md" ]; then
  cat > "$STATUS_FILE" <<EOF
status: success
timestamp: $TIMESTAMP
EOF
  echo "[$TIMESTAMP] SYNC SUCCESS" >> "$LOG_FILE"

  # Call 2: Drift detection (reads sync output + doc indexes, writes drift files)
  # Runs independently — failure here does NOT affect sync status
  if [ -f "$OUTPUT_DIR/drift-prompt.md" ]; then
    DRIFT_OUTPUT=$(claude -p "$(cat "$OUTPUT_DIR/drift-prompt.md")" \
      --add-dir "$OUTPUT_DIR" \
      --allowedTools "Read,Write" \
      --output-format text \
      2>&1) || true

    DRIFT_EXIT=${PIPESTATUS[0]:-$?}

    if [ $DRIFT_EXIT -eq 0 ]; then
      echo "[$TIMESTAMP] DRIFT SUCCESS" >> "$LOG_FILE"
    else
      echo "[$TIMESTAMP] DRIFT FAILED (exit $DRIFT_EXIT)" >> "$LOG_FILE"
      echo "$DRIFT_OUTPUT" | tail -10 >> "$LOG_FILE"
    fi
  fi
else
  cat > "$STATUS_FILE" <<EOF
status: failed
timestamp: $TIMESTAMP
error: Exit code $EXIT_CODE
likely_cause: Check sync.log and sync.err.log for details.
EOF
  echo "[$TIMESTAMP] SYNC FAILED (exit $EXIT_CODE)" >> "$LOG_FILE"
  echo "$OUTPUT" | tail -20 >> "$LOG_FILE"
fi
