#!/bin/bash
set -euo pipefail

# autodocs test runner
# Requires: bats-core (brew install bats-core)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v bats >/dev/null 2>&1; then
  echo "Error: bats not found. Install with: brew install bats-core"
  exit 1
fi

if [ "${1:-}" = "" ]; then
  echo "Running all tests..."
  bats "$SCRIPT_DIR"/test-*.bats
else
  echo "Running $1 tests..."
  bats "$SCRIPT_DIR"/test-"$1".bats
fi
