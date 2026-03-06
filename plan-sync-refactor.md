# autodocs — sync.sh Refactoring Plan

> Date: 2026-03-06
> Status: Ready for implementation (next session)
> Current state: 518 lines, working, all 201 tests pass
> Target state: ~280 lines bash + ~200 lines new Python operations

## The Problem

sync.sh has grown from 245 to 518 lines over one session. It now does:

| Section | Lines | What | Should be |
|---------|-------|------|-----------|
| Setup, utils | 1-60 | read_config, log_metric, retry | Keep in bash |
| Lock, auth, fetch | 61-101 | Infra | Keep in bash |
| Platform config | 102-137 | Tool allowlists, Kusto | Keep in bash |
| **Feedback ops** | **139-230** | **Discovery, state check, per-PR platform calls** | **Move to Python** |
| **Correction detection** | **231-242** | **Post-merge edit scanning** | **Move to Python** |
| **Stale management** | **243-280** | **Warn/close old PRs** | **Move to Python** |
| Open PR limit | 282-298 | Count check | Keep in bash (simple) |
| Call 1 + pre-processing | 299-327 | Date, pre-fetch, match, drift pre-process | Keep bash orchestration |
| Call 2 | 328-355 | Drift LLM call | Keep in bash |
| **Call 3 + pre/post** | **356-400** | **Suggest dedup, source copy, REPLACE verify** | **Partially move to Python** |
| Shadow + Call 4 | 400-455 | Shadow verify, apply | Keep in bash |
| Status + liveness | 456-518 | Write status, timestamp | Keep in bash |

**Bold = move to Python.** ~200 lines of bash become ~200 lines of Python.

## The Root Cause

Every bash addition requires `|| true` guarding against `set -euo pipefail`. We hit this trap 5+ times during the session:
- `grep -c` returns exit 1 on no matches
- `while read` pipeline exit code under pipefail
- `&&` chains where any failed test kills the script
- `gh pr list --jq` fails on non-JSON input
- `wc -l` pipeline exit code propagation

Python doesn't have this problem. Errors are explicit. `try/except` is clear. No pipefail traps.

## The Refactoring

### New operations in drift-helper.py

#### `pre-sync` operation

Replaces lines 139-280 (feedback discovery, state check, correction detection, stale management).

```python
def pre_sync(output_dir, repo_dir, platform, platform_config):
    """Run all pre-Call-1 operations. Returns JSON result."""
    output_dir = Path(output_dir)

    # 1. Discover existing autodocs PRs
    discovered = discover_platform_prs(platform, platform_config)
    backfill_tracking(output_dir, discovered, platform)

    # 2. Check state of tracked PRs
    state_updates = check_pr_states(output_dir, platform, platform_config)
    apply_state_updates(output_dir, state_updates)

    # 3. Detect post-merge corrections
    corrections = detect_corrections(output_dir, repo_dir)

    # 4. Stale PR management
    stale_actions = check_stale_prs(output_dir, repo_dir, platform, platform_config)

    # 5. Open PR limit
    open_count = count_open_prs(output_dir)
    max_open = get_config_value(output_dir, "limits.max_open_prs", default=10)

    result = {
        "proceed": open_count < max_open,
        "skip_reason": f"open PR limit ({open_count}/{max_open})" if open_count >= max_open else None,
        "discovered_prs": len(discovered),
        "state_updates": state_updates,
        "corrections": corrections,
        "stale_actions": stale_actions,
        "open_count": open_count,
    }

    (output_dir / "pre-sync-result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return result
```

The platform CLI calls (`gh pr view`, `gh pr close`, `glab mr view`, etc.) happen inside Python via `subprocess.run()`. This is cleaner because:
- Error handling is explicit (`try/except`)
- JSON parsing is native (`json.loads`)
- No `set -e` / `pipefail` traps
- Platform dispatch is a clean `if/elif` instead of nested `case` statements

#### `pre-apply` operation

Replaces the source-context copy + REPLACE verification (currently in sync.sh lines 365-420).

```python
def pre_apply(output_dir, repo_dir):
    """Copy source files and run REPLACE verification."""
    # 1. Copy mapped source files to source-context/
    copy_mapped_sources(output_dir, repo_dir)

    # 2. Run REPLACE verification
    verify_replaces(output_dir, repo_dir)
```

This is mostly moving existing code (source copy is currently 6 lines of bash, verify_replaces already exists in drift-helper.py).

### What sync.sh becomes

