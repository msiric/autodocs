#!/usr/bin/env python3
"""Config schema validation for autodocs.

Usage: python3 schema-helper.py <config_path>

Validates config.yaml structure. Prints errors to stderr and exits 1 if
invalid, exits 0 if valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install: pip3 install pyyaml", file=sys.stderr)
    sys.exit(2)

VALID_PLATFORMS = {"github", "gitlab", "bitbucket", "ado"}

PLATFORM_REQUIRED: dict[str, list[tuple[str, str]]] = {
    "github": [("github", "owner"), ("github", "repo")],
    "gitlab": [("gitlab", "project_path")],
    "bitbucket": [("bitbucket", "workspace"), ("bitbucket", "repo")],
    "ado": [("ado", "org"), ("ado", "project")],
}


def validate_config(config: dict) -> list[str]:
    """Validate config structure. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["config must be a YAML mapping"]

    # Platform (required, determines everything else)
    platform = config.get("platform")
    if not platform:
        errors.append("missing required field: platform")
    elif platform not in VALID_PLATFORMS:
        errors.append(
            f"platform must be one of {sorted(VALID_PLATFORMS)}, got '{platform}'"
        )
    else:
        for section, key in PLATFORM_REQUIRED.get(platform, []):
            block = config.get(section, {})
            if not isinstance(block, dict) or not block.get(key):
                errors.append(f"{platform} platform requires {section}.{key}")

    # Docs (optional, but must be well-formed if present)
    docs = config.get("docs")
    if docs is not None:
        if not isinstance(docs, list):
            errors.append("docs must be a list")
        else:
            for i, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    errors.append(f"docs[{i}] must be a mapping")
                    continue
                if not doc.get("name"):
                    errors.append(f"docs[{i}] missing required field: name")
                pm = doc.get("package_map")
                if pm is not None and not isinstance(pm, dict):
                    errors.append(f"docs[{i}].package_map must be a mapping")

    # Relevant paths (optional, but must be a list if present)
    rp = config.get("relevant_paths")
    if rp is not None and not isinstance(rp, list):
        errors.append("relevant_paths must be a list")

    # Auto PR (optional, but must be well-formed if present)
    auto_pr = config.get("auto_pr")
    if auto_pr is not None:
        if not isinstance(auto_pr, dict):
            errors.append("auto_pr must be a mapping")
        elif auto_pr.get("enabled") and not auto_pr.get("target_branch"):
            errors.append("auto_pr.enabled requires auto_pr.target_branch")

    return errors


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    config = yaml.safe_load(path.read_text()) or {}
    errors = validate_config(config)
    if errors:
        print(f"Config validation failed ({path}):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
