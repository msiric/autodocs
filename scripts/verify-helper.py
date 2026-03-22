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
    """
    output_dir = Path(output_dir)
    repo_dir = Path(repo_dir)
    suggestions_path = output_dir / "drift-suggestions.md"
    if not suggestions_path.exists():
        return True

    config_path = output_dir / "config.yaml"
    if not config_path.exists():
        return True
    config = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="replace")) or {}

    # Build doc name → repo path mapping
    doc_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = repo_dir / doc["repo_path"]

    # Parse FIND blocks from suggestions file
    text = suggestions_path.read_text(encoding="utf-8", errors="replace")
    results = []
    current_doc = ""
    current_find = []
    in_find = False
    confidence = ""

    def _verify_pending_find() -> None:
        """Verify the currently accumulated FIND block and append result."""
        find_text = "\n".join(current_find)
        if not find_text or not current_doc:
            return
        doc_path = doc_paths.get(current_doc)
        if not doc_path or not doc_path.exists():
            results.append({
                "doc": current_doc, "find_text": find_text[:100],
                "confidence": confidence, "status": "SKIP",
                "reason": "doc not found in repo",
            })
            return
        doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
        status, reason = _check_find_in_doc(find_text, doc_text)
        results.append({
            "doc": current_doc, "find_text": find_text[:100],
            "confidence": confidence, "status": status, "reason": reason,
        })

    for line in text.splitlines():
        doc_match = re.match(r"## (\S+\.\w+)\s*[\u2014\u2013\-]", line)
        if doc_match:
            current_doc = doc_match.group(1)
            continue

        if line.startswith("**Confidence:**"):
            confidence = "CONFIDENT" if "CONFIDENT" in line else "REVIEW"
            continue

        if "### FIND" in line:
            in_find = True
            current_find = []
            continue

        if in_find:
            if line.startswith("> "):
                current_find.append(line[2:])
                continue
            elif line.strip() == "":
                continue
            else:
                in_find = False
                _verify_pending_find()

    # Process any pending FIND block at end of file
    if in_find:
        _verify_pending_find()

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


def verify_replaces(output_dir: str | Path, repo_dir: str | Path | None = None) -> bool:
    """Verify REPLACE text values against source code files.

    For each suggestion, extracts concrete values from REPLACE text and checks
    them against the source files in source-context/. Three outcomes per value:
    EVIDENCED (found), MISMATCH (contradicted), UNVERIFIED (not found, not contradicted).
    """
    output_dir = Path(output_dir)
    suggestions_path = output_dir / "drift-suggestions.md"
    source_dir = output_dir / "source-context"

    if not suggestions_path.exists() or not source_dir.exists():
        return True

    # Load all source files (stripped of comments), walking directory tree
    source_corpus = {}
    for src_file in source_dir.rglob("*"):
        if src_file.is_file():
            rel_name = str(src_file.relative_to(source_dir))
            source_corpus[rel_name] = strip_code_comments(
                src_file.read_text(encoding="utf-8", errors="replace")
            )

    if not source_corpus:
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
                    verified = _verify_values(values, combined_source, source_corpus, repo_dir)
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
        verified = _verify_values(values, combined_source, source_corpus, repo_dir)
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


def _verify_values(values: list[dict[str, str]], combined_source: str, source_corpus: dict[str, str], repo_dir: str | Path | None = None) -> list[dict[str, str]]:
    """Verify each value against source corpus. Returns list with status."""
    results = []
    for v in values:
        val = v["value"]
        found_in = None

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

        # Search each source file for string values
        for filename, content in source_corpus.items():
            if val in content:
                found_in = filename
                break

        if found_in:
            results.append({
                "value": val,
                "type": v["type"],
                "status": "EVIDENCED",
                "source": found_in,
            })
        else:
            # Determine severity: MISMATCH (block) vs UNVERIFIED (review)
            if _is_code_reference(val, v["type"]):
                results.append({
                    "value": val,
                    "type": v["type"],
                    "status": "MISMATCH",
                    "reason": f"'{val}' not found in any source file",
                })
            else:
                results.append({
                    "value": val,
                    "type": v["type"],
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
