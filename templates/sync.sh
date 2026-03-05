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

# Retry a command with exponential backoff (for transient API/network failures)
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
PLATFORM=$(grep "^platform:" "$OUTPUT_DIR/config.yaml" 2>/dev/null | awk '{print $2}' | tr -d '"')

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

# Feedback: discover + check state of pending autodocs PRs (bash only, no LLM call)
FEEDBACK_FILE="$OUTPUT_DIR/feedback/open-prs.json"
FEEDBACK_HELPER="$SCRIPTS_DIR/feedback-helper.py"

# Read platform config once for feedback operations
FB_GH_OWNER="" ; FB_GH_REPO=""
FB_GL_PROJECT=""
FB_BB_WS="" ; FB_BB_REPO=""
FB_ADO_ORG="" ; FB_ADO_PROJECT=""
if command -v python3 >/dev/null 2>&1; then
  case "$PLATFORM" in
    github)    FB_GH_OWNER=$(read_config github.owner || true); FB_GH_REPO=$(read_config github.repo || true) ;;
    gitlab)    FB_GL_PROJECT=$(read_config gitlab.project_path || true) ;;
    bitbucket) FB_BB_WS=$(read_config bitbucket.workspace || true); FB_BB_REPO=$(read_config bitbucket.repo || true) ;;
    ado)       FB_ADO_ORG=$(read_config ado.org || true); FB_ADO_PROJECT=$(read_config ado.project || true) ;;
  esac
fi

# Discover existing autodocs PRs not yet tracked (bootstrap + orphan recovery)
if command -v python3 >/dev/null 2>&1 && [ -f "$FEEDBACK_HELPER" ]; then
  mkdir -p "$OUTPUT_DIR/feedback"
  case "$PLATFORM" in
    github)
      if [ -n "$FB_GH_OWNER" ] && [ -n "$FB_GH_REPO" ]; then
        discovered=$(gh pr list -R "$FB_GH_OWNER/$FB_GH_REPO" \
          --search "head:autodocs/ is:open" \
          --json number,createdAt --limit 50 2>/dev/null || true)
        [ -n "$discovered" ] && [ "$discovered" != "[]" ] && \
          python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" discover "$discovered" github 2>/dev/null
      fi
      ;;
  esac
fi

# Check state of tracked PRs (merged/closed)
if [ -f "$FEEDBACK_FILE" ] && command -v python3 >/dev/null 2>&1; then
  if [ -f "$FEEDBACK_HELPER" ]; then
    open_prs=$(python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" list-prs --open-only 2>/dev/null)
    if [ -n "$open_prs" ]; then
      while IFS= read -r pr_num; do
        [ -z "$pr_num" ] && continue
        pr_state=""
        case "$PLATFORM" in
          github)
            [ -n "$FB_GH_OWNER" ] && [ -n "$FB_GH_REPO" ] && \
              pr_state=$(gh pr view "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" --json state --jq '.state' 2>/dev/null)
            ;;
          gitlab)
            if [ -n "$FB_GL_PROJECT" ] && command -v glab >/dev/null 2>&1; then
              gl_raw=$(glab mr view "$pr_num" -R "$FB_GL_PROJECT" -F json 2>/dev/null \
                | python3 -c "import sys,json;print(json.load(sys.stdin).get('state',''))" 2>/dev/null)
              case "$gl_raw" in
                merged) pr_state="MERGED" ;;
                closed) pr_state="CLOSED" ;;
              esac
            fi
            ;;
          bitbucket)
            if [ -n "$FB_BB_WS" ] && [ -n "$FB_BB_REPO" ] && [ -n "${BITBUCKET_TOKEN:-}" ]; then
              bb_raw=$(curl -s -H "Authorization: Bearer $BITBUCKET_TOKEN" \
                "https://api.bitbucket.org/2.0/repositories/$FB_BB_WS/$FB_BB_REPO/pullrequests/$pr_num" \
                | python3 -c "import sys,json;print(json.load(sys.stdin).get('state',''))" 2>/dev/null)
              case "$bb_raw" in
                MERGED) pr_state="MERGED" ;;
                DECLINED|SUPERSEDED) pr_state="CLOSED" ;;
              esac
            fi
            ;;
          ado)
            if [ -n "$FB_ADO_ORG" ] && [ -n "$FB_ADO_PROJECT" ] && command -v az >/dev/null 2>&1; then
              ado_raw=$(az repos pr show --id "$pr_num" \
                --org "https://dev.azure.com/$FB_ADO_ORG" -p "$FB_ADO_PROJECT" \
                --query "status" -o tsv 2>/dev/null)
              case "$ado_raw" in
                completed) pr_state="MERGED" ;;
                abandoned) pr_state="CLOSED" ;;
              esac
            fi
            ;;
        esac
        if [ "$pr_state" = "MERGED" ]; then
          python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" update-pr "$pr_num" merged "$(date +%Y-%m-%d)"
          echo "[$TIMESTAMP] FEEDBACK: PR #$pr_num merged" >> "$LOG_FILE"
        elif [ "$pr_state" = "CLOSED" ]; then
          python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" update-pr "$pr_num" closed
          echo "[$TIMESTAMP] FEEDBACK: PR #$pr_num closed" >> "$LOG_FILE"
        fi
      done <<< "$open_prs"
    fi
  fi
fi

