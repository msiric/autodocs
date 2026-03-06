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

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)


# ---------------------------------------------------------------------------
# FIND verification
# ---------------------------------------------------------------------------

def verify_finds(output_dir, repo_dir):
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
    config = yaml.safe_load(config_path.read_text()) or {}

    # Build doc name → repo path mapping
    doc_paths = {}
    for doc in config.get("docs") or []:
        if doc.get("repo_path"):
            doc_paths[doc["name"]] = repo_dir / doc["repo_path"]

    # Parse FIND blocks from suggestions file
    text = suggestions_path.read_text()
    results = []
    current_doc = ""
    current_find = []
    in_find = False
    confidence = ""

    for line in text.splitlines():
        doc_match = re.match(r"## (\S+\.md)\s*—", line)
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
                find_text = "\n".join(current_find)
                if find_text and current_doc:
                    doc_path = doc_paths.get(current_doc)
                    status = "SKIP"
                    reason = ""
                    if not doc_path or not doc_path.exists():
                        status = "SKIP"
                        reason = "doc not found in repo"
                    elif find_text in doc_path.read_text():
                        status = "PASS"
                    else:
                        status = "FAIL"
                        reason = "FIND text not found in doc"
                    results.append({
                        "doc": current_doc,
                        "find_text": find_text[:100],
                        "confidence": confidence,
                        "status": status,
                        "reason": reason,
                    })

    # Process any pending FIND block at end of file
    if in_find and current_find and current_doc:
        find_text = "\n".join(current_find)
        doc_path = doc_paths.get(current_doc)
        status = "SKIP"
        reason = ""
        if not doc_path or not doc_path.exists():
            reason = "doc not found in repo"
        elif find_text in doc_path.read_text():
            status = "PASS"
        else:
            status = "FAIL"
            reason = "FIND text not found in doc"
        results.append({
            "doc": current_doc,
            "find_text": find_text[:100],
            "confidence": confidence,
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
REPLACE_EXTRACTORS = [
    ("backtick_id", re.compile(r"`(\w[\w.]*)`")),
    ("single_quoted", re.compile(r"'([^']{2,})'")),
    ("double_quoted", re.compile(r'"([^"]{2,})"')),
    ("file_path", re.compile(r"(?:src|lib|app)/[\w/.-]+\.\w+")),
    ("http_method", re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b")),
    ("endpoint_path", re.compile(r"(/[a-z][\w/-]*(?:/:\w+)*)")),
    ("error_code", re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")),
]

# Common words that aren't code references
SKIP_VALUES = {
    "FIND", "REPLACE", "INSERT", "AFTER", "YES", "NO", "HIGH", "LOW",
    "CRITICAL", "REVIEW", "CONFIDENT", "GET", "POST", "PUT", "PATCH",
    "DELETE", "HEAD", "OPTIONS", "HTTP", "API", "URL", "JSON", "HTML",
    "CSS", "SQL", "EOF", "TODO", "NOTE", "YAML", "TRUE", "FALSE",
}


def find_function_containing(source_text, value):
    """Find which function body contains a value. Returns function name or None."""
    for match in re.finditer(
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", source_text
    ):
        func_name = match.group(1)
        brace_start = source_text.find("{", match.end())
        if brace_start == -1:
            continue
        depth, pos = 1, brace_start + 1
        while pos < len(source_text) and depth > 0:
            if source_text[pos] == "{":
                depth += 1
            elif source_text[pos] == "}":
                depth -= 1
            pos += 1
        if value in source_text[brace_start:pos]:
            return func_name
    return None


def strip_code_comments(text):
    """Strip JS/TS comments from source code for cleaner matching."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    return text


def verify_replaces(output_dir, repo_dir=None):
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

    # Load all source files (stripped of comments)
    source_corpus = {}
    for src_file in source_dir.iterdir():
        if src_file.is_file():
            source_corpus[src_file.name] = strip_code_comments(src_file.read_text())

    if not source_corpus:
        return True

    combined_source = "\n".join(source_corpus.values())

    # Parse suggestions and their REPLACE blocks
    text = suggestions_path.read_text()
    results = []
    current_doc = ""
    current_section = ""
    current_replace = []
    in_replace = False

    for line in text.splitlines():
        doc_match = re.match(r"## (\S+\.md)\s*—\s*(.*)", line)
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


def _extract_values(replace_text):
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


def _verify_values(values, combined_source, source_corpus, repo_dir=None):
    """Verify each value against source corpus. Returns list with status."""
    results = []
    for v in values:
        val = v["value"]
        found_in = None

        # File paths: verify by checking if the file exists in repo
        if v["type"] == "file_path" and repo_dir:
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


def _is_code_reference(value, value_type):
    """Heuristic: does this value look like a code reference vs prose?"""
    if value_type in ("backtick_id", "file_path", "error_code"):
        return True
    if value_type in ("single_quoted", "double_quoted"):
        if " " in value:
            return False
        if re.match(r"^[a-zA-Z_][\w.:/-]*$", value):
            return True
        return False
    return False


def _gate_decision(verified_values):
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

def main():
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
