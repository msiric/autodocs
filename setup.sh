#!/bin/bash
set -euo pipefail

# autodocs setup wizard
# Auto-detects platform, owner, team, and paths where possible.
# Falls back to manual input when detection fails.
# Usage: ./setup.sh [--quick]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/templates"

QUICK_MODE=false
if [ "${1:-}" = "--quick" ]; then
  QUICK_MODE=true
fi

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

confirm() {
  if $QUICK_MODE; then return 0; fi
  local prompt="$1"
  read -rp "$prompt [Y/n] " answer
  [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

detect_platform() {
  local remote
  remote=$(cd "$1" && git remote get-url origin 2>/dev/null) || return 1
  case "$remote" in
    *github.com*)                       echo "github" ;;
    *gitlab*)                           echo "gitlab" ;;
    *bitbucket*)                        echo "bitbucket" ;;
    *dev.azure.com*|*visualstudio.com*) echo "ado" ;;
    *)                                  return 1 ;;
  esac
}

detect_owner_repo() {
  local remote
  remote=$(cd "$1" && git remote get-url origin 2>/dev/null) || return 1
  # Handles SSH (git@host:owner/repo.git) and HTTPS (https://host/owner/repo.git)
  echo "$remote" | sed 's|.*[:/]\([^:]*\)$|\1|' | sed 's|\.git$||'
}

discover_team() {
  local platform="$1"
  case "$platform" in
    github)
      gh pr list -R "$GH_OWNER/$GH_REPO" --state merged --limit 50 \
        --json author --jq '[.[].author.login] | unique | .[]' 2>/dev/null ;;
    gitlab)
      glab mr list --merged -F json -R "$GITLAB_PROJECT_PATH" --per-page 50 2>/dev/null \
        | jq -r '[.[].author.username] | unique | .[]' 2>/dev/null ;;
    bitbucket)
      [ -n "${BITBUCKET_TOKEN:-}" ] && \
      curl -s -H "Authorization: Bearer $BITBUCKET_TOKEN" \
        "https://api.bitbucket.org/2.0/repositories/$BB_WORKSPACE/$BB_REPO/pullrequests?state=MERGED&pagelen=50" \
        | jq -r '[.values[].author.nickname] | unique | .[]' 2>/dev/null ;;
  esac
}

discover_paths() {
  grep -oE '[a-zA-Z][a-zA-Z0-9/_.-]+\.(ts|js|py|tsx|jsx|go|rs|java|rb|cs)' "$1" \
    | sed 's|/[^/]*$||' | sort -u 2>/dev/null
}

# ---------------------------------------------------------------------------
echo "=== autodocs setup ==="
echo ""
# ---------------------------------------------------------------------------

# --- Step 1: Repo path ---

if [ -d ".git" ]; then
  REPO_DIR="$(pwd)"
  if confirm "Use current directory as repo ($REPO_DIR)?"; then
    : # accepted
  else
    read -rp "Path to your git repo: " REPO_DIR
    REPO_DIR="${REPO_DIR/#\~/$HOME}"
  fi
else
  read -rp "Path to your git repo (e.g., ~/Documents/my-repo): " REPO_DIR
  REPO_DIR="${REPO_DIR/#\~/$HOME}"
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Error: $REPO_DIR is not a git repository."
  exit 1
fi

# --- Step 2: Output directory ---

DEFAULT_OUTPUT="$REPO_DIR/.autodocs"
read -rp "Output directory (default: $DEFAULT_OUTPUT): " OUTPUT_DIR
OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT}"
OUTPUT_DIR="${OUTPUT_DIR/#\~/$HOME}"
mkdir -p "$OUTPUT_DIR"

echo ""

# --- Step 3: Platform + repo details ---

PLATFORM=""
GH_OWNER="" ; GH_REPO=""
GITLAB_HOST="gitlab.com" ; GITLAB_PROJECT_PATH=""
BB_WORKSPACE="" ; BB_REPO=""
ADO_ORG="" ; ADO_PROJECT="" ; ADO_REPO="" ; ADO_REPO_ID=""

DETECTED_PLATFORM=$(detect_platform "$REPO_DIR" || true)
if [ -n "$DETECTED_PLATFORM" ]; then
  OWNER_REPO=$(detect_owner_repo "$REPO_DIR" || true)
  if [ -n "$OWNER_REPO" ] && [ "$DETECTED_PLATFORM" != "ado" ]; then
    echo "Detected: $DETECTED_PLATFORM ($OWNER_REPO)"
    if confirm "Correct?"; then
      PLATFORM="$DETECTED_PLATFORM"
      case "$PLATFORM" in
        github)
          GH_OWNER="${OWNER_REPO%%/*}"
          GH_REPO="${OWNER_REPO#*/}"
          ;;
        gitlab)
          GITLAB_PROJECT_PATH="$OWNER_REPO"
          ;;
        bitbucket)
          BB_WORKSPACE="${OWNER_REPO%%/*}"
          BB_REPO="${OWNER_REPO#*/}"
          ;;
      esac
    fi
  fi
