#!/usr/bin/env python3
"""Generate initial architecture doc and config from a codebase.

Reads source files, calls the LLM to generate a structured doc, then
derives the config (including package_map) from the generated sections.

Usage:
  python3 generate.py <repo_dir> <output_dir> [--doc-path PATH] [--relevant-dirs DIR,DIR,...]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install: pip3 install pyyaml", file=sys.stderr)
    sys.exit(2)

from llm_runner import LLMRunner, create_runner

# File extensions to include per language
SOURCE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx",  # TypeScript/JavaScript
    ".py",                          # Python
    ".go",                          # Go
    ".rs",                          # Rust
    ".java",                        # Java
    ".rb",                          # Ruby
    ".cs",                          # C#
    ".cpp", ".cc", ".c", ".h",     # C/C++
    ".swift",                       # Swift
    ".kt",                          # Kotlin
}

# Directories to always skip
SKIP_DIRS = {
    ".git", "node_modules", "vendor", ".venv", "__pycache__",
    "dist", "build", ".next", "out", "target", "bin", "obj",
    ".autodocs", ".github",
}

# Files to always skip
SKIP_PATTERNS = {
    ".test.", ".spec.", ".mock.", ".fixture.",
    ".generated.", ".min.", ".d.ts", ".map",
}



# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_source_files(
    repo_dir: Path,
    relevant_dirs: list[str] | None = None,
) -> list[dict]:
    """Find source files in the repo. Returns [{path, lines}] sorted by path."""
    files: list[dict] = []

    for root, dirs, filenames in os.walk(repo_dir):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        rel_root = Path(root).relative_to(repo_dir)

        # If relevant_dirs specified, only include files under those dirs
        if relevant_dirs:
            if not any(str(rel_root).startswith(d) or str(rel_root) == "." for d in relevant_dirs):
                continue

        for filename in sorted(filenames):
            path = Path(root) / filename
            rel_path = str(path.relative_to(repo_dir))

            # Check extension
            if path.suffix not in SOURCE_EXTENSIONS:
                continue

            # Skip test/generated files
            if any(p in filename for p in SKIP_PATTERNS):
                continue

            try:
                lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue

            files.append({"path": rel_path, "lines": lines})

    return files


def build_file_tree(files: list[dict]) -> str:
    """Build a file tree string for the prompt. The LLM reads files on demand."""
    lines = ["### Source files\n"]

    # Group by top-level directory for readability
    by_dir: dict[str, list[dict]] = {}
    for f in files:
        parts = f["path"].split("/")
        top = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        by_dir.setdefault(top, []).append(f)

    for dir_name in sorted(by_dir):
        dir_files = by_dir[dir_name]
        total_lines = sum(f["lines"] for f in dir_files)
        lines.append(f"\n**{dir_name}/** ({len(dir_files)} files, {total_lines} lines)")
        for f in sorted(dir_files, key=lambda x: x["path"]):
            lines.append(f"  {f['path']} ({f['lines']} lines)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Doc parsing and config generation
# ---------------------------------------------------------------------------

def extract_sections(doc_text: str) -> list[dict]:
    """Extract ## section headers from generated doc."""
    sections: list[dict] = []
    for line in doc_text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            name = line[3:].strip()
            # Strip numbering prefix like "1. " or "1 "
            name = re.sub(r"^\d+\.?\s+", "", name)
            if name.lower() not in ("table of contents",):
                sections.append({"name": name})
    return sections


def infer_package_map(
    sections: list[dict],
    source_dirs: list[str],
    doc_text: str,
) -> dict[str, str]:
    """Map source directories to doc sections by reference frequency."""
    package_map: dict[str, str] = {}

    for src_dir in source_dirs:
        best_section = ""
        best_count = 0
        dir_pattern = src_dir.rstrip("/")

        for section in sections:
            if section["name"] == "File Index":
                continue  # File Index references everything, skip it

            # Count references to this directory within the section's content
            section_header = f"## {section['name']}"
            # Find section content (from header to next ## header)
            pattern = re.escape(section_header) + r"\n(.*?)(?=\n## |\Z)"
            match = re.search(pattern, doc_text, re.DOTALL)
            if not match:
                continue

            section_text = match.group(1)
            count = section_text.count(dir_pattern)
            if count > best_count:
                best_count = count
                best_section = section["name"]

        if best_section:
            package_map[os.path.basename(dir_pattern)] = best_section

    return package_map


