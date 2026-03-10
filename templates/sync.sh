#!/bin/bash
set -euo pipefail

# autodocs — automated documentation drift detection
# https://github.com/msiric/autodocs
# Usage: autodocs-sync.sh [--dry-run]

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

OUTPUT_DIR="${OUTPUT_DIR}"
REPO_DIR="${REPO_DIR}"
STATUS_FILE="$OUTPUT_DIR/sync-status.md"
LOG_FILE="$OUTPUT_DIR/sync.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Resolve helper scripts directory
# Deployed: scripts/ is sibling to this script (copied by setup.sh)
# Development: scripts/ is sibling to templates/ (one level up)
SCRIPTS_DIR="$(dirname "$0")/scripts"
[ ! -d "$SCRIPTS_DIR" ] && SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)/../scripts"

# Read a dotted config key (e.g., "github.owner") from config.yaml
# Normalizes booleans to lowercase "true"/"false"
read_config() {
  python3 -c "
import yaml
c = yaml.safe_load(open('$OUTPUT_DIR/config.yaml'))
keys = '$1'.split('.')
v = c
for k in keys:
    v = v.get(k, '') if isinstance(v, dict) else ''
print('true' if v is True else 'false' if v is False else v)
" 2>/dev/null
}

# Log a metric entry (JSON line to metrics.jsonl)
log_metric() {
  local call="$1" status="$2" rc="${3:-0}"
  echo "{\"ts\":\"$TIMESTAMP\",\"call\":\"$call\",\"status\":\"$status\",\"rc\":$rc}" \
    >> "$OUTPUT_DIR/metrics.jsonl" 2>/dev/null || true
}

# Retry a command with exponential backoff (for transient API/network failures).
# Claude Code CLI uses binary exit codes (0=success, 1=any error) so we cannot
# distinguish transient from permanent failures. The auth pre-check above catches
# the most common permanent failure (expired session) before any retried call.
retry() {
  local attempts=3 delay=5 rc=0
  for ((i=1; i<=attempts; i++)); do
    "$@" && return 0
    rc=$?
    if [ $i -lt $attempts ]; then
      echo "[$TIMESTAMP] Attempt $i/$attempts failed (exit $rc), retrying in ${delay}s..." >> "$LOG_FILE"
      sleep $delay
      delay=$((delay * 2))
    fi
  done
  return $rc
}

# Ensure PATH includes typical Claude Code install locations (launchd has minimal PATH)
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.claude/local"

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
  if [ "$LOCK_AGE" -gt 7200 ]; then
    echo "[$TIMESTAMP] WARN: Removing stale lock (${LOCK_AGE}s old)" >> "$LOG_FILE"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    mkdir "$LOCK_DIR" 2>/dev/null || { echo "[$TIMESTAMP] SKIPPED — another sync is running" >> "$LOG_FILE"; exit 0; }
  else
    echo "[$TIMESTAMP] SKIPPED — another sync is running" >> "$LOG_FILE"
    exit 0
  fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

# Rotate large files (keep recent entries, discard old)
rotate_if_large() {
  local file="$1" max_bytes="$2" keep_lines="$3"
  if [ -f "$file" ] && [ "$(wc -c < "$file")" -gt "$max_bytes" ]; then
    tail -"$keep_lines" "$file" > "$file.tmp" && mv "$file.tmp" "$file"
  fi
}
rotate_if_large "$LOG_FILE" 102400 50                     # sync.log: 100KB, keep 50 lines
rotate_if_large "$OUTPUT_DIR/metrics.jsonl" 512000 1000   # metrics: 500KB, keep 1000 entries

# Preemptive auth check (fail fast, don't waste an expensive call)
if ! (cd "$REPO_DIR" && claude -p "Reply with OK" --output-format text 2>/dev/null | grep -qx "OK"); then
  cat > "$STATUS_FILE" <<EOF
status: failed
drift: skipped
suggest: skipped
verify: skipped
apply: skipped
timestamp: $TIMESTAMP
error: Claude Code auth expired
likely_cause: Re-open Claude Code interactively to refresh authentication.
EOF
  echo "[$TIMESTAMP] AUTH FAILED — aborting sync" >> "$LOG_FILE"
  exit 1
fi