# Stale PR management (two-phase: warn then close, deterministic)
STALE_HELPER="$SCRIPTS_DIR/stale-helper.py"
if [ -f "$FEEDBACK_FILE" ] && [ -f "$STALE_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  # Collect stale labels from platform (which open PRs have autodocs:stale)
  STALE_LABELS="{}"
  case "$PLATFORM" in
    github)
      if [ -n "$FB_GH_OWNER" ] && [ -n "$FB_GH_REPO" ]; then
        STALE_LABELS=$(gh pr list -R "$FB_GH_OWNER/$FB_GH_REPO" \
          --label "autodocs:stale" --state open \
          --json number --jq '[.[] | {(.number|tostring): true}] | add // {}' 2>/dev/null || echo "{}")
      fi
      ;;
  esac

  stale_output=$(python3 "$STALE_HELPER" "$FEEDBACK_FILE" "$OUTPUT_DIR/config.yaml" "$REPO_DIR" \
    list-stale "$(date +%Y-%m-%d)" "$STALE_LABELS" 2>/dev/null)
  if [ -n "$stale_output" ]; then
    while IFS='|' read -r pr_num action reason; do
      [ -z "$pr_num" ] && continue
      case "$PLATFORM" in
        github)
          if [ "$action" = "warn" ]; then
            gh pr comment "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" \
              --body "**autodocs**: $reason. This PR will be auto-closed in 7 days if no activity. Add label \`autodocs:keep-open\` to prevent." 2>/dev/null || true
            gh pr edit "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" --add-label "autodocs:stale" 2>/dev/null || true
          elif [ "$action" = "close" ]; then
            gh pr comment "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" \
              --body "**autodocs**: Closing — $reason. A fresh PR will be generated if changes are still needed." 2>/dev/null || true
            gh pr close "$pr_num" -R "$FB_GH_OWNER/$FB_GH_REPO" 2>/dev/null || true
            python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" update-pr "$pr_num" closed 2>/dev/null || true
          fi
          echo "[$TIMESTAMP] STALE: $action PR #$pr_num ($reason)" >> "$LOG_FILE"
          ;;
      esac
    done <<< "$stale_output"
  fi
fi

# Check open PR limit (prevent accumulation)
MAX_OPEN=$(read_config limits.max_open_prs || true)
[ -z "$MAX_OPEN" ] && MAX_OPEN=10
if [ -f "$FEEDBACK_FILE" ] && command -v python3 >/dev/null 2>&1; then
  OPEN_COUNT=$(python3 "$FEEDBACK_HELPER" "$FEEDBACK_FILE" list-prs --open-only 2>/dev/null | wc -l | tr -d ' ')
  if [ "$OPEN_COUNT" -ge "$MAX_OPEN" ]; then
    echo "[$TIMESTAMP] SKIPPED — $OPEN_COUNT open PRs (limit: $MAX_OPEN). Review existing PRs first." >> "$LOG_FILE"
    log_metric "sync" "skipped-open-limit" "0"
    cat > "$STATUS_FILE" <<EOF
status: skipped
reason: open PR limit ($OPEN_COUNT/$MAX_OPEN)
timestamp: $TIMESTAMP
EOF
    exit 0
  fi
fi

# Call 1: Main sync (PRs + telemetry)

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
      > "$OUTPUT_DIR/resolved-mappings.md" 2>/dev/null || true
  fi

  # Pre-process drift detection (deterministic: parse, group, dedup, lifecycle)
  DRIFT_HELPER="$SCRIPTS_DIR/drift-helper.py"
  if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$DRIFT_HELPER" pre-process "$OUTPUT_DIR" 2>/dev/null || true
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
  fi

  # Call 3: Suggested updates + changelog (only if drift found actionable alerts)
  if [ "$DRIFT_STATUS" = "success" ] && [ -f "$OUTPUT_DIR/suggest-prompt.md" ] \
     && grep -qE "HIGH|CRITICAL" "$OUTPUT_DIR/drift-report.md" 2>/dev/null; then

    # Pre-compute suggest dedup (deterministic: changelog + open PR filtering)
    if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
      python3 "$DRIFT_HELPER" suggest-dedup "$OUTPUT_DIR" 2>/dev/null || true
    fi

    SUGGEST_OUTPUT=$(retry claude -p "$(cat "$OUTPUT_DIR/suggest-prompt.md")" \
      --add-dir "$OUTPUT_DIR" \
      --allowedTools "Read,Write" \
      --output-format text \
      2>&1) && SUGGEST_RC=0 || SUGGEST_RC=$?

    if [ $SUGGEST_RC -eq 0 ]; then
      SUGGEST_STATUS="success"
      echo "[$TIMESTAMP] SUGGEST SUCCESS" >> "$LOG_FILE"
      log_metric "suggest" "success" "$SUGGEST_RC"
      if grep -q "Verified: NO" "$OUTPUT_DIR/drift-suggestions.md" 2>/dev/null; then
        echo "[$TIMESTAMP] SUGGEST WARNING: some suggestions are UNVERIFIED" >> "$LOG_FILE"
      fi

      # Deterministic FIND verification (Python, not LLM)
      # Mechanically checks every FIND block exists in the target doc file
      if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
        python3 "$DRIFT_HELPER" verify-finds "$OUTPUT_DIR" "$REPO_DIR" 2>/dev/null || \
          echo "[$TIMESTAMP] FIND VERIFY: some FIND blocks failed verification" >> "$LOG_FILE"
      fi

      # Call 3v: Shadow verification (log only, does not gate apply)
      # Runs in a subshell so failures never crash the main pipeline.
      if grep -q "multi_model" "$OUTPUT_DIR/config.yaml" 2>/dev/null \
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
         && grep -q "auto_pr" "$OUTPUT_DIR/config.yaml" 2>/dev/null \
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
if [ "$SYNC_STATUS" = "success" ]; then
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$OUTPUT_DIR/last-successful-run"
fi
