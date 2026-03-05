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
from pathlib import Path

try:
    import yaml
except ImportError:
    print("UNMAPPED")
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
        return value.get("default", "UNMAPPED")
    return "UNMAPPED"


def match_file_with_roots(original_path, stripped_path, package_map, pr_title=""):
    """Match a file path against package_map keys using 4-priority system.

    Uses original_path for exact/glob matching (priorities 1-2).
    Uses stripped_path for directory/basename matching (priorities 3-4).
    """
    if not package_map:
        return "UNMAPPED"

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

    return "UNMAPPED"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    file_path = sys.argv[2]
    pr_title = sys.argv[3] if len(sys.argv) > 3 else ""

    config = load_config(config_path)
    source_roots = config.get("source_roots", [])
    package_map = get_all_package_maps(config)

    # Strip source root prefix (used for directory/basename matching)
    stripped_path = strip_source_root(file_path, source_roots)

    # Match: try original path for exact/glob, stripped path for directory/basename
    result = match_file_with_roots(file_path, stripped_path, package_map, pr_title)
    print(result)


if __name__ == "__main__":
    main()
