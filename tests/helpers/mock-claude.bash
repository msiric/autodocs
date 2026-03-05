#!/bin/bash
# Mock claude for integration tests.
# Identifies calls by prompt content keywords, copies fixture files, returns configurable exit codes.

PROMPT="" APPEND_SYSTEM=""
ADD_DIRS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p) PROMPT="$2"; shift 2 ;;
    --append-system-prompt) APPEND_SYSTEM="$2"; shift 2 ;;
    --add-dir) ADD_DIRS+=("$2"); shift 2 ;;
    --output-format|--allowedTools|--model) shift 2 ;;
    *) shift ;;
  esac
done

SCENARIO_DIR="${MOCK_SCENARIO_DIR:-}"

# Auth check: "Reply with OK"
if echo "$PROMPT" | grep -q "Reply with OK"; then
  if [ -f "$SCENARIO_DIR/auth.exit" ]; then
    exit "$(cat "$SCENARIO_DIR/auth.exit")"
  fi
  echo "OK"
  exit 0
fi

# Identify call by unique prompt content
CALL=""
if echo "$PROMPT" | grep -q "work context summarizer"; then
  CALL="sync"
elif echo "$PROMPT" | grep -q "documentation drift detector"; then
  CALL="drift"
elif echo "$PROMPT" | grep -q "documentation update advisor"; then
  if [ -n "$APPEND_SYSTEM" ]; then
    CALL="verify"
  else
    CALL="suggest"
  fi
elif echo "$PROMPT" | grep -q "documentation update applicator"; then
  CALL="apply"
fi

# Copy fixture files for this call
if [ -n "$CALL" ] && [ -d "$SCENARIO_DIR/$CALL" ]; then
  # Determine OUTPUT_DIR from --add-dir (first one)
  TARGET_DIR="${ADD_DIRS[0]:-}"
  if [ -n "$TARGET_DIR" ]; then
    cp "$SCENARIO_DIR/$CALL/"* "$TARGET_DIR/" 2>/dev/null || true
  fi
fi

# Return configured exit code
if [ -n "$CALL" ] && [ -f "$SCENARIO_DIR/$CALL.exit" ]; then
  exit "$(cat "$SCENARIO_DIR/$CALL.exit")"
fi
exit 0
