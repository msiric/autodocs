#!/bin/bash
set -euo pipefail

# autodocs setup wizard
# Auto-detects platform, owner, team, and paths where possible.
# Falls back to manual input when detection fails.
# Usage: ./setup.sh [--quick]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/templates"
HELPER="$SCRIPT_DIR/scripts/config-helper.py"

# ---------------------------------------------------------------------------
# Config management subcommands
# ---------------------------------------------------------------------------

find_config() {
  # Search for config.yaml in common locations
  for candidate in "./config.yaml" "./.autodocs/config.yaml"; do
    if [ -f "$candidate" ]; then
      echo "$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
      return 0
    fi
  done
  echo "Error: No config.yaml found. Run setup.sh first." >&2
  return 1
}

cmd_team() {
  local config_file
  config_file=$(find_config) || exit 1
  local action="${1:-list}"
  local platform
  platform=$(python3 "$HELPER" "$config_file" get platform)

  case "$action" in
    list)
      echo "Team members:"
      local members
      members=$(python3 "$HELPER" "$config_file" list team)
      if [ -n "$members" ]; then
        echo "$members" | nl
      else
        echo "  (none)"
      fi
      ;;
    add)
      read -rp "Name: " name
      read -rp "Username: " username
      local field="${platform}_username"
      [ "$platform" = "ado" ] && field="ado_id"
      if python3 "$HELPER" "$config_file" has team "$name" 2>/dev/null; then
        echo "$name is already a team member."
      else
        python3 "$HELPER" "$config_file" add team "$name" "$field" "$username"
        echo "Added: $name ($username)"
      fi
      ;;
    remove)
      echo "Team members:"
      local members
      members=$(python3 "$HELPER" "$config_file" list team)
      if [ -z "$members" ]; then
        echo "  (none)"; return
      fi
      echo "$members" | nl
      read -rp "Remove (number, or Enter to cancel): " num
      if [ -n "$num" ]; then
        local name
        name=$(echo "$members" | sed -n "${num}p")
        if [ -n "$name" ]; then
          python3 "$HELPER" "$config_file" remove team "$name"
          echo "Removed: $name"
        fi
      fi
      ;;
    discover)
      echo "Discovering contributors from recent PRs..."
      local discovered=""
      case "$platform" in
        github)
          local owner repo
          owner=$(python3 "$HELPER" "$config_file" get github | python3 -c "import sys,yaml;d=yaml.safe_load(sys.stdin);print(d.get('owner',''))" 2>/dev/null)
          repo=$(python3 "$HELPER" "$config_file" get github | python3 -c "import sys,yaml;d=yaml.safe_load(sys.stdin);print(d.get('repo',''))" 2>/dev/null)
          [ -n "$owner" ] && [ -n "$repo" ] && \
            discovered=$(gh pr list -R "$owner/$repo" --state merged --limit 50 \
              --json author --jq '[.[].author.login] | unique | .[]' 2>/dev/null)
          ;;
      esac
      if [ -n "$discovered" ]; then
        echo "Found contributors:"
        local new_members=""
        while IFS= read -r username; do
          if ! python3 "$HELPER" "$config_file" has team "$username" 2>/dev/null; then
            new_members="${new_members}${username}\n"
            echo "  NEW: $username"
          else
            echo "  (existing): $username"
          fi
        done <<< "$discovered"
        if [ -n "$new_members" ]; then
          read -rp "Add new members? [Y/n] " answer
          if [[ -z "$answer" || "$answer" =~ ^[Yy] ]]; then
            local field="${platform}_username"
            [ "$platform" = "ado" ] && field="ado_id"
            echo -e "$new_members" | while IFS= read -r username; do
              [ -n "$username" ] && python3 "$HELPER" "$config_file" add team "$username" "$field" "$username"
            done
            echo "Done."
          fi
        else
          echo "All contributors are already team members."
        fi
      else
        echo "  No contributors found (or CLI not available)."
      fi
      ;;
    *)
      echo "Usage: setup.sh team [list|add|remove|discover]"
      ;;
  esac
}

cmd_docs() {
  local config_file
  config_file=$(find_config) || exit 1
  local action="${1:-list}"

  case "$action" in
    list)
      echo "Monitored docs:"
      local docs
      docs=$(python3 "$HELPER" "$config_file" list docs)
      if [ -n "$docs" ]; then
        echo "$docs" | nl
      else
        echo "  (none)"
      fi
      ;;
    add)
      read -rp "Doc filename (e.g., architecture.md): " name
      read -rp "Repo path (e.g., docs/architecture.md, or Enter to skip): " repo_path
      if python3 "$HELPER" "$config_file" has doc "$name" 2>/dev/null; then
        echo "$name is already monitored."
      else
        if [ -n "$repo_path" ]; then
          python3 "$HELPER" "$config_file" add doc "$name" "$repo_path"
        else
          python3 "$HELPER" "$config_file" add doc "$name"
        fi
        echo "Added: $name"
      fi
      ;;
    remove)
      echo "Monitored docs:"
      local docs
      docs=$(python3 "$HELPER" "$config_file" list docs)
      if [ -z "$docs" ]; then
        echo "  (none)"; return
      fi
      echo "$docs" | nl
      read -rp "Remove (number, or Enter to cancel): " num
      if [ -n "$num" ]; then
        local name
        name=$(echo "$docs" | sed -n "${num}p")
        if [ -n "$name" ]; then
          python3 "$HELPER" "$config_file" remove doc "$name"
          echo "Removed: $name"
        fi
      fi
      ;;
    *)
      echo "Usage: setup.sh docs [list|add|remove]"
      ;;
  esac
}

