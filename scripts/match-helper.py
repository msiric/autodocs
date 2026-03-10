#!/usr/bin/env python3
"""Deterministic file-to-section matching for autodocs.

Resolves a file path to a doc section using the package_map from config.
Replaces LLM-based matching with deterministic logic.

Usage: python3 match-helper.py <config_path> <file_path> [pr_title]

Priority order (first match wins):
  1. Exact path match (key contains '/' and file path ends with key)
  2. Glob match (key contains '*')
  3. Directory match (/<key>/ in file path)
  4. Basename match (key matches filename, only if no '/' or '*' in key)

Outputs: section name, or "UNMAPPED" if no match found.
"""

import fnmatch
import os
import sys

UNMAPPED = "UNMAPPED"
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Warning: pyyaml not installed, returning UNMAPPED for all files", file=sys.stderr)
    sys.exit(0)


def load_config(path):
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def strip_source_root(file_path, source_roots):
    """Strip the longest matching source root prefix from the file path."""
    if not source_roots:
        return file_path
    # Sort by length descending so longest prefix matches first
    for root in sorted(source_roots, key=len, reverse=True):
        root = root.rstrip("/") + "/"
        if file_path.startswith(root):
            return file_path[len(root):]
    return file_path


def get_all_package_maps(config):
    """Extract all package_map entries from all docs in config."""
    maps = {}
    for doc in config.get("docs") or []:
        for key, value in (doc.get("package_map") or {}).items():
            maps[key] = value
    return maps


def resolve_section(value, pr_title=""):
    """Resolve a package_map value to a section name.
    Handles both simple strings and complex mappings with title_hints."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Complex mapping with title_hints
        title_hints = value.get("title_hints", {})
        pr_title_lower = pr_title.lower()
        for keywords_str, section in title_hints.items():
            keywords = [k.strip() for k in keywords_str.split(",")]
            if any(kw in pr_title_lower for kw in keywords):
                return section
        return value.get("default", UNMAPPED)
    return UNMAPPED


def match_file_with_roots(original_path, stripped_path, package_map, pr_title=""):
    """Match a file path against package_map keys using 4-priority system.

    Uses original_path for exact/glob matching (priorities 1-2).
    Uses stripped_path for directory/basename matching (priorities 3-4).
    """
    if not package_map:
        return UNMAPPED

    # Separate keys by type
    exact_keys = {k: v for k, v in package_map.items() if "/" in k and "*" not in k}
    glob_keys = {k: v for k, v in package_map.items() if "*" in k}
    dir_keys = {k: v for k, v in package_map.items() if "/" not in k and "*" not in k}

    # Priority 1: Exact path match (original path ends with key)
    matches = [(k, v) for k, v in exact_keys.items() if original_path.endswith(k)]
    if matches:
        best = max(matches, key=lambda x: len(x[0]))
        return resolve_section(best[1], pr_title)

    # Priority 2: Glob match (against original path)
    matches = [(k, v) for k, v in glob_keys.items() if fnmatch.fnmatch(original_path, k)]
    if matches:
        best = max(matches, key=lambda x: len(x[0]))
        return resolve_section(best[1], pr_title)

    # Priority 3: Directory match (/<key>/ in stripped path)
    matches = [(k, v) for k, v in dir_keys.items() if f"/{k}/" in f"/{stripped_path}"]
    if matches:
        best = max(matches, key=lambda x: len(x[0]))
        return resolve_section(best[1], pr_title)

    # Priority 4: Basename match (against stripped path filename)
    basename = os.path.basename(stripped_path)
    matches = [(k, v) for k, v in dir_keys.items() if k == basename]
    if matches:
        best = max(matches, key=lambda x: len(x[0]))
        return resolve_section(best[1], pr_title)

    return UNMAPPED


def _is_safe_path(path):
    """Reject paths that could be injection attempts (traversal, absolute)."""
    return path and ".." not in path and not path.startswith("/")


def extract_files_from_report(report_path):
    """Extract file paths and change types from a daily-report.md file."""
    files = []
    for line in Path(report_path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        # Match lines like: M src/auth/handler.ts
        if line and line[0] in "MADR" and len(line) > 2 and line[1] == " ":
            change_type = line[0]
            file_path = line[2:].strip()
            if _is_safe_path(file_path):
                files.append((change_type, file_path))
        # Match renamed files: R src/old.ts → src/new.ts
        elif line.startswith("R ") and "→" in line:
            parts = line[2:].split("→")
            if len(parts) == 2:
                new_path = parts[1].strip()
                if _is_safe_path(new_path):
                    files.append(("R", new_path))
    return files


def resolve_report(config_path, report_path):
    """Resolve all files in a daily report to their doc sections."""
    config = load_config(config_path)
    source_roots = config.get("source_roots", [])
    package_map = get_all_package_maps(config)

    files = extract_files_from_report(report_path)
    for change_type, file_path in files:
        stripped = strip_source_root(file_path, source_roots)
        section = match_file_with_roots(file_path, stripped, package_map)
        print(f"{change_type} {file_path} → {section}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    config_path = Path(sys.argv[1])

    # Mode: resolve report
    if sys.argv[2] == "--resolve-report":
        report_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
        if report_path and report_path.exists():
            resolve_report(config_path, report_path)
        sys.exit(0)

    # Mode: single file match
    file_path = sys.argv[2]
    pr_title = sys.argv[3] if len(sys.argv) > 3 else ""

    config = load_config(config_path)
    source_roots = config.get("source_roots", [])
    package_map = get_all_package_maps(config)

    stripped_path = strip_source_root(file_path, source_roots)
    result = match_file_with_roots(file_path, stripped_path, package_map, pr_title)
    print(result)


if __name__ == "__main__":
    main()
