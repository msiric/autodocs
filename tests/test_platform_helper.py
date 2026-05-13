"""Unit tests for platform_helper.py — platform-specific URL construction."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from platform_helper import build_pr_url


# ---------------------------------------------------------------------------
# build_pr_url — one canonical URL per platform
# ---------------------------------------------------------------------------

class TestBuildPrUrl:
    """Each platform has its own URL pattern. These tests are the contract
    that changelog entries (and any other consumer) rely on. Breaking any
    of these silently turns clickable PR links into dead text.
    """

    def test_github(self):
        url = build_pr_url(
            {"platform": "github", "github": {"owner": "msiric", "repo": "autodocs"}},
            pr_number=42,
        )
        assert url == "https://github.com/msiric/autodocs/pull/42"

    def test_ado_canonical_visualstudio_format(self):
        """ADO web URL uses <org>.visualstudio.com/<project>/_git/<repo>/pullrequest/<n>.

        This is the format ADO shows in the address bar and what most
        teams paste in chat. Both visualstudio.com and dev.azure.com
        work as redirects; we pick visualstudio.com for parity with
        the URL pattern teams already see.
        """
        url = build_pr_url(
            {
                "platform": "ado",
                "ado": {"org": "domoreexp", "project": "Teamspace", "repo": "teams-modular-packages"},
            },
            pr_number=1550912,
        )
        assert url == (
            "https://domoreexp.visualstudio.com/Teamspace"
            "/_git/teams-modular-packages/pullrequest/1550912"
        )

    def test_gitlab_default_host(self):
        url = build_pr_url(
            {"platform": "gitlab", "gitlab": {"project_path": "group/project"}},
            pr_number=99,
        )
        assert url == "https://gitlab.com/group/project/-/merge_requests/99"

    def test_gitlab_self_hosted(self):
        """Self-hosted GitLab uses configured host instead of gitlab.com."""
        url = build_pr_url(
            {
                "platform": "gitlab",
                "gitlab": {"project_path": "team/repo", "host": "gitlab.internal.corp"},
            },
            pr_number=15,
        )
        assert url == "https://gitlab.internal.corp/team/repo/-/merge_requests/15"

    def test_gitlab_nested_group_path(self):
        """GitLab project paths can have subgroups (group/subgroup/project)."""
        url = build_pr_url(
            {"platform": "gitlab", "gitlab": {"project_path": "g/sub/proj"}},
            pr_number=7,
        )
        assert url == "https://gitlab.com/g/sub/proj/-/merge_requests/7"

    def test_bitbucket(self):
        url = build_pr_url(
            {"platform": "bitbucket", "bitbucket": {"workspace": "myws", "repo": "myrepo"}},
            pr_number=12,
        )
        assert url == "https://bitbucket.org/myws/myrepo/pull-requests/12"

    def test_returns_empty_string_when_config_incomplete(self):
        """Missing platform-specific fields → empty string, not crash."""
        # Missing github.owner
        assert build_pr_url({"platform": "github", "github": {"repo": "r"}}, 1) == ""
        # Missing ado.repo
        assert build_pr_url({"platform": "ado", "ado": {"org": "o", "project": "p"}}, 1) == ""
        # Missing bitbucket.workspace
        assert build_pr_url({"platform": "bitbucket", "bitbucket": {"repo": "r"}}, 1) == ""

    def test_returns_empty_for_unknown_platform(self):
        assert build_pr_url({"platform": "unknown"}, 42) == ""

    def test_returns_empty_for_zero_pr_number(self):
        assert build_pr_url(
            {"platform": "github", "github": {"owner": "x", "repo": "y"}},
            pr_number=0,
        ) == ""

    def test_accepts_string_or_int_pr_number(self):
        """PR number may come in as int (Python) or string (JSON)."""
        cfg = {"platform": "github", "github": {"owner": "x", "repo": "y"}}
        assert build_pr_url(cfg, 42).endswith("/pull/42")
        assert build_pr_url(cfg, "42").endswith("/pull/42")