```bash
#!/bin/bash
set -euo pipefail

# === Setup (unchanged) ===
# DRY_RUN, OUTPUT_DIR, REPO_DIR, SCRIPTS_DIR
# read_config, log_metric, retry functions
# Lock, auth check, git fetch
# Platform detection, tool allowlists

# === Pre-sync (one Python call replaces 160 lines of bash) ===
PRESYNC_OK=true
if [ -f "$DRIFT_HELPER" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$DRIFT_HELPER" pre-sync "$OUTPUT_DIR" "$REPO_DIR" "$PLATFORM" 2>/dev/null || true

  # Check if we should proceed
  if [ -f "$OUTPUT_DIR/pre-sync-result.json" ]; then
    PROCEED=$(python3 -c "import json;print(json.load(open('$OUTPUT_DIR/pre-sync-result.json'))['proceed'])" 2>/dev/null || echo "True")
    if [ "$PROCEED" = "False" ]; then
      SKIP_REASON=$(python3 -c "import json;print(json.load(open('$OUTPUT_DIR/pre-sync-result.json')).get('skip_reason',''))" 2>/dev/null || echo "")
      log_metric "sync" "skipped" "0"
      # Write status and exit
      ...
      exit 0
    fi
  fi
fi

# === Call 1: Sync (unchanged) ===
# Date computation, pre-fetch, LLM call

# === Deterministic pre-processing (unchanged) ===
# match-helper, drift-helper pre-process, match rate metric

# === Call 2: Drift (unchanged) ===

# === Call 3: Suggest (unchanged LLM call) ===
# suggest-dedup (already Python)

# === Pre-apply (one Python call replaces source copy + verify) ===
python3 "$DRIFT_HELPER" pre-apply "$OUTPUT_DIR" "$REPO_DIR" 2>/dev/null || true

# === Call 4: Apply (unchanged) ===

# === Status write + liveness guard (unchanged) ===
```

### Line count estimate

| Section | Current | After |
|---------|---------|-------|
| Setup + utils | 60 | 60 |
| Lock + auth + fetch | 41 | 41 |
| Platform config | 36 | 36 |
| Pre-sync (Python call) | 160 | 15 |
| Call 1 + pre-processing | 60 | 60 |
| Call 2 | 27 | 27 |
| Call 3 + pre-apply | 50 | 20 |
| Shadow + Call 4 | 55 | 55 |
| Status + liveness | 35 | 35 |
| **Total** | **518** | **~280** |

### Platform CLI in Python

The pre-sync operation needs to call platform CLIs. Pattern:

```python
def _gh(args: list[str], repo: str) -> str | None:
    """Run a gh CLI command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["gh"] + args + ["-R", repo],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

def discover_github_prs(owner: str, repo: str) -> list[dict]:
    """Discover existing autodocs PRs on GitHub."""
    output = _gh(
        ["pr", "list", "--search", "head:autodocs/ is:open",
         "--json", "number,createdAt", "--limit", "50"],
        f"{owner}/{repo}"
    )
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []
```

### Stale management in Python

Currently `stale-helper.py` is a standalone script. Move the `gh pr comment` and `gh pr close` calls into the pre-sync operation:

```python
def execute_stale_actions(actions, platform, platform_config):
    """Execute stale PR actions (warn/close) via platform CLI."""
    for action in actions:
        pr_num = action["pr_number"]
        if action["action"] == "warn":
            _gh(["pr", "comment", str(pr_num), "--body", f"**autodocs**: {action['reason']}..."],
                 platform_config["repo"])
            _gh(["pr", "edit", str(pr_num), "--add-label", "autodocs:stale"],
                 platform_config["repo"])
        elif action["action"] == "close":
            _gh(["pr", "comment", str(pr_num), "--body", f"**autodocs**: Closing — {action['reason']}"],
                 platform_config["repo"])
            _gh(["pr", "close", str(pr_num)], platform_config["repo"])
```

### Testing strategy

The pre-sync operation calls platform CLIs, which means tests need to mock `subprocess.run`. Two approaches:

**Approach A: Mock subprocess** — Use `unittest.mock.patch` on `subprocess.run` in Python tests.

**Approach B: Interface-based** — Define a `Platform` interface with `discover_prs()`, `check_pr_state()`, `close_pr()`, `comment_pr()` methods. The real implementation calls CLIs. The test implementation returns fixtures.

Approach B is cleaner for testing but adds abstraction. Approach A is simpler but tightly couples tests to implementation.

**Recommendation: Approach A for v1.** The pre-sync operation is ~200 lines. Mock `subprocess.run` at the test boundary. If platform support grows significantly, extract to Approach B later.

### Implementation steps

1. **Add `pre-sync` operation to drift-helper.py** — move discovery, state check, corrections, stale actions
2. **Add `pre-apply` operation to drift-helper.py** — move source copy + existing verify-replaces
3. **Simplify sync.sh** — replace 160 lines of bash with Python call + result check
4. **Add tests** — mock subprocess for platform CLI calls
5. **Run E2E** — validate against demo repo

### Risks

- Moving platform CLI calls to Python means Python needs `gh`, `glab`, `curl`, `az` on PATH
- The `stale-helper.py` standalone script becomes redundant (its logic moves into drift-helper)
- The refactoring touches the most sensitive part of the pipeline (the orchestration layer)
- Should NOT be done alongside feature work — do it in isolation, test thoroughly

### What NOT to change

- The 4 LLM calls and their gating logic stay in bash (must call `claude` CLI)
- `read_config`, `log_metric`, `retry` stay in bash (utility functions used by the LLM calls)
- Lock, auth, git fetch stay in bash (infrastructure)
- Status write stays in bash (final output)
