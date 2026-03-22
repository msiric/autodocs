#!/bin/bash
set -euo pipefail

# autodocs — automated documentation drift detection
# https://github.com/msiric/autodocs
# Thin wrapper: PATH setup + exec Python orchestrator.
# Lock management is handled by the orchestrator (protects all entry points).
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

exec python3 "$SCRIPTS_DIR/orchestrator.py" "$OUTPUT_DIR" "$REPO_DIR" "$@"
