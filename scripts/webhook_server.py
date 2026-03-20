#!/usr/bin/env python3
"""FastAPI webhook receiver for autodocs.

Receives PR merge webhooks from GitHub/GitLab/Bitbucket, writes fetched-prs.json,
and triggers the orchestrator pipeline.

Usage:
  uvicorn webhook_server:app --host 0.0.0.0 --port 8080
  # Or: python3 webhook_server.py [--port 8080]

Environment variables:
  OUTPUT_DIR            — autodocs output directory (required)
  REPO_DIR              — git repository path (required)
  AUTODOCS_WEBHOOK_SECRET — HMAC secret for signature verification (recommended)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
    app = FastAPI(title="autodocs webhook")
except ImportError:
    # fastapi not installed — signature/normalization functions still usable,
    # but the server endpoints and app object are not available.
    app = None  # type: ignore
    BackgroundTasks = None  # type: ignore
    Request = None  # type: ignore

    def HTTPException(status_code: int, detail: str = "") -> Exception:  # type: ignore
        return Exception(f"HTTP {status_code}: {detail}")


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub X-Hub-Signature-256 HMAC."""
    if not secret or not signature:
        return not secret  # No secret configured = skip verification
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_gitlab_token(token: str, secret: str) -> bool:
    """Verify GitLab X-Gitlab-Token header."""
    if not secret:
        return True
    return hmac.compare_digest(token, secret)


# ---------------------------------------------------------------------------
# Payload normalization (into fetched-prs.json format)
# ---------------------------------------------------------------------------

def normalize_github_pr(payload: dict) -> dict | None:
    """Extract PR data from GitHub webhook. Returns None if not a merge event."""
    if payload.get("action") != "closed":
        return None
    pr = payload.get("pull_request", {})
    if not pr.get("merged"):
        return None
    body = pr.get("body") or ""
    return {
        "number": pr.get("number", 0),
        "title": pr.get("title", ""),
        "body": body[:500],
        "mergedAt": pr.get("merged_at", ""),
        "mergeCommit": {"oid": pr.get("merge_commit_sha", "")},
        "files": [],  # Will be populated by git diff-tree during sync
        "author": {"login": pr.get("user", {}).get("login", "")},
        "reviews": [],
    }


def normalize_gitlab_mr(payload: dict) -> dict | None:
    """Extract MR data from GitLab webhook. Returns None if not a merge event."""
    attrs = payload.get("object_attributes", {})
    if attrs.get("action") != "merge":
        return None
    desc = attrs.get("description") or ""
    return {
        "number": attrs.get("iid", 0),
        "title": attrs.get("title", ""),
        "body": desc[:500],
        "mergedAt": attrs.get("merged_at", attrs.get("updated_at", "")),
        "mergeCommit": {"oid": attrs.get("merge_commit_sha", "")},
        "files": [],
        "author": {"login": attrs.get("author_id", "")},
        "reviews": [],
    }


def normalize_bitbucket_pr(payload: dict) -> dict | None:
    """Extract PR data from Bitbucket webhook. Returns None if not a merge event."""
    pr = payload.get("pullrequest", {})
    if pr.get("state") != "MERGED":
        return None
    desc = pr.get("description") or ""
    return {
        "number": pr.get("id", 0),
        "title": pr.get("title", ""),
        "body": desc[:500],
        "mergedAt": pr.get("updated_on", ""),
        "mergeCommit": {"oid": (pr.get("merge_commit") or {}).get("hash", "")},
        "files": [],
        "author": {"login": pr.get("author", {}).get("nickname", "")},
        "reviews": [],
    }


NORMALIZERS = {
    "github": normalize_github_pr,
    "gitlab": normalize_gitlab_mr,
    "bitbucket": normalize_bitbucket_pr,
}


# ---------------------------------------------------------------------------
# Pipeline trigger
# ---------------------------------------------------------------------------

def trigger_pipeline(output_dir: str, repo_dir: str) -> None:
    """Run the orchestrator as a subprocess.

    Uses the existing .sync.lock mechanism for concurrency control.
    """
    scripts_dir = Path(output_dir) / "scripts"
    if not (scripts_dir / "orchestrator.py").exists():
        scripts_dir = Path(__file__).parent

    subprocess.run(
        ["python3", str(scripts_dir / "orchestrator.py"), output_dir, repo_dir],
        timeout=1800,  # 30 min max
    )


# ---------------------------------------------------------------------------
# Endpoints (only registered when fastapi is available)
# ---------------------------------------------------------------------------

def _register_endpoints(fastapi_app: FastAPI) -> None:
    """Register webhook endpoints on the FastAPI app."""

    @fastapi_app.post("/webhook/{platform}")
    async def receive_webhook(
        platform: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict:
        if platform not in NORMALIZERS:
            raise HTTPException(400, f"Unsupported platform: {platform}")

        payload_bytes = await request.body()
        secret = os.environ.get("AUTODOCS_WEBHOOK_SECRET", "")

        # Verify signature
        if platform == "github":
            sig = request.headers.get("X-Hub-Signature-256", "")
            if not verify_github_signature(payload_bytes, sig, secret):
                raise HTTPException(401, "Invalid signature")
        elif platform == "gitlab":
            token = request.headers.get("X-Gitlab-Token", "")
            if not verify_gitlab_token(token, secret):
                raise HTTPException(401, "Invalid token")

        # Parse payload
        try:
            payload = json.loads(payload_bytes)
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, "Invalid JSON payload")

        # Normalize
        normalizer = NORMALIZERS[platform]
        pr_data = normalizer(payload)
        if pr_data is None:
            return {"status": "ignored", "reason": "not a merge event"}

        # Write fetched-prs.json
        output_dir = os.environ.get("OUTPUT_DIR", "")
        repo_dir = os.environ.get("REPO_DIR", "")
        if not output_dir or not repo_dir:
            raise HTTPException(500, "OUTPUT_DIR and REPO_DIR must be set")

        output_path = Path(output_dir)
        prs_file = output_path / "fetched-prs.json"
        prs_file.write_text(json.dumps([pr_data], indent=2) + "\n")

        # Set lookback to cover this PR
        merged_at = pr_data.get("mergedAt", "")
        if merged_at:
            lookback = merged_at[:10]
            (output_path / "last-successful-run").write_text(f"{lookback}T00:00:00Z")

        # Trigger pipeline in background
        background_tasks.add_task(trigger_pipeline, output_dir, repo_dir)

        return {"status": "queued", "platform": platform, "pr": pr_data.get("number")}

    @fastapi_app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}


if app is not None:
    _register_endpoints(app)


# ---------------------------------------------------------------------------
# Main (standalone server)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="autodocs webhook server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn required. Install: pip install uvicorn", file=sys.stderr)
        sys.exit(2)

    uvicorn.run(app, host=args.host, port=args.port)
