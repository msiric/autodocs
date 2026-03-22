"""Unit tests for webhook_server.py.

These tests cover signature verification, payload normalization, and
endpoint behavior. Requires: pip install fastapi httpx
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# The webhook module requires fastapi. Test signature/normalization functions
# directly (they have no fastapi dependency). Skip endpoint tests if fastapi missing.
try:
    import fastapi as _  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

try:
    from starlette.testclient import TestClient
    HAS_TEST_CLIENT = True
except ImportError:
    HAS_TEST_CLIENT = False

# Signature and normalization functions are pure Python — import directly
# to test them even without fastapi installed.
from webhook_server import (
    app,
    normalize_bitbucket_pr,
    normalize_github_pr,
    normalize_gitlab_mr,
    verify_github_signature,
    verify_gitlab_token,
)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

class TestSignatureVerification:
    def test_github_valid_signature(self):
        payload = b'{"action": "closed"}'
        secret = "test-secret"
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_github_signature(payload, sig, secret) is True

    def test_github_invalid_signature(self):
        assert verify_github_signature(b"payload", "sha256=wrong", "secret") is False

    def test_github_no_secret_skips(self):
        assert verify_github_signature(b"payload", "", "") is True

    def test_gitlab_valid_token(self):
        assert verify_gitlab_token("my-token", "my-token") is True

    def test_gitlab_invalid_token(self):
        assert verify_gitlab_token("wrong", "my-token") is False

    def test_gitlab_no_secret_skips(self):
        assert verify_gitlab_token("anything", "") is True


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_github_pr_merged(self):
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "number": 42,
                "title": "Fix auth",
                "body": "Description",
                "merged_at": "2026-03-20T12:00:00Z",
                "merge_commit_sha": "abc123",
                "user": {"login": "alice"},
            },
        }
        result = normalize_github_pr(payload)
        assert result is not None
        assert result["number"] == 42
        assert result["title"] == "Fix auth"
        assert result["mergeCommit"]["oid"] == "abc123"
        assert result["author"]["login"] == "alice"

    def test_github_pr_closed_not_merged(self):
        payload = {"action": "closed", "pull_request": {"merged": False}}
        assert normalize_github_pr(payload) is None

    def test_github_non_close_event(self):
        payload = {"action": "opened", "pull_request": {"merged": False}}
        assert normalize_github_pr(payload) is None

    def test_gitlab_mr_merged(self):
        payload = {
            "object_attributes": {
                "action": "merge",
                "iid": 10,
                "title": "Update docs",
                "description": "MR description",
                "merged_at": "2026-03-20T12:00:00Z",
                "merge_commit_sha": "def456",
            },
        }
        result = normalize_gitlab_mr(payload)
        assert result is not None
        assert result["number"] == 10

    def test_gitlab_mr_not_merge(self):
        payload = {"object_attributes": {"action": "open"}}
        assert normalize_gitlab_mr(payload) is None

    def test_bitbucket_pr_merged(self):
        payload = {
            "pullrequest": {
                "state": "MERGED",
                "id": 7,
                "title": "BB PR",
                "description": "",
                "updated_on": "2026-03-20T12:00:00Z",
                "merge_commit": {"hash": "ghi789"},
                "author": {"nickname": "bob"},
            },
        }
        result = normalize_bitbucket_pr(payload)
        assert result is not None
        assert result["number"] == 7

    def test_bitbucket_pr_not_merged(self):
        payload = {"pullrequest": {"state": "OPEN"}}
        assert normalize_bitbucket_pr(payload) is None

    def test_github_long_body_truncated(self):
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True, "number": 1, "title": "t",
                "body": "x" * 1000,
                "merged_at": "", "merge_commit_sha": "",
                "user": {"login": ""},
            },
        }
        result = normalize_github_pr(payload)
        assert len(result["body"]) == 500


# ---------------------------------------------------------------------------
# Endpoint tests (require httpx)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_TEST_CLIENT, reason="httpx not installed")
class TestEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_unknown_platform(self, client):
        response = client.post("/webhook/svn", json={})
        assert response.status_code == 400

    @patch.dict(os.environ, {"OUTPUT_DIR": "/tmp/test", "REPO_DIR": "/tmp/repo"})
    def test_github_non_merge_ignored(self, client):
        payload = {"action": "opened", "pull_request": {"merged": False}}
        response = client.post(
            "/webhook/github",
            json=payload,
            headers={"X-Hub-Signature-256": ""},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_github_invalid_signature(self, client):
        with patch.dict(os.environ, {"AUTODOCS_WEBHOOK_SECRET": "my-secret"}):
            response = client.post(
                "/webhook/github",
                content=b'{"action":"closed"}',
                headers={"X-Hub-Signature-256": "sha256=wrong", "Content-Type": "application/json"},
            )
            assert response.status_code == 401
