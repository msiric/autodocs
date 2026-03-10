#!/usr/bin/env bats

load helpers/test-helpers

HELPER="$BATS_TEST_DIRNAME/../scripts/drift-helper.py"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR

  # Minimal config
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
relevant_paths:
  - packages/auth/
docs:
  - name: "architecture.md"
    package_map:
      auth: "Authentication"
      errors: "Error Handling"
    ignore_packages:
      - test-utils
    known_patterns_section: "Known Error Patterns"
EOF
}

# ============================================================
# parse daily-report.md
# ============================================================

@test "pre-process extracts PRs from daily report" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
sync_status: success
pr_count: 1
feature_prs: 1
---
# Work Report — 2026-03-05

## Team PRs (last 24h)
- PR #42: "Fix auth handler" by Alice — merged
  Description: Fixed auth
  API: YES (packages/auth/)
  Files:
    M packages/auth/handler.ts
    A packages/auth/permissions.ts

## Owner Activity
- Reviewed: none
EOF

  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/auth/handler.ts → Authentication
A packages/auth/permissions.ts → Authentication
EOF

  python3 "$HELPER" pre-process "$TEST_DIR"
  [ -f "$TEST_DIR/drift-context.json" ]

  # Verify PR was parsed
  result=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['prs'][0]['number'])")
  [ "$result" = "42" ]
}

@test "pre-process extracts file change types" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #1: "Test" by Bob — merged
  API: YES (packages/auth/)
  Files:
    M src/auth/handler.ts
    D src/legacy/old.ts
EOF
  touch "$TEST_DIR/resolved-mappings.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  files=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['prs'][0]['files']))")
  [ "$files" = "2" ]
}

@test "pre-process extracts anomalies with NEW" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
No PRs merged.

### Anomalies
- NEW: TimeoutError in batch processor
- KNOWN: ConnectionReset
EOF
  touch "$TEST_DIR/resolved-mappings.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['anomalies']))")
  [ "$count" = "1" ]
}

# ============================================================
# parse drift-status.md
# ============================================================

@test "pre-process parses unchecked and checked status entries" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
No PRs merged.
EOF
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-04 | architecture.md | Authentication | PR #40 | HIGH
- [x] 2026-03-01 | architecture.md | Error Handling | PR #38 | HIGH | resolved
EOF
  touch "$TEST_DIR/resolved-mappings.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  unchecked=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['existing_status']['unchecked']))")
  checked=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['existing_status']['checked']))")
  [ "$unchecked" = "1" ]
  [ "$checked" = "1" ]
}

# ============================================================
# Alert generation from mappings
# ============================================================

@test "pre-process generates HIGH alert for mapped modified file" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #50: "Update auth" by Alice — merged
  API: YES (packages/auth/)
  Files:
    M packages/auth/handler.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/auth/handler.ts → Authentication
EOF
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  confidence=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['confidence'])")
  [ "$confidence" = "HIGH" ]
}

@test "pre-process generates CRITICAL alert for unmapped file in relevant path" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #51: "Add new module" by Alice — merged
  API: YES (packages/auth/)
  Files:
    A packages/auth/new-module/index.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
A packages/auth/new-module/index.ts → UNMAPPED
EOF
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  confidence=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['confidence'])")
  [ "$confidence" = "CRITICAL" ]
}

@test "pre-process generates LOW alert for REFACTOR PRs" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #60: "Big rename" by Bob — merged
  API: REFACTOR
  Files:
    M src/a.ts
    M src/b.ts
EOF
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  confidence=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['confidence'])")
  [ "$confidence" = "LOW" ]
}

@test "pre-process skips NO-classified PRs" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #70: "Unrelated fix" by Bob — merged
  API: NO
  Files:
    M src/unrelated.ts
EOF
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['new_alerts']))")
  [ "$count" = "0" ]
}

@test "pre-process generates anomaly alerts for NEW patterns" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
No PRs merged.

### Anomalies
- NEW: UnhandledRejection in auth flow
EOF
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['new_alerts']))")
  [ "$count" = "1" ]
  section=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['section'])")
  [ "$section" = "Known Error Patterns" ]
}

# ============================================================
# Grouping and dedup
# ============================================================

@test "pre-process groups alerts by (doc, section)" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #80: "Fix A" by Alice — merged
  API: YES (packages/auth/)
  Files:
    M packages/auth/a.ts
- PR #81: "Fix B" by Bob — merged
  API: YES (packages/auth/)
  Files:
    M packages/auth/b.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/auth/a.ts → Authentication
M packages/auth/b.ts → Authentication
EOF
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['new_alerts']))")
  [ "$count" = "1" ]
  prs=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(sorted(d['new_alerts'][0]['prs']))")
  [ "$prs" = "[80, 81]" ]
}

