#!/usr/bin/env python3
"""YAML config helper for autodocs. Handles all config read/write operations.

Usage: python3 config-helper.py <config_path> <operation> [args...]

Operations:
  list team|docs|paths          Print entries (one per line)
  add team <name> <field> <val> Add a team member
  add doc <name> [repo_path]    Add a doc entry
  add path <path>               Add a relevant path
  remove team|doc|path <name>   Remove an entry
  has team|doc|path <name>      Exit 0 if exists, 1 if not
  get <field>                   Print a top-level field value
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install: pip3 install pyyaml", file=sys.stderr)
    sys.exit(2)


def load_config(path):
    if not path.exists():
        return {}
    text = path.read_text()
    return yaml.safe_load(text) or {}


def save_config(path, config):
    path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def handle_list(config, section):
    if section == "team":
        for member in config.get("team_members") or []:
            print(member.get("name", ""))
    elif section == "docs":
        for doc in config.get("docs") or []:
            print(doc.get("name", ""))
    elif section == "paths":
        for path in config.get("relevant_paths") or []:
            print(path)


def handle_add(config, args):
    section = args[0]

    if section == "team":
        name, field, value = args[1], args[2], args[3]
        members = config.setdefault("team_members", [])
        # Idempotent: check if already exists
        if any(m.get("name") == name for m in members):
            return
        members.append({"name": name, field: value})

    elif section == "doc":
        name = args[1]
        repo_path = args[2] if len(args) > 2 else None
        docs = config.setdefault("docs", [])
        if any(d.get("name") == name for d in docs):
            return
        entry = {"name": name}
        if repo_path:
            entry["repo_path"] = repo_path
        docs.append(entry)

    elif section == "path":
        path = args[1]
        if not path.endswith("/"):
            path += "/"
        paths = config.setdefault("relevant_paths", [])
        if path not in paths:
            paths.append(path)


def handle_remove(config, args):
    section = args[0]
    name = args[1]

    if section == "team":
        members = config.get("team_members") or []
        config["team_members"] = [m for m in members if m.get("name") != name]

    elif section == "doc":
        docs = config.get("docs") or []
        config["docs"] = [d for d in docs if d.get("name") != name]

    elif section == "path":
        paths = config.get("relevant_paths") or []
        # Match with or without trailing slash
        normalized = name if name.endswith("/") else name + "/"
        config["relevant_paths"] = [p for p in paths if p != normalized and p != name]


def handle_has(config, args):
    section = args[0]
    name = args[1]

    if section == "team":
        return any(m.get("name") == name for m in (config.get("team_members") or []))
    elif section == "doc":
        return any(d.get("name") == name for d in (config.get("docs") or []))
    elif section == "path":
        paths = config.get("relevant_paths") or []
        normalized = name if name.endswith("/") else name + "/"
        return name in paths or normalized in paths
    return False


def handle_get(config, field):
    value = config.get(field)
    if value is not None:
        print(value)


def handle_verify_docs(config, repo_dir):
    """Check that all docs[].repo_path files exist in the repo. Prints missing ones."""
    repo = Path(repo_dir) if repo_dir else Path(".")
    for doc in config.get("docs") or []:
        rp = doc.get("repo_path", "")
        if rp and not (repo / rp).exists():
            print(f"{doc.get('name', '?')}:{rp}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    operation = sys.argv[2]
    args = sys.argv[3:]

    config = load_config(config_path)

    if operation == "list":
        handle_list(config, args[0] if args else "")
    elif operation == "add":
        handle_add(config, args)
        save_config(config_path, config)
    elif operation == "remove":
        handle_remove(config, args)
        save_config(config_path, config)
    elif operation == "has":
        sys.exit(0 if handle_has(config, args) else 1)
    elif operation == "get":
        handle_get(config, args[0] if args else "")
    elif operation == "verify-docs":
        handle_verify_docs(config, args[0] if args else ".")
    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