cmd_paths() {
  local config_file
  config_file=$(find_config) || exit 1
  local action="${1:-list}"

  case "$action" in
    list)
      echo "Relevant paths:"
      local paths
      paths=$(python3 "$HELPER" "$config_file" list paths)
      if [ -n "$paths" ]; then
        echo "$paths" | nl
      else
        echo "  (none)"
      fi
      ;;
    add)
      read -rp "Path prefix (e.g., src/api/): " path
      if python3 "$HELPER" "$config_file" has path "$path" 2>/dev/null; then
        echo "$path is already in relevant_paths."
      else
        python3 "$HELPER" "$config_file" add path "$path"
        echo "Added: $path"
      fi
      ;;
    remove)
      echo "Relevant paths:"
      local paths
      paths=$(python3 "$HELPER" "$config_file" list paths)
      if [ -z "$paths" ]; then
        echo "  (none)"; return
      fi
      echo "$paths" | nl
      read -rp "Remove (number, or Enter to cancel): " num
      if [ -n "$num" ]; then
        local path
        path=$(echo "$paths" | sed -n "${num}p")
        if [ -n "$path" ]; then
          python3 "$HELPER" "$config_file" remove path "$path"
          echo "Removed: $path"
        fi
      fi
      ;;
    discover)
      echo "Discovering paths from doc files..."
      local docs
      docs=$(python3 "$HELPER" "$config_file" list docs)
      if [ -z "$docs" ]; then
        echo "  No docs configured. Add docs first: setup.sh docs add"
        return
      fi
      local output_dir
      output_dir=$(dirname "$config_file")
      while IFS= read -r doc; do
        local doc_path="$output_dir/$doc"
        if [ -f "$doc_path" ]; then
          echo "Paths from $doc:"
          local discovered
          discovered=$(grep -oE '[a-zA-Z][a-zA-Z0-9/_.-]+\.(ts|js|py|tsx|jsx|go|rs|java|rb|cs)' "$doc_path" \
            | sed 's|/[^/]*$||' | sort -u 2>/dev/null)
          if [ -n "$discovered" ]; then
            while IFS= read -r path; do
              if ! python3 "$HELPER" "$config_file" has path "$path" 2>/dev/null; then
                echo "  NEW: $path/"
                python3 "$HELPER" "$config_file" add path "$path"
              fi
            done <<< "$discovered"
          fi
        fi
      done <<< "$docs"
      echo "Done."
      ;;
    *)
      echo "Usage: setup.sh paths [list|add|remove|discover]"
      ;;
  esac
}

cmd_config() {
  local config_file
  config_file=$(find_config) || exit 1
  ${EDITOR:-vi} "$config_file"
}

cmd_analyze() {
  local repo_dir="${1:-.}"
  if [ ! -d "$repo_dir/.git" ]; then
    echo "Error: $repo_dir is not a git repository."
    exit 1
  fi

  echo "=== Repository Analysis ==="
  echo ""

  # Count files (exclude .git, node_modules, vendor, .venv)
  local file_count
  file_count=$(find "$repo_dir" -type f \
    -not -path '*/.git/*' -not -path '*/node_modules/*' \
    -not -path '*/vendor/*' -not -path '*/.venv/*' \
    2>/dev/null | wc -l | tr -d ' ')
  echo "Files: $file_count"

  # Classify repo size
  if [ "$file_count" -lt 50 ]; then
    echo "Repo type: SMALL (< 50 files)"
    echo "  → File-level or basename matching recommended for package_map"
  elif [ "$file_count" -lt 500 ]; then
    echo "Repo type: MEDIUM (50-500 files)"
    echo "  → Directory-level matching recommended for package_map"
  else
    echo "Repo type: LARGE (500+ files)"
    echo "  → Directory-level matching + exclude_patterns recommended"
  fi

  # Detect languages
  echo ""
  echo "Languages detected:"
  [ -f "$repo_dir/package.json" ] && echo "  - TypeScript/JavaScript (package.json)"
  [ -f "$repo_dir/go.mod" ] && echo "  - Go (go.mod)"
  ([ -f "$repo_dir/pyproject.toml" ] || [ -f "$repo_dir/setup.py" ]) && echo "  - Python"
  ([ -f "$repo_dir/pom.xml" ] || [ -f "$repo_dir/build.gradle" ]) && echo "  - Java"
  [ -f "$repo_dir/Cargo.toml" ] && echo "  - Rust (Cargo.toml)"

  # Find docs
  echo ""
  echo "Documentation found:"
  find "$repo_dir" -name "*.md" -not -path '*/.git/*' -not -path '*/node_modules/*' \
    -not -name "CHANGELOG.md" -not -name "LICENSE.md" 2>/dev/null | while read -r doc; do
    local sections lines
    sections=$(grep -c "^## " "$doc" 2>/dev/null || echo "0")
    lines=$(wc -l < "$doc" 2>/dev/null | tr -d ' ')
    local mode_hint=""
    if [ "$sections" -lt 5 ] && [ "$lines" -lt 500 ]; then
      mode_hint=" (adaptive: holistic context)"
    elif [ "$sections" -ge 5 ]; then
      mode_hint=" (adaptive: per-section)"
    else
      mode_hint=" (adaptive: section + adjacent)"
    fi
    echo "  $(basename "$doc") — $lines lines, $sections sections$mode_hint"
  done

  echo ""
  echo "Run 'setup.sh' to generate a config based on this analysis."
}