fi

if [ -z "$PLATFORM" ]; then
  echo "Platform:"
  echo "  1. GitHub"
  echo "  2. Azure DevOps"
  echo "  3. GitLab"
  echo "  4. Bitbucket"
  read -rp "Select (1-4): " PLATFORM_CHOICE

  case "$PLATFORM_CHOICE" in
    1)
      PLATFORM="github"
      read -rp "GitHub owner (user or org): " GH_OWNER
      read -rp "GitHub repo name: " GH_REPO
      ;;
    3)
      PLATFORM="gitlab"
      read -rp "GitLab host (default: gitlab.com): " GITLAB_HOST
      GITLAB_HOST="${GITLAB_HOST:-gitlab.com}"
      read -rp "GitLab project path (e.g., mygroup/myrepo): " GITLAB_PROJECT_PATH
      ;;
    4)
      PLATFORM="bitbucket"
      read -rp "Bitbucket workspace: " BB_WORKSPACE
      read -rp "Bitbucket repo name: " BB_REPO
      echo "  Note: Set BITBUCKET_TOKEN environment variable for API access."
      ;;
    *)
      PLATFORM="ado"
      read -rp "ADO organization name: " ADO_ORG
      read -rp "ADO project name: " ADO_PROJECT
      read -rp "ADO repository name: " ADO_REPO

      echo ""
      echo "Resolving repository GUID..."
      read -rp "Enter repo GUID (or press Enter to resolve via Claude Code): " ADO_REPO_ID

      if [ -z "$ADO_REPO_ID" ]; then
        ADO_REPO_ID=$(cd "$REPO_DIR" && claude -p "Call mcp__azure-devops__repo_get_repo_by_name_or_id with project=$ADO_PROJECT, repositoryNameOrId=$ADO_REPO. Return ONLY the repository ID (GUID), nothing else." \
          --allowedTools "mcp__azure-devops__repo_get_repo_by_name_or_id" \
          --output-format text 2>/dev/null | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1) || true

        if [ -z "$ADO_REPO_ID" ]; then
          echo "Could not resolve. Enter manually."
          read -rp "Repo GUID: " ADO_REPO_ID
        else
          echo "Resolved: $ADO_REPO_ID"
        fi
      fi
      ;;
  esac
fi

echo ""

# --- Step 4: Owner ---

OWNER_NAME="" ; OWNER_EMAIL="" ; OWNER_ADO_ID=""
DETECTED_NAME=$(git config user.name 2>/dev/null || true)
DETECTED_EMAIL=$(git config user.email 2>/dev/null || true)

if [ -n "$DETECTED_NAME" ] && [ -n "$DETECTED_EMAIL" ]; then
  echo "Detected owner: $DETECTED_NAME ($DETECTED_EMAIL)"
  if confirm "Correct?"; then
    OWNER_NAME="$DETECTED_NAME"
    OWNER_EMAIL="$DETECTED_EMAIL"
  fi
fi

if [ -z "$OWNER_NAME" ]; then
  read -rp "Your name: " OWNER_NAME
  read -rp "Your email: " OWNER_EMAIL
fi

if [ "$PLATFORM" = "ado" ]; then
  read -rp "Your ADO ID (GUID): " OWNER_ADO_ID
fi

echo ""

# --- Step 5: Team members ---

DISCOVERED_TEAM=""
if [ "$PLATFORM" != "ado" ]; then
  echo "Discovering team members from recent PRs..."
  DISCOVERED_TEAM=$(discover_team "$PLATFORM" || true)

  if [ -n "$DISCOVERED_TEAM" ]; then
    echo "Found recent contributors:"
    echo "$DISCOVERED_TEAM" | nl
    if ! confirm "Include all as team members?"; then
      DISCOVERED_TEAM=""
      echo "  You can add team members to config.yaml later."
    fi
  else
    echo "  No recent contributors found. Add team members to config.yaml later."
  fi
else
  echo "  Add team members to config.yaml after setup (ADO requires manual ID entry)."
fi

echo ""

# --- Step 6: Feature name ---

read -rp "Feature/area name (e.g., Channel Pages, Auth, Search): " FEATURE_NAME

echo ""

# --- Step 7: Doc file + path discovery ---

SELECTED_DOC="" ; DISCOVERED_RELEVANT_PATHS=""