# Clear intermediate files from any previous run (prevents stale data if a run crashed mid-pipeline).
# Persistent state is preserved: drift-status.md, drift-log.md, activity-log.md,
# changelog-*.md, feedback/, last-successful-run, metrics.jsonl, sync-status.md.
for f in daily-report.md resolved-mappings.md drift-context.json drift-report.md \
         suggest-context.json drift-suggestions.md drift-suggestions-verify.md \
         verified-suggestions.json replace-verification.json pre-sync-result.json \
         fetched-prs.json current-date.txt lookback-date.txt; do
  rm -f "$OUTPUT_DIR/$f"
done
rm -rf "$OUTPUT_DIR/source-context"
rm -f "$OUTPUT_DIR"/changelog-*.md.bak

# Pre-flight: verify configured doc paths exist in repo
CONFIG_HELPER="$SCRIPTS_DIR/config-helper.py"
if [ -f "$CONFIG_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  MISSING_DOCS=$(python3 "$CONFIG_HELPER" "$OUTPUT_DIR/config.yaml" verify-docs "$REPO_DIR" 2>/dev/null)
  if [ -n "$MISSING_DOCS" ]; then
    echo "[$TIMESTAMP] WARN: doc paths not found in repo (check config.yaml docs[].repo_path):" >> "$LOG_FILE"
    while IFS=: read -r name rp; do
      echo "[$TIMESTAMP]   $name → $rp" >> "$LOG_FILE"
    done <<< "$MISSING_DOCS"
  fi
fi

# Fetch latest remote refs so git diff-tree can resolve merge commits from teammates' PRs
cd "$REPO_DIR"
git fetch origin --quiet 2>/dev/null || echo "[$TIMESTAMP] git fetch failed (non-fatal)" >> "$LOG_FILE"

# Track results — status is written ONCE at the end
SYNC_STATUS="failed"
DRIFT_STATUS="skipped"
SUGGEST_STATUS="skipped"
VERIFY_STATUS="skipped"
APPLY_STATUS="skipped"

# Determine platform for tool allowlists
PLATFORM=$(read_config platform || true)

case "$PLATFORM" in
  github)
    SYNC_TOOLS="Bash(gh:*),Bash(git:*),Write"
    APPLY_BASE_TOOLS="Read,Edit,Write,Bash(gh:*),Bash(git:*)"
    ;;
  gitlab)
    SYNC_TOOLS="Bash(glab:*),Bash(git:*),Write"
    APPLY_BASE_TOOLS="Read,Edit,Write,Bash(glab:*),Bash(git:*)"
    ;;
  bitbucket)
    SYNC_TOOLS="Bash(curl:*),Bash(git:*),Write"
    APPLY_BASE_TOOLS="Read,Edit,Write,Bash(curl:*),Bash(git:*)"
    ;;
  ado)
    SYNC_TOOLS="mcp__azure-devops__repo_list_pull_requests_by_repo_or_project"
    SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__repo_get_pull_request_by_id"
    SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__repo_list_pull_request_threads"
    SYNC_TOOLS="$SYNC_TOOLS,mcp__azure-devops__search_code"
    SYNC_TOOLS="$SYNC_TOOLS,Bash(git:*),Write"
    APPLY_BASE_TOOLS="Read,Edit,Write,Bash(git:*)"
    APPLY_BASE_TOOLS="$APPLY_BASE_TOOLS,mcp__azure-devops__repo_create_pull_request"
    APPLY_BASE_TOOLS="$APPLY_BASE_TOOLS,mcp__azure-devops__repo_create_branch"
    ;;
  *)
    echo "[$TIMESTAMP] ERROR: unknown platform '$PLATFORM'" >> "$LOG_FILE"
    exit 1
    ;;
esac

# Add Kusto telemetry tool if enabled (platform-independent)
if [ "$(read_config telemetry.enabled || true)" = "true" ]; then
  SYNC_TOOLS="$SYNC_TOOLS,mcp__kusto-mcp__kusto_query"
fi

