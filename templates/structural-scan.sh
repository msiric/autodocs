#!/bin/bash
set -euo pipefail

# autodocs structural scan — weekly documentation audit
# Thin wrapper: lock management + exec Python orchestrator.

OUTPUT_DIR="${OUTPUT_DIR}"
REPO_DIR="${REPO_DIR}"

export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.claude/local:$PATH"

# Resolve helper scripts directory
SCRIPTS_DIR="$(dirname "$0")/scripts"
[ ! -d "$SCRIPTS_DIR" ] && SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)/../scripts"

# Prevent concurrent runs
LOCK_DIR="$OUTPUT_DIR/.scan.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

exec python3 "$SCRIPTS_DIR/orchestrator.py" "$OUTPUT_DIR" "$REPO_DIR" --structural-scan
