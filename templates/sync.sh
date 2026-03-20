#!/bin/bash
set -euo pipefail

# autodocs — automated documentation drift detection
# https://github.com/msiric/autodocs
# Thin wrapper: lock management + PATH setup + exec Python orchestrator.
# Usage: autodocs-sync.sh [--dry-run] [--since YYYY-MM-DD [--chunk-days N]]

OUTPUT_DIR="${OUTPUT_DIR}"
REPO_DIR="${REPO_DIR}"

# Ensure PATH includes typical Claude Code install locations (launchd has minimal PATH)
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.claude/local"

# Resolve helper scripts directory
# Deployed: scripts/ is sibling to this script (copied by setup.sh)
# Development: scripts/ is sibling to templates/ (one level up)
SCRIPTS_DIR="$(dirname "$0")/scripts"
[ ! -d "$SCRIPTS_DIR" ] && SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)/../scripts"

# Prevent concurrent runs (mkdir is atomic on all filesystems)
LOCK_DIR="$OUTPUT_DIR/.sync.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  # Check for stale lock (orphaned by a killed process)
  LOCK_AGE=0
  if [[ "$(uname)" == "Darwin" ]]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -f%m "$LOCK_DIR" 2>/dev/null || echo "$(date +%s)") ))
  else
    LOCK_AGE=$(( $(date +%s) - $(stat -c%Y "$LOCK_DIR" 2>/dev/null || echo "$(date +%s)") ))
  fi
  LOG_FILE="$OUTPUT_DIR/sync.log"
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [ "$LOCK_AGE" -gt 7200 ]; then
    echo "[$TIMESTAMP] WARN: Removing stale lock (${LOCK_AGE}s old)" >> "$LOG_FILE" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
    mkdir "$LOCK_DIR" 2>/dev/null || { echo "[$TIMESTAMP] SKIPPED — another sync is running" >> "$LOG_FILE" 2>/dev/null || true; exit 0; }
  else
    echo "[$TIMESTAMP] SKIPPED — another sync is running" >> "$LOG_FILE" 2>/dev/null || true
    exit 0
  fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

exec python3 "$SCRIPTS_DIR/orchestrator.py" "$OUTPUT_DIR" "$REPO_DIR" "$@"