# Pre-sync: discovery, feedback state, corrections, stale management, open PR limit
# All platform CLI calls happen in Python — no set -e traps on gh/glab/curl/az
FEEDBACK_FILE="$OUTPUT_DIR/feedback/open-prs.json"
PIPELINE_HELPER="$SCRIPTS_DIR/pipeline-helper.py"
if [ -f "$PIPELINE_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$PIPELINE_HELPER" pre-sync "$OUTPUT_DIR" "$REPO_DIR" "$PLATFORM" 2>/dev/null ||
    echo "[$TIMESTAMP] WARN: pre-sync helper failed (discovery/stale management may be incomplete)" >> "$LOG_FILE"

  # Log entries from pre-sync
  if [ -f "$OUTPUT_DIR/pre-sync-result.json" ]; then
    PRE_SYNC_LOG=$(python3 -c "
import json
d = json.load(open('$OUTPUT_DIR/pre-sync-result.json'))
print('\n'.join(d.get('log', [])))
" 2>/dev/null || true)
    if [ -n "$PRE_SYNC_LOG" ]; then
      while IFS= read -r line; do
        [ -n "$line" ] && echo "[$TIMESTAMP] $line" >> "$LOG_FILE"
      done <<< "$PRE_SYNC_LOG"
    fi

    # Check if we should proceed (open PR limit)
    PROCEED=$(python3 -c "import json;print(json.load(open('$OUTPUT_DIR/pre-sync-result.json')).get('proceed', True))" 2>/dev/null || echo "True")
    if [ "$PROCEED" = "False" ]; then
      SKIP_REASON=$(python3 -c "import json;print(json.load(open('$OUTPUT_DIR/pre-sync-result.json')).get('skip_reason',''))" 2>/dev/null || echo "")
      echo "[$TIMESTAMP] SKIPPED — $SKIP_REASON" >> "$LOG_FILE"
      log_metric "sync" "skipped-open-limit" "0"
      cat > "$STATUS_FILE" <<EOF
status: skipped
reason: $SKIP_REASON
timestamp: $TIMESTAMP
EOF
      exit 0
    fi
  fi
fi

# Call 1: Main sync (PRs + telemetry)
# Compute lookback date deterministically (prevents LLM date anchoring on old reports)
TODAY=$(date -u +"%Y-%m-%d")
echo "$TODAY" > "$OUTPUT_DIR/current-date.txt"
if [ -f "$OUTPUT_DIR/last-successful-run" ]; then
  LOOKBACK_DATE=$(cat "$OUTPUT_DIR/last-successful-run" | cut -c1-10)
  # Guard against future timestamps (clock drift, manual edit, NTP adjustment)
  if [[ "$LOOKBACK_DATE" > "$TODAY" ]]; then
    echo "[$TIMESTAMP] WARN: last-successful-run ($LOOKBACK_DATE) is in the future. Resetting to 1 day ago." >> "$LOG_FILE"
    LOOKBACK_DATE=$(date -u -v-1d +"%Y-%m-%d" 2>/dev/null || date -u -d "1 day ago" +"%Y-%m-%d" 2>/dev/null || echo "$TODAY")
  fi
else
  LOOKBACK_DATE=$(date -u -v-1d +"%Y-%m-%d" 2>/dev/null || date -u -d "1 day ago" +"%Y-%m-%d" 2>/dev/null || echo "$TODAY")
fi
echo "$LOOKBACK_DATE" > "$OUTPUT_DIR/lookback-date.txt"

# Pre-fetch PRs deterministically (GitHub only — other platforms use LLM tool calls)
case "$PLATFORM" in
  github)
    GH_OWNER=$(read_config github.owner || true)
    GH_REPO=$(read_config github.repo || true)
    if [ -n "$GH_OWNER" ] && [ -n "$GH_REPO" ]; then
      # Fetch merged PRs in the lookback window. gh auto-paginates (100 per API page).
      # Limit 1000 covers any realistic daily window; the --search date filter keeps it bounded.
      gh pr list -R "$GH_OWNER/$GH_REPO" --state merged \
        --search "merged:>=$LOOKBACK_DATE" \
        --json number,title,body,mergedAt,mergeCommit,files,author,reviews \
        --limit 1000 > "$OUTPUT_DIR/fetched-prs.json" 2>/dev/null || true
    fi
    ;;
esac

OUTPUT=$(retry claude -p "$(cat "$OUTPUT_DIR/sync-prompt.md")" \
  --add-dir "$OUTPUT_DIR" \
  --allowedTools "$SYNC_TOOLS" \
  --output-format text \
  2>&1) && SYNC_RC=0 || SYNC_RC=$?

if [ $SYNC_RC -eq 0 ] && [ -f "$OUTPUT_DIR/daily-report.md" ]; then
  SYNC_STATUS="success"
  echo "[$TIMESTAMP] SYNC SUCCESS" >> "$LOG_FILE"
  log_metric "sync" "success" "$SYNC_RC"

  # Pre-resolve file-to-section mappings (deterministic, no LLM)
  MATCH_HELPER="$SCRIPTS_DIR/match-helper.py"
  if [ -f "$MATCH_HELPER" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$MATCH_HELPER" "$OUTPUT_DIR/config.yaml" --resolve-report "$OUTPUT_DIR/daily-report.md" \
      > "$OUTPUT_DIR/resolved-mappings.md" 2>/dev/null ||
      echo "[$TIMESTAMP] WARN: match-helper failed (file-to-section mappings unavailable)" >> "$LOG_FILE"
  fi

  # Log match rate metric (config drift detection)
  if [ -f "$OUTPUT_DIR/resolved-mappings.md" ]; then
    TOTAL_MAPPED=$(wc -l < "$OUTPUT_DIR/resolved-mappings.md" | tr -d ' ')
    UNMAPPED_COUNT=$(grep -c "UNMAPPED" "$OUTPUT_DIR/resolved-mappings.md" || true)
    MAPPED_COUNT=$((TOTAL_MAPPED - UNMAPPED_COUNT))
    log_metric "match-rate" "$MAPPED_COUNT/$TOTAL_MAPPED" "0"
    if [ "$TOTAL_MAPPED" -gt 5 ] && [ "$MAPPED_COUNT" -eq 0 ]; then
      echo "[$TIMESTAMP] WARN: 0/$TOTAL_MAPPED files matched package_map. Check config." >> "$LOG_FILE"
    fi
  fi

  # Pre-process drift detection (deterministic: parse, group, dedup, lifecycle)
  DRIFT_HELPER="$SCRIPTS_DIR/drift-helper.py"
  if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$DRIFT_HELPER" pre-process "$OUTPUT_DIR" 2>/dev/null ||
      echo "[$TIMESTAMP] WARN: drift pre-process failed (LLM will fall back to raw report parsing)" >> "$LOG_FILE"
  fi

  # Call 2: Drift detection (reads pre-processed context + doc content, writes drift files)
  # Runs independently — failure here does NOT affect sync status
  if [ -f "$OUTPUT_DIR/drift-prompt.md" ]; then
    DRIFT_OUTPUT=$(retry claude -p "$(cat "$OUTPUT_DIR/drift-prompt.md")" \
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
    log_metric "drift" "$DRIFT_STATUS" "$DRIFT_RC"

    # Post-drift: apply lifecycle rules (expire LOW >7 days, trim checked >30 days).
    # The LLM writes drift-status.md but cannot enforce these rules itself.
    if [ "$DRIFT_STATUS" = "success" ] && [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
      python3 "$DRIFT_HELPER" apply-lifecycle "$OUTPUT_DIR" 2>/dev/null ||
        echo "[$TIMESTAMP] WARN: drift lifecycle application failed" >> "$LOG_FILE"
    fi
  fi

  # Call 3: Suggested updates + changelog (only if drift found actionable alerts)
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$OUTPUT_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$OUTPUT_DIR/drift-report.md" 2>/dev/null; then

    # Pre-compute suggest dedup (deterministic: changelog + open PR filtering)
    if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
      python3 "$DRIFT_HELPER" suggest-dedup "$OUTPUT_DIR" 2>/dev/null ||
        echo "[$TIMESTAMP] WARN: suggest-dedup failed (duplicate suggestions possible)" >> "$LOG_FILE"
    fi

    # Copy mapped source files for suggest context (ground truth for the LLM)
    if [ -f "$PIPELINE_HELPER" ] && command -v python3 >/dev/null 2>&1; then
      python3 "$PIPELINE_HELPER" copy-sources "$OUTPUT_DIR" "$REPO_DIR" 2>/dev/null ||
        echo "[$TIMESTAMP] WARN: copy-sources failed (LLM may lack source file context)" >> "$LOG_FILE"
    fi

    # Back up existing changelogs before suggest (for deterministic merge after)
    for f in "$OUTPUT_DIR"/changelog-*.md; do
      [ -f "$f" ] && cp "$f" "$f.bak"
    done

    SUGGEST_OUTPUT=$(retry claude -p "$(cat "$OUTPUT_DIR/suggest-prompt.md")" \
      --add-dir "$OUTPUT_DIR" \
      --allowedTools "Read,Write" \
      --output-format text \
      2>&1) && SUGGEST_RC=0 || SUGGEST_RC=$?

    if [ $SUGGEST_RC -eq 0 ]; then
      SUGGEST_STATUS="success"
      echo "[$TIMESTAMP] SUGGEST SUCCESS" >> "$LOG_FILE"
      log_metric "suggest" "success" "$SUGGEST_RC"

      # Post-process changelogs: merge only new entries, preserve section order
      if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
        python3 "$DRIFT_HELPER" merge-changelogs "$OUTPUT_DIR" 2>/dev/null ||
          echo "[$TIMESTAMP] WARN: changelog merge failed (LLM version kept as-is)" >> "$LOG_FILE"
      fi

      if grep -q "Verified: NO" "$OUTPUT_DIR/drift-suggestions.md" 2>/dev/null; then
        echo "[$TIMESTAMP] SUGGEST WARNING: some suggestions are UNVERIFIED" >> "$LOG_FILE"
      fi

      # Deterministic verification (Python, not LLM)
      VERIFY_HELPER="$SCRIPTS_DIR/verify-helper.py"

      # FIND verification: does the target text exist in the doc?
      if [ -f "$VERIFY_HELPER" ] && command -v python3 >/dev/null 2>&1; then
        python3 "$VERIFY_HELPER" verify-finds "$OUTPUT_DIR" "$REPO_DIR" 2>/dev/null || \
          echo "[$TIMESTAMP] FIND VERIFY: some FIND blocks failed verification" >> "$LOG_FILE"
      fi

      # REPLACE verification: are code references correct?
      if [ -f "$VERIFY_HELPER" ] && [ -d "$OUTPUT_DIR/source-context" ] && command -v python3 >/dev/null 2>&1; then
        python3 "$VERIFY_HELPER" verify-replaces "$OUTPUT_DIR" "$REPO_DIR" 2>/dev/null || \
          echo "[$TIMESTAMP] REPLACE VERIFY: some suggestions BLOCKED (value mismatch)" >> "$LOG_FILE"
      fi

      # Call 3v: Shadow verification (log only, does not gate apply)
      # Runs in a subshell so failures never crash the main pipeline.
      if [ "$(read_config multi_model.enabled || true)" = "true" ] \
         && grep -q "CONFIDENT" "$OUTPUT_DIR/drift-suggestions.md" 2>/dev/null; then
        (
          VERIFY_VARIATION_FILE="$OUTPUT_DIR/verify-variation.md"
          if [ -f "$VERIFY_VARIATION_FILE" ]; then
            VERIFY_VARIATION=$(cat "$VERIFY_VARIATION_FILE")
            claude -p "$(cat "$OUTPUT_DIR/suggest-prompt.md")" \
              --append-system-prompt "$VERIFY_VARIATION" \
              --model opus \
              --add-dir "$OUTPUT_DIR" \
              --allowedTools "Read,Write" \
              --output-format text \
              > /dev/null 2>&1 && VERIFY_STATUS="shadow-success" || VERIFY_STATUS="shadow-failed"
            echo "[$TIMESTAMP] VERIFY (shadow): $VERIFY_STATUS" >> "$LOG_FILE"
            log_metric "verify-shadow" "$VERIFY_STATUS" "0"
          fi
        ) || echo "[$TIMESTAMP] VERIFY (shadow): skipped (call failed)" >> "$LOG_FILE"
      fi

      # Call 4: Apply CONFIDENT + self-verified suggestions as PR
      # Single-model with self-verification is the quality gate (14/14 in testing)
      if [ "$DRY_RUN" = "true" ]; then
        APPLY_STATUS="dry-run"
        echo "[$TIMESTAMP] DRY RUN — skipping apply" >> "$LOG_FILE"
      elif [ -f "$OUTPUT_DIR/apply-prompt.md" ] \
         && [ "$(read_config auto_pr.enabled || true)" = "true" ] \
         && [ -f "$OUTPUT_DIR/drift-suggestions.md" ] \
         && ! grep -q "suggestion_count: 0" "$OUTPUT_DIR/drift-suggestions.md"; then

        APPLY_OUTPUT=$(retry claude -p "$(cat "$OUTPUT_DIR/apply-prompt.md")" \
          --add-dir "$OUTPUT_DIR" \
          --add-dir "$REPO_DIR" \
          --allowedTools "$APPLY_BASE_TOOLS" \
          --output-format text \
          2>&1) && APPLY_RC=0 || APPLY_RC=$?

        if [ $APPLY_RC -eq 0 ]; then
          APPLY_STATUS="success"
          echo "[$TIMESTAMP] APPLY SUCCESS" >> "$LOG_FILE"
        else
          APPLY_STATUS="failed"
          echo "[$TIMESTAMP] APPLY FAILED (exit $APPLY_RC)" >> "$LOG_FILE"
          echo "$APPLY_OUTPUT" | tail -10 >> "$LOG_FILE"
        fi
        log_metric "apply" "$APPLY_STATUS" "${APPLY_RC:-0}"
      fi
    else
      SUGGEST_STATUS="failed"
      echo "[$TIMESTAMP] SUGGEST FAILED (exit $SUGGEST_RC)" >> "$LOG_FILE"
      echo "$SUGGEST_OUTPUT" | tail -10 >> "$LOG_FILE"
      log_metric "suggest" "failed" "$SUGGEST_RC"
    fi
  fi
else
  echo "[$TIMESTAMP] SYNC FAILED (exit $SYNC_RC)" >> "$LOG_FILE"
  echo "$OUTPUT" | tail -20 >> "$LOG_FILE"
  log_metric "sync" "failed" "$SYNC_RC"
fi

# Compute acceptance rate if feedback data exists
ACCEPTANCE_RATE="n/a"
FEEDBACK_HELPER="$SCRIPTS_DIR/feedback-helper.py"
if [ -f "$FEEDBACK_FILE" ] && [ -f "$FEEDBACK_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  ACCEPTANCE_RATE=$(python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" acceptance-rate 2>/dev/null || echo "n/a")
fi

# Write status ONCE at the end
cat > "$STATUS_FILE" <<EOF
status: $SYNC_STATUS
drift: $DRIFT_STATUS
suggest: $SUGGEST_STATUS
verify: $VERIFY_STATUS
apply: $APPLY_STATUS
acceptance_rate: $ACCEPTANCE_RATE
timestamp: $TIMESTAMP
EOF

# Record successful completion time for lookback dedup
# Only advance timestamp if sync AND drift both succeeded (or drift was skipped with no alerts).
# This prevents: "sync succeeded but drift failed → timestamp advances → PRs never re-analyzed"
if [ "$SYNC_STATUS" = "success" ] && [ "$DRIFT_STATUS" != "failed" ]; then
  # Read counts from drift-context.json (deterministic, not grep on LLM output)
  if [ -f "$OUTPUT_DIR/drift-context.json" ]; then
    RELEVANT_COUNT=$(python3 -c "import json;d=json.load(open('$OUTPUT_DIR/drift-context.json'));print(d.get('summary',{}).get('relevant_count',0))" 2>/dev/null || true)
    PR_COUNT_VAL=$(python3 -c "import json;d=json.load(open('$OUTPUT_DIR/drift-context.json'));print(d.get('summary',{}).get('pr_count',0))" 2>/dev/null || true)
  else
    RELEVANT_COUNT=0
    PR_COUNT_VAL=0
  fi
  [ -z "$RELEVANT_COUNT" ] && RELEVANT_COUNT=0
  [ -z "$PR_COUNT_VAL" ] && PR_COUNT_VAL=0
  if [ "$RELEVANT_COUNT" -gt 0 ] || [ "${PR_COUNT_VAL:-0}" -eq 0 ]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$OUTPUT_DIR/last-successful-run"
  else
    echo "[$TIMESTAMP] WARN: ${PR_COUNT_VAL} PRs found, 0 relevant. Timestamp not advanced." >> "$LOG_FILE"
  fi
fi
