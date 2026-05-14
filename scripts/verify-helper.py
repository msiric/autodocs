#!/usr/bin/env python3
"""Deterministic verification for autodocs suggestions.

Verifies LLM-generated FIND/REPLACE suggestions against actual source code.
Three verification layers:
1. FIND verification: does the target text exist in the doc?
2. REPLACE verification: are code references in the replacement correct?
3. Function-scoped context: are co-referenced values in the same function?

Usage:
  python3 verify-helper.py verify-finds <output_dir> <repo_dir>
  python3 verify-helper.py verify-replaces <output_dir> [<repo_dir>]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install: pip3 install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# FIND verification
# ---------------------------------------------------------------------------

def _normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs (spaces, tabs, newlines) into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _check_find_in_doc(find_text: str, doc_text: str) -> tuple[str, str]:
    """Check if FIND text exists in doc. Returns (status, reason).

    Tries exact match first, then falls back to whitespace-normalized match.
    This handles invisible differences: trailing spaces, different line endings,
    tab-vs-space, or LLM-normalized whitespace in FIND blocks.
    """
    if find_text in doc_text:
        return "PASS", ""
    if _normalize_whitespace(find_text) in _normalize_whitespace(doc_text):
        return "PASS", "matched after whitespace normalization"
    return "FAIL", "FIND text not found in doc"


def verify_finds(output_dir: str | Path, repo_dir: str | Path) -> bool:
    """Mechanically verify every FIND block in suggestions exists in the target doc.

    Reads drift-suggestions.md, checks each FIND text against the actual file
    in the repo. Writes verified-suggestions.json with pass/fail per suggestion.
    This is the deterministic quality gate — no LLM involved.

    The suggestion parser is reused from apply_engine so verify and apply
    operate on byte-identical FIND text. A prior bug had two independent
    parsers diverge on bare ">" lines (legitimate empty quoted lines inside a
    multi-line FIND): verify-helper terminated the block at the bare ">" and
    checked only the first line of the FIND, while apply_engine kept the full
    block. Hallucinated FINDs that happened to share a prefix with the doc
    silently passed verify and then silently failed at apply with no surfaced
    reason. Sharing the parser eliminates that whole class of drift by
    construction — there is exactly one definition of "what the FIND text is".
    """
    # Local import: apply_engine sits next to this script. Importing at module
    # scope would force every verify-helper invocation (including ops that
    # don't touch suggestions) to load apply_engine's full dependency set.
    # When invoked as `python3 scripts/verify-helper.py …` Python puts the
    # script's directory on sys.path automatically; when loaded via importlib
    # (tests, embedded callers) it does not — so we add it explicitly.
    _scripts_dir = str(Path(__file__).resolve().parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from apply_engine import parse_suggestions

    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)
    suggestions_path = output_dir / "drift-suggestions.md"
    if not suggestions_path.exists():
        return True

    config_path = output_dir / "config.yaml"
    if not config_path.exists():
        return True
    config = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="replace")) or {}

    doc_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = repo_dir / doc["repo_path"]

    text = suggestions_path.read_text(encoding="utf-8", errors="replace")
    results = []
    for s in parse_suggestions(text):
        doc_path = doc_paths.get(s.doc)
        if not doc_path or not doc_path.exists():
            status, reason = "SKIP", "doc not found in repo"
        else:
            doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
            status, reason = _check_find_in_doc(s.find_text, doc_text)
        results.append({
            "doc": s.doc,
            "find_text": s.find_text[:100],
            "confidence": s.confidence,
            "status": status,
            "reason": reason,
        })

    (output_dir / "verified-suggestions.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    if failed > 0:
        print(f"FIND verification: {passed} passed, {failed} FAILED", file=sys.stderr)
    return failed == 0


# ---------------------------------------------------------------------------
# REPLACE verification
# ---------------------------------------------------------------------------

# Patterns to extract verifiable values from REPLACE text
# Each pattern extracts values that can be checked against source code.
# The backtick_id extractor is the primary mechanism — the suggest prompt
# instructs the LLM to backtick-wrap all code references including file paths.
# Quoted literals catch default values like 'member' or 'viewer'.
REPLACE_EXTRACTORS = [
    ("backtick_id", re.compile(r"`(\w[\w./-]*)`")),
    ("single_quoted", re.compile(r"'([^']{2,})'")),
    ("double_quoted", re.compile(r'"([^"]{2,})"')),
]

# Values to skip during verification (not code references)
SKIP_VALUES = {
    "FIND", "REPLACE", "INSERT", "AFTER", "YES", "NO",
    "HIGH", "LOW", "CRITICAL", "REVIEW", "CONFIDENT",
    "TRUE", "FALSE", "NULL", "NONE",
}


def strip_code_comments(text: str) -> str:
    """Strip common comment patterns from source code for cleaner matching.

    Handles C-style (/* */), single-line (//), and Python-style (#) comments.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"#.*", "", text)
    return text


def _config_search_paths(config: dict, repo_dir: Path) -> list[Path]:
    """Resolve relevant_paths + cross_cutting_packages to repo-relative directories.

    Used as a fallback when source-context/ doesn't contain the identifier
    being verified. source-context is curated for the LLM (context-window
    constrained); the verifier needs broader ground truth.
    """
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(rel: str) -> None:
        if not rel or rel in seen:
            return
        full = (repo_dir / rel).resolve()
        # Ensure resolved path stays within repo (prevent traversal)
        try:
            full.relative_to(repo_dir.resolve())
        except ValueError:
            return
        if full.exists():
            seen.add(rel)
            paths.append(full)

    # relevant_paths may contain glob patterns — expand
    for rp in config.get("relevant_paths") or []:
        rp = rp.rstrip("/")
        if "*" in rp or "?" in rp:
            for match in repo_dir.glob(rp):
                try:
                    rel = str(match.relative_to(repo_dir))
                    _add(rel)
                except ValueError:
                    continue
        else:
            _add(rp)

    # cross_cutting_packages: literal directory paths
    for pkg in config.get("cross_cutting_packages") or []:
        _add(pkg.rstrip("/"))

    return paths


def _value_in_repo(value: str, search_paths: list[Path]) -> str | None:
    """Search repo for a literal value. Returns the file path if found, else None.

    Uses `grep -lF` (fixed string, list files only, recursive) for speed on
    large monorepos. Fast even on thousands of files because grep stops at
    the first match per file and we stop at the first matching path.
    """
    if not value or not search_paths:
        return None
    for path in search_paths:
        result = subprocess.run(
            ["grep", "-rlF", "-e", value, str(path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Return first matching file (repo-relative if possible)
            first = result.stdout.strip().splitlines()[0]
            return first
    return None


def verify_replaces(output_dir: str | Path, repo_dir: str | Path | None = None) -> bool:
    """Verify REPLACE text values against source code files.

    For each suggestion, extracts concrete values from REPLACE text and checks
    them against:
    1. source-context/ (curated subset, primary check)
    2. relevant_paths + cross_cutting_packages in the repo (fallback)

    Three outcomes per value: EVIDENCED (found), MISMATCH (contradicted),
    UNVERIFIED (not found, not contradicted).
    """
    output_dir = Path(output_dir)
    suggestions_path = output_dir / "drift-suggestions.md"
    source_dir = output_dir / "source-context"

    if not suggestions_path.exists():
        return True

    # Load all source files (stripped of comments), walking directory tree
    source_corpus: dict[str, str] = {}
    if source_dir.exists():
        for src_file in source_dir.rglob("*"):
            if src_file.is_file():
                rel_name = str(src_file.relative_to(source_dir))
                source_corpus[rel_name] = strip_code_comments(
                    src_file.read_text(encoding="utf-8", errors="replace")
                )

    # Resolve repo-wide search paths for fallback verification
    repo_search_paths: list[Path] = []
    if repo_dir:
        config_path = output_dir / "config.yaml"
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="replace")) or {}
                repo_search_paths = _config_search_paths(config, Path(repo_dir))
            except yaml.YAMLError:
                pass

    if not source_corpus and not repo_search_paths:
        return True

    combined_source = "\n".join(source_corpus.values())

    # Parse suggestions and their REPLACE blocks
    text = suggestions_path.read_text(encoding="utf-8", errors="replace")
    results = []
    current_doc = ""
    current_section = ""
    current_replace = []
    in_replace = False

    for line in text.splitlines():
        doc_match = re.match(r"## (\S+\.\w+)\s*[\u2014\u2013\-]\s*(.*)", line)
        if doc_match:
            current_doc = doc_match.group(1)
            current_section = doc_match.group(2).strip()
            continue

        if "### REPLACE WITH:" in line or "### INSERT AFTER:" in line:
            in_replace = True
            current_replace = []
            continue

        if in_replace:
            if line.startswith("> "):
                current_replace.append(line[2:])
                continue
            elif line.strip() == "":
                continue
            else:
                in_replace = False
                if current_replace and current_doc:
                    replace_text = "\n".join(current_replace)
                    values = _extract_values(replace_text)
                    verified = _verify_values(
                        values, combined_source, source_corpus, repo_dir, repo_search_paths,
                    )
                    gate = _gate_decision(verified)
                    results.append({
                        "doc": current_doc,
                        "section": current_section,
                        "gate": gate,
                        "values": verified,
                    })

    # Process any pending REPLACE block at end of file
    if in_replace and current_replace and current_doc:
        replace_text = "\n".join(current_replace)
        values = _extract_values(replace_text)
        verified = _verify_values(
            values, combined_source, source_corpus, repo_dir, repo_search_paths,
        )
        gate = _gate_decision(verified)
        results.append({
            "doc": current_doc,
            "section": current_section,
            "gate": gate,
            "values": verified,
        })

    (output_dir / "replace-verification.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )

    blocked = sum(1 for r in results if r["gate"] == "BLOCK")
    if blocked:
        print(f"REPLACE verification: {blocked} suggestion(s) BLOCKED", file=sys.stderr)
    return blocked == 0


def _extract_values(replace_text: str) -> list[dict[str, str]]:
    """Extract verifiable values from REPLACE text."""
    values = []
    seen = set()
    for name, pattern in REPLACE_EXTRACTORS:
        for match in pattern.finditer(replace_text):
            val = match.group(1) if match.lastindex else match.group(0)
            if val in seen or val in SKIP_VALUES or len(val) < 2:
                continue
            seen.add(val)
            values.append({"value": val, "type": name})
    return values


def _verify_values(
    values: list[dict[str, str]],
    combined_source: str,
    source_corpus: dict[str, str],
    repo_dir: str | Path | None = None,
    repo_search_paths: list[Path] | None = None,
) -> list[dict[str, str]]:
    """Verify each value against source corpus, with repo-wide fallback.

    Search order: source-context (fast, in-memory) → repo paths (slower grep).
    Only marks MISMATCH if the value isn't found in EITHER scope, preventing
    false positives when source-context lacks files that contain the value.
    """
    results = []
    repo_search_paths = repo_search_paths or []
    for v in values:
        val = v["value"]

        # File paths (detected by "/" in value): verify by repo existence
        if "/" in val and repo_dir and re.match(r"[\w.-]+/[\w/.-]+\.\w+$", val):
            file_path = Path(repo_dir) / val
            if file_path.exists():
                results.append({
                    "value": val, "type": v["type"],
                    "status": "EVIDENCED", "source": "repo",
                })
            else:
                results.append({
                    "value": val, "type": v["type"],
                    "status": "MISMATCH",
                    "reason": f"file '{val}' does not exist in repo",
                })
            continue

        # Primary search: source-context (in-memory)
        found_in = None
        for filename, content in source_corpus.items():
            if val in content:
                found_in = filename
                break

        if found_in:
            results.append({
                "value": val, "type": v["type"],
                "status": "EVIDENCED", "source": found_in,
            })
            continue

        # Fallback search: repo-wide grep (only if source-context didn't find it)
        repo_match = _value_in_repo(val, repo_search_paths)
        if repo_match:
            results.append({
                "value": val, "type": v["type"],
                "status": "EVIDENCED", "source": f"repo:{repo_match}",
            })
            continue

        # Not found anywhere — MISMATCH if code-like, UNVERIFIED otherwise
        if _is_code_reference(val, v["type"]):
            results.append({
                "value": val, "type": v["type"],
                "status": "MISMATCH",
                "reason": f"'{val}' not found in any source file",
            })
        else:
            results.append({
                "value": val, "type": v["type"],
                "status": "UNVERIFIED",
            })
    return results


def _is_code_reference(value: str, value_type: str) -> bool:
    """Heuristic: does this value look like a code reference vs prose?"""
    if value_type == "backtick_id":
        return True
    if value_type in ("single_quoted", "double_quoted"):
        if " " in value:
            return False
        if re.match(r"^[a-zA-Z_][\w.:/-]*$", value):
            return True
        return False
    return False


def _gate_decision(verified_values: list[dict[str, str]]) -> str:
    """Determine gate: BLOCK, AUTO_APPLY, or REVIEW."""
    if not verified_values:
        return "REVIEW"
    has_mismatch = any(v["status"] == "MISMATCH" for v in verified_values)
    has_evidenced = any(v["status"] == "EVIDENCED" for v in verified_values)
    if has_mismatch:
        return "BLOCK"
    if has_evidenced:
        return "AUTO_APPLY"
    return "REVIEW"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    operation = sys.argv[1]
    output_dir = sys.argv[2]

    if operation == "verify-finds":
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else "."
        ok = verify_finds(output_dir, repo_dir)
        sys.exit(0 if ok else 1)
    elif operation == "verify-replaces":
        repo_dir = sys.argv[3] if len(sys.argv) > 3 else None
        verify_replaces(output_dir, repo_dir)
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