cmd_status() {
  local config_file
  config_file=$(find_config) || exit 1
  local output_dir
  output_dir=$(dirname "$config_file")

  echo "=== autodocs status ==="
  echo ""
  if [ -f "$output_dir/sync-status.md" ]; then
    cat "$output_dir/sync-status.md"
  else
    echo "No runs recorded."
  fi
  echo ""
  if [ -f "$output_dir/last-successful-run" ]; then
    echo "Last successful run: $(cat "$output_dir/last-successful-run")"
  fi
  if [ -f "$output_dir/feedback/open-prs.json" ]; then
    local open
    open=$(python3 "$HELPER" "$output_dir/feedback/open-prs.json" list-prs --open-only 2>/dev/null | wc -l | tr -d ' ')
    echo "Open autodocs PRs: $open"
  fi
  if [ -f "$output_dir/feedback/open-prs.json" ]; then
    local rate
    rate=$(python3 "$HELPER" "$output_dir/feedback/open-prs.json" acceptance-rate 2>/dev/null)
    echo "Acceptance rate: $rate"
  fi
  if [ -f "$output_dir/metrics.jsonl" ]; then
    local total
    total=$(wc -l < "$output_dir/metrics.jsonl" | tr -d ' ')
    echo "Metric entries: $total"
  fi
}

# --- Subcommand routing ---
case "${1:-}" in
  team)   shift; cmd_team "$@"; exit 0 ;;
  docs)   shift; cmd_docs "$@"; exit 0 ;;
  paths)  shift; cmd_paths "$@"; exit 0 ;;
  config) shift; cmd_config "$@"; exit 0 ;;
  analyze) shift; cmd_analyze "$@"; exit 0 ;;
  status) shift; cmd_status "$@"; exit 0 ;;
  --quick) QUICK_MODE=true ;;
  "")     ;; # no args = full setup
  -*)     ;; # other flags
  *)      echo "Usage: setup.sh [--quick] | team | docs | paths | config | analyze | status"; exit 1 ;;
esac

QUICK_MODE=${QUICK_MODE:-false}

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
envsubst '${OUTPUT_DIR}' < "$TEMPLATES_DIR/verify-variation.md" > "$OUTPUT_DIR/verify-variation.md"

echo "Rendering scripts..."
envsubst '${OUTPUT_DIR} ${REPO_DIR}' < "$TEMPLATES_DIR/sync.sh" > "$OUTPUT_DIR/autodocs-sync.sh"
chmod +x "$OUTPUT_DIR/autodocs-sync.sh"
envsubst '${OUTPUT_DIR} ${REPO_DIR}' < "$TEMPLATES_DIR/structural-scan.sh" > "$OUTPUT_DIR/autodocs-structural-scan.sh"
chmod +x "$OUTPUT_DIR/autodocs-structural-scan.sh"

echo "Copying helper scripts..."
mkdir -p "$OUTPUT_DIR/scripts"
cp "$SCRIPT_DIR/scripts/"*.py "$OUTPUT_DIR/scripts/"

cat > "$OUTPUT_DIR/autodocs-now" <<EOF
#!/bin/bash
exec "$OUTPUT_DIR/autodocs-sync.sh" "\$@"
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

# --- CI option ---

if ! $QUICK_MODE; then
  echo ""
  if confirm "Set up GitHub Actions workflow?"; then
    mkdir -p "$REPO_DIR/.github/workflows"
    cp "$TEMPLATES_DIR/autodocs-workflow.yml" "$REPO_DIR/.github/workflows/autodocs.yml"
    echo "Workflow created: $REPO_DIR/.github/workflows/autodocs.yml"
    echo "  Add ANTHROPIC_API_KEY to repository secrets."
    echo "  Commit and push to activate."
  fi
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