@test "pre-process deduplicates against existing unchecked entries" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #90: "Auth fix" by Alice — merged
  API: YES (packages/auth/)
  Files:
    M packages/auth/handler.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/auth/handler.ts → Authentication
EOF
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-04 | architecture.md | Authentication | PR #89 | HIGH
EOF

  python3 "$HELPER" pre-process "$TEST_DIR"
  # Should have 0 new alerts (deduped) and 1 dedup action
  new_count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['new_alerts']))")
  [ "$new_count" = "0" ]
  action_count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['dedup_actions']))")
  [ "$action_count" = "1" ]
}

# ============================================================
# Lifecycle management
# ============================================================

@test "pre-process auto-expires LOW entries older than 7 days" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-10
---
## Team PRs (last 24h)
No PRs merged.
EOF
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-01 | architecture.md | Utilities | PR #10 | LOW
- [ ] 2026-03-09 | architecture.md | Authentication | PR #20 | HIGH
EOF
  touch "$TEST_DIR/resolved-mappings.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  expired=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['lifecycle']['auto_expired']))")
  [ "$expired" = "1" ]
  # HIGH entry should be kept
  unchecked=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['existing_status']['unchecked']))")
  [ "$unchecked" = "1" ]
}

@test "pre-process trims checked entries older than 30 days" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-10
---
## Team PRs (last 24h)
No PRs merged.
EOF
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [x] 2026-01-01 | architecture.md | Old Section | PR #1 | HIGH | resolved
- [x] 2026-03-05 | architecture.md | Recent | PR #15 | HIGH | resolved
EOF
  touch "$TEST_DIR/resolved-mappings.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  trimmed=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['lifecycle']['trimmed']))")
  [ "$trimmed" = "1" ]
  kept=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['existing_status']['checked']))")
  [ "$kept" = "1" ]
}

# ============================================================
# Doc section parsing with breadcrumbs
# ============================================================

@test "pre-process disambiguates duplicate section names" {
  cat > "$TEST_DIR/architecture.md" <<EOF
# Architecture

## Authentication
Content here.

### Examples
Auth examples.

## Error Handling
Content here.

### Examples
Error examples.
EOF
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
No PRs merged.
EOF
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  sections=$(python3 -c "
import json
d = json.load(open('$TEST_DIR/drift-context.json'))
secs = d['doc_sections']['architecture.md']
disamb = [s['disambiguated'] for s in secs if s['name'] == 'Examples']
print(sorted(disamb))
")
  echo "$sections"
  echo "$sections" | grep -q "Authentication > Examples"
  echo "$sections" | grep -q "Error Handling > Examples"
}

# ============================================================
# suggest-dedup
# ============================================================

@test "suggest-dedup filters alerts with existing changelog entries" {
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-05 | architecture.md | Authentication | PR #42 | HIGH
- [ ] 2026-03-05 | architecture.md | Error Handling | PR #43 | HIGH
EOF
  cat > "$TEST_DIR/changelog-architecture.md" <<EOF
# architecture.md — Changelog

## Authentication

### 2026-03-05 — PR #42 by Alice
**Changed:** Updated auth handler
**Why:** Bug fix
EOF

  python3 "$HELPER" suggest-dedup "$TEST_DIR"
  [ -f "$TEST_DIR/suggest-context.json" ]
  actionable=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['actionable_alerts']))")
  [ "$actionable" = "1" ]
  skipped=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['skipped']))")
  [ "$skipped" = "1" ]
}

@test "suggest-dedup keeps alert when new PR has no changelog entry" {
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-05 | architecture.md | Authentication | PR #42, PR #50 | HIGH
EOF
  cat > "$TEST_DIR/changelog-architecture.md" <<EOF
# architecture.md — Changelog

## Authentication

### 2026-03-04 — PR #42 by Alice
**Changed:** Updated auth handler
**Why:** Bug fix
EOF

  python3 "$HELPER" suggest-dedup "$TEST_DIR"
  # PR #50 has no changelog entry, so the alert should be actionable
  actionable=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['actionable_alerts']))")
  [ "$actionable" = "1" ]
}

@test "suggest-dedup filters alerts with pending open PRs" {
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-05 | architecture.md | Authentication | PR #50 | HIGH
- [ ] 2026-03-05 | architecture.md | Error Handling | PR #51 | HIGH
EOF
  mkdir -p "$TEST_DIR/feedback"
  cat > "$TEST_DIR/feedback/open-prs.json" <<EOF
[
  {
    "pr_number": 99,
    "state": "open",
    "suggestions": [
      {"doc": "architecture.md", "section": "Authentication", "type": "REPLACE"}
    ]
  }
]
EOF

  python3 "$HELPER" suggest-dedup "$TEST_DIR"
  actionable=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['actionable_alerts']))")
  [ "$actionable" = "1" ]
  # The pending one should be skipped
  skipped_reason=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(d['skipped'][0]['reason'])")
  echo "$skipped_reason" | grep -q "open autodocs PR"
}