def detect_source_dirs(files: list[dict]) -> list[str]:
    """Extract unique top-level source directories from file paths."""
    dirs: set[str] = set()
    for f in files:
        parts = f["path"].split("/")
        if len(parts) >= 2:
            # Use first two levels: src/api, src/auth, lib/utils, etc.
            dirs.add("/".join(parts[:2]))
    return sorted(dirs)


def detect_relevant_paths(source_dirs: list[str]) -> list[str]:
    """Convert source directories to relevant_paths format (with trailing /)."""
    return [d + "/" for d in source_dirs]


def build_config(
    repo_dir: Path,
    doc_path: str,
    doc_name: str,
    package_map: dict[str, str],
    relevant_paths: list[str],
    feature_name: str,
) -> str:
    """Generate config.yaml content."""
    # Detect platform and owner from git
    platform, owner, repo = _detect_git_info(repo_dir)

    config: dict = {
        "platform": platform,
        "feature_name": feature_name,
    }

    # Platform connection
    if platform == "github":
        config["github"] = {"owner": owner, "repo": repo}
    elif platform == "gitlab":
        config["gitlab"] = {"host": "gitlab.com", "project_path": f"{owner}/{repo}"}
    elif platform == "bitbucket":
        config["bitbucket"] = {"workspace": owner, "repo": repo}
    elif platform == "ado":
        config["ado"] = {"org": owner, "project": repo, "repo": repo}

    # Owner
    git_name = _git_config("user.name", repo_dir) or "Your Name"
    git_email = _git_config("user.email", repo_dir) or "you@example.com"
    owner_config: dict = {"name": git_name, "email": git_email}
    if platform == "github":
        username = _detect_github_username()
        if username:
            owner_config["github_username"] = username
    config["owner"] = owner_config

    config["team_members"] = []
    config["relevant_paths"] = relevant_paths
    config["relevant_pattern"] = ""

    config["docs"] = [{
        "name": doc_name,
        "repo_path": doc_path,
        "package_map": package_map,
    }]

    config["last_verified"] = __import__("datetime").date.today().isoformat()

    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def _detect_git_info(repo_dir: Path) -> tuple[str, str, str]:
    """Detect platform, owner, repo from git remote."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=str(repo_dir),
    )
    if result.returncode != 0:
        return "github", "owner", "repo"

    remote = result.stdout.strip()

    # Detect platform
    platform = "github"
    if "gitlab.com" in remote or "gitlab." in remote:
        platform = "gitlab"
    elif "bitbucket.org" in remote:
        platform = "bitbucket"
    elif "dev.azure.com" in remote or "visualstudio.com" in remote:
        platform = "ado"

    # Extract owner/repo
    path = re.sub(r"^[^:]+://[^/]+/", "", remote)
    path = re.sub(r"^[^:]+:", "", path)
    path = re.sub(r"\.git$", "", path)
    parts = path.split("/")

    owner = parts[0] if len(parts) >= 1 else "owner"
    repo = parts[-1] if len(parts) >= 2 else parts[0] if parts else "repo"

    return platform, owner, repo


def _git_config(key: str, repo_dir: Path) -> str:
    result = subprocess.run(
        ["git", "config", key], capture_output=True, text=True, cwd=str(repo_dir),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _detect_github_username() -> str:
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate architecture doc from codebase")
    parser.add_argument("repo_dir", help="Path to the git repository")
    parser.add_argument("output_dir", help="Output directory for autodocs files")
    parser.add_argument("--doc-path", default="docs/architecture.md",
                        help="Path in repo for the generated doc (default: docs/architecture.md)")
    parser.add_argument("--relevant-dirs", help="Comma-separated directories to scope (e.g., src/api,src/auth)")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    relevant_dirs = args.relevant_dirs.split(",") if args.relevant_dirs else None
    repo_name = repo_dir.name

    print(f"Scanning {repo_dir}...")

    # 1. Discover source files
    files = discover_source_files(repo_dir, relevant_dirs)
    if not files:
        print("No source files found.", file=sys.stderr)
        sys.exit(1)

    total_lines = sum(f["lines"] for f in files)
    print(f"Found {len(files)} source files ({total_lines} lines)")

    # 2. Build file tree (LLM reads files on demand via Read tools)
    file_tree = build_file_tree(files)

    # 3. Build prompt
    prompt_template = Path(__file__).parent.parent / "templates" / "generate-prompt.md"
    if not prompt_template.exists():
        prompt_template = Path(__file__).parent / "generate-prompt.md"

    prompt_text = prompt_template.read_text()
    prompt_text = prompt_text.replace("${OUTPUT_DIR}", str(output_dir))
    prompt_text = prompt_text.replace("${REPO_DIR}", str(repo_dir))
    prompt_text = prompt_text.replace("${FILE_TREE}", file_tree)
    prompt_text = prompt_text.replace("<Project Name>", repo_name.replace("-", " ").title())

    # 4. Create runner (minimal config — just need the LLM)
    llm_config: dict = {}
    config_path = output_dir / "config.yaml"
    if config_path.exists():
        llm_config = yaml.safe_load(config_path.read_text()) or {}
    runner = create_runner(llm_config)

    # Auth check
    if not runner.check_auth(str(repo_dir)):
        print("Error: LLM authentication failed.", file=sys.stderr)
        print("  CLI: run 'claude' to authenticate", file=sys.stderr)
        print("  API: set ANTHROPIC_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    print("Generating architecture doc...")

    # 5. Call LLM
    rc, output = runner.run(
        prompt=prompt_text,
        allowed_tools="Read,Write",
        add_dirs=[str(output_dir), str(repo_dir)],
        working_dir=str(repo_dir),
    )

    if rc != 0:
        print(f"Error: LLM call failed (exit {rc})", file=sys.stderr)
        print(output[:500], file=sys.stderr)
        sys.exit(1)

    # 6. Read the generated doc
    generated_path = output_dir / "generated-doc.md"
    if not generated_path.exists():
        print("Error: LLM did not write generated-doc.md", file=sys.stderr)
        sys.exit(1)

    doc_text = generated_path.read_text()
    doc_name = os.path.basename(args.doc_path)

    # 7. Copy doc to output dir with final name + to repo
    final_output = output_dir / doc_name
    final_output.write_text(doc_text)
    generated_path.unlink()  # Clean up intermediate file

    repo_doc = repo_dir / args.doc_path
    repo_doc.parent.mkdir(parents=True, exist_ok=True)
    repo_doc.write_text(doc_text)

    print(f"Doc written to: {repo_doc}")
    print(f"Doc copied to:  {final_output}")

    # 8. Extract sections and build package_map
    sections = extract_sections(doc_text)
    source_dirs = detect_source_dirs(files)
    relevant_paths = detect_relevant_paths(source_dirs)
    package_map = infer_package_map(sections, source_dirs, doc_text)

    feature_name = repo_name.replace("-", " ").title()

    print(f"\nDetected {len(sections)} sections:")
    for s in sections:
        mapping = next((f"{k} →" for k, v in package_map.items() if v == s["name"]), "  (no mapping)")
        print(f"  ## {s['name']}  {mapping}")

    # 9. Generate config
    config_text = build_config(
        repo_dir, args.doc_path, doc_name, package_map, relevant_paths, feature_name,
    )

    if config_path.exists():
        print(f"\nConfig already exists at {config_path} — not overwriting.")
        print("Generated config saved to: config.generated.yaml")
        (output_dir / "config.generated.yaml").write_text(config_text)
    else:
        config_path.write_text(config_text)
        print(f"\nConfig written to: {config_path}")

    print("\nDone. Review the generated doc, then run 'autodocs-now' to start maintenance.")


if __name__ == "__main__":
    main()