if ! $QUICK_MODE; then
  echo "Looking for documentation files..."
  DOC_FILES=$(cd "$REPO_DIR" && find . -name "*.md" -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/.autodocs/*" -not -name "README.md" -not -name "CHANGELOG.md" -not -name "LICENSE.md" 2>/dev/null | sort | head -10)

  if [ -n "$DOC_FILES" ]; then
    echo "Found markdown files:"
    echo "$DOC_FILES" | nl
    read -rp "Monitor which doc? (number, or Enter to skip): " DOC_CHOICE

    if [ -n "$DOC_CHOICE" ]; then
      SELECTED_DOC=$(echo "$DOC_FILES" | sed -n "${DOC_CHOICE}p" | sed 's|^\./||')
      if [ -n "$SELECTED_DOC" ]; then
        echo "Selected: $SELECTED_DOC"

        DISCOVERED_RELEVANT_PATHS=$(discover_paths "$REPO_DIR/$SELECTED_DOC" || true)
        if [ -n "$DISCOVERED_RELEVANT_PATHS" ]; then
          echo "Found code paths referenced in doc:"
          echo "$DISCOVERED_RELEVANT_PATHS" | sed 's/^/  - /'
          if ! confirm "Use these as relevant_paths?"; then
            DISCOVERED_RELEVANT_PATHS=""
          fi
        fi
      fi
    fi
  else
    echo "  No documentation files found. Add docs to config.yaml later."
  fi
fi

echo ""

# --- Step 8: Telemetry ---

TELEMETRY_ENABLED="false"
if ! $QUICK_MODE; then
  read -rp "Use Kusto telemetry? (y/n, default: n): " USE_TELEMETRY
  if [[ "${USE_TELEMETRY:-n}" =~ ^[Yy] ]]; then
    TELEMETRY_ENABLED="true"
  fi
fi

echo ""

# --- Step 9: Schedule ---

SCHEDULE_HOUR="17"
if ! $QUICK_MODE; then
  read -rp "Daily sync hour (UTC, 0-23, default: 17): " SCHEDULE_HOUR_INPUT
  SCHEDULE_HOUR="${SCHEDULE_HOUR_INPUT:-17}"
fi

echo ""

# --- Step 10: Generate config ---

CONFIG_FILE="$OUTPUT_DIR/config.yaml"
if [ -f "$CONFIG_FILE" ]; then
  echo "Config already exists at $CONFIG_FILE — skipping generation."
  echo "Delete it and re-run setup to regenerate."
else
  # Build platform-specific username field for owner
  OWNER_USERNAME_FIELD=""
  case "$PLATFORM" in
    github)   OWNER_USERNAME_FIELD="  github_username: \"${GH_OWNER}\"" ;;
    gitlab)   OWNER_USERNAME_FIELD="  gitlab_username: \"${OWNER_NAME}\"  # Update with your GitLab username" ;;
    bitbucket) OWNER_USERNAME_FIELD="  bitbucket_username: \"${OWNER_NAME}\"  # Update with your Bitbucket username" ;;
    ado)      OWNER_USERNAME_FIELD="  ado_id: \"${OWNER_ADO_ID}\"" ;;
  esac

  cat > "$CONFIG_FILE" <<CONFIGEOF
# autodocs configuration — generated by setup.sh
# Edit this file to customize. Changes take effect on the next sync.

platform: "$PLATFORM"

$(case "$PLATFORM" in
  github)   echo "github:"; echo "  owner: \"$GH_OWNER\""; echo "  repo: \"$GH_REPO\"" ;;
  gitlab)   echo "gitlab:"; echo "  host: \"$GITLAB_HOST\""; echo "  project_path: \"$GITLAB_PROJECT_PATH\"" ;;
  bitbucket) echo "bitbucket:"; echo "  workspace: \"$BB_WORKSPACE\""; echo "  repo: \"$BB_REPO\"" ;;
  ado)      echo "ado:"; echo "  org: \"$ADO_ORG\""; echo "  project: \"$ADO_PROJECT\""; echo "  repo: \"$ADO_REPO\""; echo "  repo_id: \"$ADO_REPO_ID\"" ;;
esac)

owner:
  name: "$OWNER_NAME"
  email: "$OWNER_EMAIL"
$OWNER_USERNAME_FIELD

$(if [ -n "$DISCOVERED_TEAM" ]; then
  echo "team_members:"
  echo "$DISCOVERED_TEAM" | while read -r username; do
    echo "  - name: \"$username\""
    case "$PLATFORM" in
      github)    echo "    github_username: \"$username\"" ;;
      gitlab)    echo "    gitlab_username: \"$username\"" ;;
      bitbucket) echo "    bitbucket_username: \"$username\"" ;;
    esac
  done
else
  echo "team_members: []"
fi)

$(if [ -n "$DISCOVERED_RELEVANT_PATHS" ]; then
  echo "relevant_paths:"
  echo "$DISCOVERED_RELEVANT_PATHS" | while read -r path; do
    echo "  - $path/"
  done
else
  echo "relevant_paths: []"
fi)

relevant_pattern: ""

telemetry:
  enabled: $TELEMETRY_ENABLED

$(if [ -n "$SELECTED_DOC" ]; then
  doc_name=$(basename "$SELECTED_DOC")
  echo "docs:"
  echo "  - name: \"$doc_name\""
  echo "    repo_path: \"$SELECTED_DOC\""
else
  echo "# docs: []"
fi)

# auto_pr:
#   enabled: true
#   target_branch: "main"
#   branch_prefix: "autodocs/"

last_verified: "$(date +%Y-%m-%d)"
CONFIGEOF

  echo "Config generated: $CONFIG_FILE"
fi

echo ""

# --- Step 11: Render prompts + scripts ---

export OUTPUT_DIR REPO_DIR FEATURE_NAME OWNER_NAME SCHEDULE_HOUR

echo "Rendering prompts..."
envsubst '${OUTPUT_DIR} ${FEATURE_NAME} ${OWNER_NAME}' < "$TEMPLATES_DIR/sync-prompt.md" > "$OUTPUT_DIR/sync-prompt.md"
envsubst '${OUTPUT_DIR}' < "$TEMPLATES_DIR/drift-prompt.md" > "$OUTPUT_DIR/drift-prompt.md"
envsubst '${OUTPUT_DIR}' < "$TEMPLATES_DIR/suggest-prompt.md" > "$OUTPUT_DIR/suggest-prompt.md"
envsubst '${OUTPUT_DIR}' < "$TEMPLATES_DIR/apply-prompt.md" > "$OUTPUT_DIR/apply-prompt.md"
envsubst '${OUTPUT_DIR}' < "$TEMPLATES_DIR/structural-scan-prompt.md" > "$OUTPUT_DIR/structural-scan-prompt.md"

echo "Rendering scripts..."
envsubst '${OUTPUT_DIR} ${REPO_DIR}' < "$TEMPLATES_DIR/sync.sh" > "$OUTPUT_DIR/autodocs-sync.sh"
chmod +x "$OUTPUT_DIR/autodocs-sync.sh"
envsubst '${OUTPUT_DIR} ${REPO_DIR}' < "$TEMPLATES_DIR/structural-scan.sh" > "$OUTPUT_DIR/autodocs-structural-scan.sh"
chmod +x "$OUTPUT_DIR/autodocs-structural-scan.sh"

cat > "$OUTPUT_DIR/autodocs-now" <<EOF
#!/bin/bash
exec "$OUTPUT_DIR/autodocs-sync.sh"
EOF
chmod +x "$OUTPUT_DIR/autodocs-now"

# --- Step 12: Schedule ---

if [[ "$(uname)" == "Darwin" ]]; then
  PLIST_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$PLIST_DIR"
  envsubst '${OUTPUT_DIR} ${SCHEDULE_HOUR}' < "$TEMPLATES_DIR/com.autodocs.sync.plist" > "$PLIST_DIR/com.autodocs.sync.plist"
  envsubst '${OUTPUT_DIR} ${SCHEDULE_HOUR}' < "$TEMPLATES_DIR/com.autodocs.structural-scan.plist" > "$PLIST_DIR/com.autodocs.structural-scan.plist"
  echo "Daily sync:  launchctl load $PLIST_DIR/com.autodocs.sync.plist"
  echo "Weekly scan: launchctl load $PLIST_DIR/com.autodocs.structural-scan.plist"
else
  echo "Add to crontab (crontab -e):"
  echo "  0 $SCHEDULE_HOUR * * * $OUTPUT_DIR/autodocs-sync.sh"
  echo "  0 $SCHEDULE_HOUR * * 6 $OUTPUT_DIR/autodocs-structural-scan.sh"
fi

# --- Done ---

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
if [ -z "$SELECTED_DOC" ]; then
  echo "  1. Edit $CONFIG_FILE — add docs, team members, relevant paths"
else
  echo "  1. Review $CONFIG_FILE — verify team members and paths"
fi
echo "  2. Copy reference docs to $OUTPUT_DIR/ (for drift detection)"
echo "  3. Test: $OUTPUT_DIR/autodocs-now"
echo "  4. Activate schedule (see above)"
echo ""
echo "Docs: https://github.com/msiric/autodocs/blob/main/docs/configuration.md"