@test "suggest-dedup skips LOW confidence alerts" {
  cat > "$TEST_DIR/drift-status.md" <<EOF
# Active Drift Alerts

- [ ] 2026-03-05 | architecture.md | Authentication | PR #50 | LOW
EOF

  python3 "$HELPER" suggest-dedup "$TEST_DIR"
  actionable=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['actionable_alerts']))")
  [ "$actionable" = "0" ]
}

# ============================================================
# Multi-doc section_to_doc mapping
# ============================================================

@test "pre-process maps section to correct doc in multi-doc config" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
relevant_paths:
  - packages/
docs:
  - name: "auth-guide.md"
    package_map:
      auth: "Authentication"
  - name: "api-guide.md"
    package_map:
      api: "API Endpoints"
EOF
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #100: "Fix API" by Alice — merged
  API: YES (packages/api/)
  Files:
    M packages/api/handler.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/api/handler.ts → API Endpoints
EOF
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  doc=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['doc'])")
  [ "$doc" = "api-guide.md" ]
}

@test "pre-process maps title_hints section to correct doc" {
  cat > "$TEST_DIR/config.yaml" <<EOF
platform: github
relevant_paths: []
docs:
  - name: "guide.md"
    package_map:
      shared:
        default: "Shared Utils"
        title_hints:
          "error,fault": "Error Handling"
EOF
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
- PR #101: "Fix errors" by Bob — merged
  API: YES (packages/shared/)
  Files:
    M packages/shared/errors.ts
EOF
  cat > "$TEST_DIR/resolved-mappings.md" <<EOF
M packages/shared/errors.ts → Error Handling
EOF
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  doc=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(d['new_alerts'][0]['doc'])")
  [ "$doc" = "guide.md" ]
}

# ============================================================
# Edge cases
# ============================================================

@test "pre-process handles missing daily-report.md" {
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  [ -f "$TEST_DIR/drift-context.json" ]
  count=$(python3 -c "import json;d=json.load(open('$TEST_DIR/drift-context.json'));print(len(d['prs']))")
  [ "$count" = "0" ]
}

@test "pre-process handles missing config.yaml gracefully" {
  rm "$TEST_DIR/config.yaml"

  python3 "$HELPER" pre-process "$TEST_DIR"
  # Should not create output (no config = nothing to do)
  [ ! -f "$TEST_DIR/drift-context.json" ]
}

@test "pre-process handles empty drift-status.md" {
  cat > "$TEST_DIR/daily-report.md" <<EOF
---
date: 2026-03-05
---
## Team PRs (last 24h)
No PRs merged.
EOF
  touch "$TEST_DIR/resolved-mappings.md"
  touch "$TEST_DIR/drift-status.md"

  python3 "$HELPER" pre-process "$TEST_DIR"
  [ -f "$TEST_DIR/drift-context.json" ]
}

@test "suggest-dedup handles missing drift-status.md" {
  python3 "$HELPER" suggest-dedup "$TEST_DIR"
  [ -f "$TEST_DIR/suggest-context.json" ]
  actionable=$(python3 -c "import json;d=json.load(open('$TEST_DIR/suggest-context.json'));print(len(d['actionable_alerts']))")
  [ "$actionable" = "0" ]
}

# ============================================================
# Changelog merger
# ============================================================

@test "merge-changelogs inserts new entry at top of existing section" {
  cat > "$TEST_DIR/changelog-guide.md.bak" <<EOF
# guide.md — Changelog

## Authentication

### 2026-03-07 — PR #9 by alice
**Changed:** Old entry.
**Why:** Old reason.

---
EOF
  cat > "$TEST_DIR/changelog-guide.md" <<EOF
# guide.md — Changelog

## Authentication

### 2026-03-09 — PR #16 by bob
**Changed:** New entry.
**Why:** New reason.

### 2026-03-07 — PR #9 by alice
**Changed:** Old entry.
**Why:** Old reason.

---
EOF

  python3 "$HELPER" merge-changelogs "$TEST_DIR"
  result=$(cat "$TEST_DIR/changelog-guide.md")
  # New entry should be at top
  echo "$result" | grep -q "PR #16"
  # Old entry should still exist
  echo "$result" | grep -q "PR #9"
  # Backup should be cleaned up
  [ ! -f "$TEST_DIR/changelog-guide.md.bak" ]
}

@test "merge-changelogs does not duplicate existing entries" {
  cat > "$TEST_DIR/changelog-guide.md.bak" <<EOF
# guide.md — Changelog

## Auth

### 2026-03-07 — PR #9 by alice
**Changed:** Existing.
**Why:** Reason.

---
EOF
  # LLM wrote same entry (same PR number in same section)
  cat > "$TEST_DIR/changelog-guide.md" <<EOF
# guide.md — Changelog

## Auth

### 2026-03-07 — PR #9 by alice
**Changed:** Reworded version.
**Why:** Different reason.

---
EOF

  python3 "$HELPER" merge-changelogs "$TEST_DIR"
  # Should keep original text, not LLM's reworded version
  result=$(cat "$TEST_DIR/changelog-guide.md")
  echo "$result" | grep -q "Existing"
  ! echo "$result" | grep -q "Reworded"
}

@test "merge-changelogs adds new section from LLM" {
  cat > "$TEST_DIR/changelog-guide.md.bak" <<EOF
# guide.md — Changelog

## Auth

### 2026-03-07 — PR #9 by alice
**Changed:** Auth change.
**Why:** Reason.

---
EOF
  cat > "$TEST_DIR/changelog-guide.md" <<EOF
# guide.md — Changelog

## Auth

### 2026-03-07 — PR #9 by alice
**Changed:** Auth change.
**Why:** Reason.

---

## Error Handling

### 2026-03-09 — PR #16 by bob
**Changed:** New error type.
**Why:** Needed.

---
EOF

  python3 "$HELPER" merge-changelogs "$TEST_DIR"
  result=$(cat "$TEST_DIR/changelog-guide.md")
  echo "$result" | grep -q "Error Handling"
  echo "$result" | grep -q "PR #16"
  # Original section preserved
  echo "$result" | grep -q "Auth"
}

@test "merge-changelogs skips when no backup exists" {
  cat > "$TEST_DIR/changelog-guide.md" <<EOF
# guide.md — Changelog

## Auth

### 2026-03-09 — PR #16 by bob
**Changed:** Entry.
**Why:** Reason.
EOF
  # No .bak file — should leave file unchanged
  python3 "$HELPER" merge-changelogs "$TEST_DIR"
  grep -q "PR #16" "$TEST_DIR/changelog-guide.md"
}

# ============================================================
# REPLACE value verification
# ============================================================

@test "verify-replaces marks EVIDENCED when value found in source" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function createUser() { role: data.role ?? "member" }' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> Default role is \`member\`
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  [ -f "$TEST_DIR/replace-verification.json" ]
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  [ "$gate" = "AUTO_APPLY" ]
}

@test "verify-replaces marks MISMATCH when code reference not in source" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function createUser() { role: data.role ?? "member" }' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> Default role is \`viewer\`
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  [ "$gate" = "BLOCK" ]
}

@test "verify-replaces treats quoted prose as UNVERIFIED not MISMATCH" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function createUser() {}' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> The endpoint 'returns a paginated list' of users
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  # Prose quotes are UNVERIFIED (not MISMATCH), no code refs → REVIEW
  [ "$gate" = "REVIEW" ]
}

@test "verify-replaces treats quoted code-like values as MISMATCH" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function createUser() { role: "member" }' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> Default role is 'viewer'
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  [ "$gate" = "BLOCK" ]
}

@test "verify-replaces returns REVIEW when no values extractable" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function foo() {}' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> The API has been updated with new features.
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  [ "$gate" = "REVIEW" ]
}

@test "verify-replaces handles missing source-context gracefully" {
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints

### REPLACE WITH:
> Some content
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  # No source-context → no verification file written (graceful skip)
  [ ! -f "$TEST_DIR/replace-verification.json" ]
}

@test "verify-replaces handles empty suggestions" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'code' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
---
date: 2026-03-05
suggestion_count: 0
---
No suggestions.
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  [ -f "$TEST_DIR/replace-verification.json" ]
}

@test "verify-replaces mixed values produce correct gate" {
  mkdir -p "$TEST_DIR/source-context"
  echo 'export function listUsers() { return PaginatedResponse }' > "$TEST_DIR/source-context/users.ts"
  cat > "$TEST_DIR/drift-suggestions.md" <<EOF
## architecture.md — API Endpoints
**Confidence:** CONFIDENT

### REPLACE WITH:
> \`listUsers\` returns \`PaginatedResponse\` with \`nonExistentType\`
EOF

  python3 "$HELPER" verify-replaces "$TEST_DIR"
  gate=$(python3 -c "import json;d=json.load(open('$TEST_DIR/replace-verification.json'));print(d[0]['gate'])")
  # nonExistentType is a backtick_id not in source → MISMATCH → BLOCK
  [ "$gate" = "BLOCK" ]
}
