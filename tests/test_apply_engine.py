"""Unit tests for apply_engine.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from apply_engine import (
    ApplyResult,
    Suggestion,
    _clean_llm_artifacts,
    _merge_changelog_into,
    _run_pr_cli_with_retry,
    add_reviewers,
    apply_edits,
    build_pr_body,
    create_pr,
    filter_suggestions,
    parse_suggestions,
    record_tracking,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SUGGESTIONS_MD = """---
date: 2026-03-20
suggestion_count: 2
verified: 2/2
---
# Suggested Updates — 2026-03-20

## guide.md — Authentication
**Triggered by:** PR #42 "Fix auth handler"
**Confidence:** CONFIDENT

### FIND (in guide.md, section "Authentication"):
> GET /api/users — Returns all users

### REPLACE WITH:
> GET /api/users — Returns all users. Rate limited: 100 req/min.

**Verified:** YES — FIND text confirmed in doc (line 10)

### Reasoning:
PR #42 added rate limiting to the users endpoint.

---

## guide.md — Error Handling
**Triggered by:** PR #43 "Add error logging"
**Confidence:** REVIEW

### FIND (anchor — insert after this line):
> ## Error Handling

### INSERT AFTER:
> Errors are now logged to the central logging service.

**Verified:** YES — anchor confirmed in doc

### Reasoning:
PR #43 added centralized error logging.
"""

REVIEW_ONLY_MD = """---
date: 2026-03-20
suggestion_count: 1
verified: 1/1
---
# Suggested Updates

## guide.md — API
**Triggered by:** PR #50
**Confidence:** REVIEW

### FIND:
> some text

### REPLACE WITH:
> new text

**Verified:** YES
"""


# ---------------------------------------------------------------------------
# parse_suggestions
# ---------------------------------------------------------------------------

class TestParseSuggestions:
    def test_parses_replace_and_insert(self):
        suggestions = parse_suggestions(SAMPLE_SUGGESTIONS_MD)
        assert len(suggestions) == 2

        s1 = suggestions[0]
        assert s1.doc == "guide.md"
        assert s1.section == "Authentication"
        assert s1.operation == "REPLACE"
        assert s1.find_text == "GET /api/users — Returns all users"
        assert "Rate limited" in s1.replace_text
        assert s1.confidence == "CONFIDENT"
        assert s1.verified == "YES"
        assert "PR #42" in s1.triggered_by

        s2 = suggestions[1]
        assert s2.operation == "INSERT_AFTER"
        assert s2.confidence == "REVIEW"

    def test_empty_input(self):
        assert parse_suggestions("") == []
        assert parse_suggestions("No suggestions.") == []

    def test_single_suggestion(self):
        md = """## doc.md — Section
**Triggered by:** PR #1
**Confidence:** CONFIDENT

### FIND:
> old text

### REPLACE WITH:
> new text

**Verified:** YES
"""
        suggestions = parse_suggestions(md)
        assert len(suggestions) == 1
        assert suggestions[0].find_text == "old text"
        assert suggestions[0].replace_text == "new text"

    def test_multiline_find_replace(self):
        md = """## doc.md — Section
**Confidence:** CONFIDENT

### FIND:
> line one
> line two
> line three

### REPLACE WITH:
> replaced one
> replaced two

**Verified:** YES
"""
        suggestions = parse_suggestions(md)
        assert len(suggestions) == 1
        assert suggestions[0].find_text == "line one\nline two\nline three"
        assert suggestions[0].replace_text == "replaced one\nreplaced two"

    def test_insert_after_with_bare_blockquote(self):
        """Real LLM output: INSERT AFTER block starts with bare '>' (empty blockquote line)."""
        md = """## doc.md — Section
**Triggered by:** PR #1
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> anchor text here

### INSERT AFTER:
>
> ### New Subsection
>
> Content of the new subsection.
> More content here.

**Verified:** YES
"""
        suggestions = parse_suggestions(md)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s.operation == "INSERT_AFTER"
        assert "New Subsection" in s.replace_text
        assert "More content" in s.replace_text
        assert s.replace_text.startswith("\n")  # empty line from bare >

    def test_real_llm_output_format(self):
        """Test against the exact format from autodocs-demo output."""
        md = """---
date: 2026-03-10
suggestion_count: 2
verified: 2/2
---
# Suggested Updates — 2026-03-10

## architecture.md — API Endpoints
**Triggered by:** PR #1 "feat: add auth"
**Confidence:** CONFIDENT

### FIND (in architecture.md, section "API Endpoints"):
> The API exposes three endpoints:
>
> | Endpoint | Method |
> |----------|--------|
> | `/api/users` | GET |

### REPLACE WITH:
> The API exposes five endpoints:
>
> | Endpoint | Method |
> |----------|--------|
> | `/api/users` | GET |
> | `/api/users/:id` | PATCH |

**Verified:** YES — FIND text confirmed in doc

### Reasoning:
PR #1 added PATCH endpoint.

---

## architecture.md — Authentication
**Triggered by:** PR #1 "feat: add auth"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> Role hierarchy: admin > member > viewer.

### INSERT AFTER:
>
> ### API Key Auth
>
> Keys are passed via `X-API-Key` header.

**Verified:** YES — anchor confirmed in doc

### Reasoning:
PR #1 added API key auth.
"""
        suggestions = parse_suggestions(md)
        assert len(suggestions) == 2
        assert suggestions[0].operation == "REPLACE"
        assert "five endpoints" in suggestions[0].replace_text
        assert suggestions[1].operation == "INSERT_AFTER"
        assert "API Key Auth" in suggestions[1].replace_text


# ---------------------------------------------------------------------------
# filter_suggestions
# ---------------------------------------------------------------------------

class TestFilterSuggestions:
    def test_confident_yes_passes(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "YES", "", "")
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 1
        assert len(skipped) == 0

    def test_review_skipped(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "REVIEW", "YES", "", "")
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 0
        assert skipped[0]["reason"] == "REVIEW confidence"

    def test_verified_no_skipped(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "NO", "", "")
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 0
        assert "Verified: NO" in skipped[0]["reason"]

    def test_find_verification_fail(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "YES", "", "")
        (tmp_path / "verified-suggestions.json").write_text(
            json.dumps([{"status": "FAIL", "reason": "not found"}])
        )
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 0
        assert "FIND verification" in skipped[0]["reason"]

    def test_replace_blocked(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "YES", "", "")
        (tmp_path / "replace-verification.json").write_text(
            json.dumps([{"gate": "BLOCK", "values": [{"status": "MISMATCH", "reason": "bad value"}]}])
        )
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 0
        assert "REPLACE blocked" in skipped[0]["reason"]

    def test_replace_auto_apply(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "YES", "", "")
        (tmp_path / "replace-verification.json").write_text(
            json.dumps([{"gate": "AUTO_APPLY", "values": []}])
        )
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 1

    def test_no_verification_files_passes(self, tmp_path: Path):
        s = Suggestion("doc.md", "Sec", "REPLACE", "find", "replace", "CONFIDENT", "YES", "", "")
        applicable, skipped = filter_suggestions([s], tmp_path)
        assert len(applicable) == 1


# ---------------------------------------------------------------------------
# apply_edits
# ---------------------------------------------------------------------------

class TestApplyEdits:
    def test_replace_works(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("# Guide\n\nGET /api/users — Returns all users\n\nMore content.\n")
        s = Suggestion("guide.md", "API", "REPLACE",
                        "GET /api/users — Returns all users",
                        "GET /api/users — Returns all users. Rate limited.",
                        "CONFIDENT", "YES", "PR #1", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        assert "Rate limited" in doc.read_text()

    def test_insert_after_works(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("# Guide\n\n## Error Handling\n\nExisting content.\n")
        s = Suggestion("guide.md", "Error Handling", "INSERT_AFTER",
                        "## Error Handling",
                        "Errors are logged centrally.",
                        "CONFIDENT", "YES", "PR #2", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        content = doc.read_text()
        assert "Errors are logged centrally." in content
        assert content.index("Errors are logged") > content.index("## Error Handling")

    def test_find_not_found_expired(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("# Guide\n\n## Authentication\n\nDifferent content.\n")
        s = Suggestion("guide.md", "Authentication", "REPLACE",
                        "text that does not exist",
                        "new text",
                        "CONFIDENT", "YES", "PR #3", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 0
        assert len(expired) == 1
        assert "EXPIRED" in expired[0]["reason"]

    def test_replace_whitespace_normalized_match(self, tmp_path: Path):
        """FIND text has different whitespace than doc — triggers normalized path."""
        doc = tmp_path / "guide.md"
        # Doc has double space between words; FIND has single space
        doc.write_text("GET  /api/users  —  Returns all users\n\nMore content.\n")
        s = Suggestion("guide.md", "API", "REPLACE",
                        "GET /api/users — Returns all users",
                        "GET /api/users — Rate limited.",
                        "CONFIDENT", "YES", "PR #10", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        assert "whitespace-normalized" in applied[0].get("note", "")
        content = doc.read_text()
        assert "Rate limited" in content
        assert "More content" in content

    def test_replace_tab_vs_space(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("Header\n\tindented line\nFooter\n")
        s = Suggestion("guide.md", "Sec", "REPLACE",
                        "Header\n    indented line",
                        "Header\n    new content",
                        "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        assert "Footer" in doc.read_text()

    def test_replace_extra_blank_lines(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("Para one.\n\n\n\nPara two.\n\nPara three.\n")
        s = Suggestion("guide.md", "Sec", "REPLACE",
                        "Para one.\n\nPara two.",
                        "Combined paragraph.",
                        "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        content = doc.read_text()
        assert "Combined paragraph" in content
        assert "Para three" in content

    def test_replace_crlf_line_endings(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("Line one\r\nLine two\r\nLine three\r\n")
        s = Suggestion("guide.md", "Sec", "REPLACE",
                        "Line one\nLine two",
                        "Replaced lines",
                        "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        assert "Line three" in doc.read_text()

    def test_replace_regex_special_chars(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("| Col A | Col B |\n|-------|-------|\n| val1  | val2  |\nFooter\n")
        s = Suggestion("guide.md", "Sec", "REPLACE",
                        "| Col A | Col B |\n|-------|-------|",
                        "| Col A | Col B | Col C |\n|-------|-------|-------|",
                        "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert len(applied) == 1
        assert "Col C" in doc.read_text()
        assert "Footer" in doc.read_text()

    def test_section_removed(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("# Guide\n\nNo sections here.\n")
        s = Suggestion("guide.md", "Missing Section", "REPLACE",
                        "old text", "new text",
                        "CONFIDENT", "YES", "PR #4", "")
        applied, expired = apply_edits([s], {"guide.md": doc})
        assert "SECTION REMOVED" in expired[0]["reason"]

    def test_doc_not_found(self, tmp_path: Path):
        s = Suggestion("missing.md", "Sec", "REPLACE", "a", "b", "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s], {"missing.md": tmp_path / "nope.md"})
        assert len(expired) == 1

    def test_multiple_edits_same_file(self, tmp_path: Path):
        doc = tmp_path / "guide.md"
        doc.write_text("AAA\nBBB\nCCC\n")
        s1 = Suggestion("guide.md", "A", "REPLACE", "AAA", "XXX", "CONFIDENT", "YES", "", "")
        s2 = Suggestion("guide.md", "B", "REPLACE", "BBB", "YYY", "CONFIDENT", "YES", "", "")
        applied, expired = apply_edits([s1, s2], {"guide.md": doc})
        assert len(applied) == 2
        content = doc.read_text()
        assert "XXX" in content
        assert "YYY" in content
        assert "AAA" not in content


# ---------------------------------------------------------------------------
# build_pr_body
# ---------------------------------------------------------------------------

class TestBuildPrBody:
    def test_with_applied(self):
        body = build_pr_body(
            [{"doc": "guide.md", "section": "Auth", "operation": "REPLACE", "triggered_by": "PR #1"}],
            [], [], "2026-03-20",
        )
        assert "Applied 1 suggestions" in body
        assert "guide.md — Auth" in body
        assert "autodocs:meta" in body

    def test_all_skipped(self):
        body = build_pr_body(
            [], [{"suggestion": "s", "reason": "REVIEW"}], [], "2026-03-20",
        )
        assert "No suggestions were auto-applied" in body
        assert "Needs Manual Review" in body

    def test_empty(self):
        body = build_pr_body([], [], [], "2026-03-20")
        assert "autodocs" in body


# ---------------------------------------------------------------------------
# LLM artifact cleaning
# ---------------------------------------------------------------------------

class TestCleanLlmArtifacts:
    def test_removes_note_lines(self, tmp_path: Path):
        doc = tmp_path / "test.md"
        doc.write_text("## Section\n\nReal content.\n\n(Note: this should be removed.)\n\nMore content.\n")
        _clean_llm_artifacts(doc)
        result = doc.read_text()
        assert "Real content" in result
        assert "More content" in result
        assert "(Note:" not in result

    def test_collapses_excessive_blank_lines(self, tmp_path: Path):
        doc = tmp_path / "test.md"
        doc.write_text("Line one.\n\n\n\n\n\nLine two.\n")
        _clean_llm_artifacts(doc)
        result = doc.read_text()
        assert "Line one" in result
        assert "Line two" in result
        # 6 blank lines collapsed to at most 2 (standard markdown paragraph gap)
        assert "\n\n\n\n" not in result

    def test_removes_duplicate_headers(self, tmp_path: Path):
        doc = tmp_path / "test.md"
        doc.write_text("## Section\n\nContent.\n\n## Section\n\nMore content.\n")
        _clean_llm_artifacts(doc)
        result = doc.read_text()
        assert result.count("## Section") == 1
        assert "Content" in result
        assert "More content" in result

    def test_preserves_normal_content(self, tmp_path: Path):
        doc = tmp_path / "test.md"
        original = "# Title\n\n## Section 1\n\nContent here.\n\n## Section 2\n\nMore content.\n"
        doc.write_text(original)
        _clean_llm_artifacts(doc)
        result = doc.read_text()
        assert "# Title" in result
        assert "## Section 1" in result
        assert "## Section 2" in result
        assert "Content here" in result


# ---------------------------------------------------------------------------
# changelog merge (append-only)
# ---------------------------------------------------------------------------

class TestChangelogMerge:
    def test_new_entries_appended_to_existing(self, tmp_path: Path):
        """New PR entries are added; existing entries preserved."""
        dest = tmp_path / "dest.md"
        dest.write_text(
            "# doc.md — Changelog\n\n"
            "## Auth\n\n"
            "### 2026-03-01 — PR #1 by alice\n"
            "**Changed:** Old entry.\n**Why:** Old reason.\n\n---\n"
        )
        source = tmp_path / "source.md"
        source.write_text(
            "# doc.md — Changelog\n\n"
            "## Auth\n\n"
            "### 2026-03-10 — PR #5 by bob\n"
            "**Changed:** New entry.\n**Why:** New reason.\n\n"
            "### 2026-03-01 — PR #1 by alice\n"
            "**Changed:** Reworded.\n**Why:** Different.\n\n---\n"
        )
        _merge_changelog_into(source, dest)
        result = dest.read_text()
        assert "PR #5" in result   # new entry added
        assert "PR #1" in result   # old entry kept
        assert "Old entry" in result  # original text preserved, not LLM rewrite
        assert "Reworded" not in result  # LLM's rewrite of PR #1 NOT used

    def test_no_new_entries_preserves_dest(self, tmp_path: Path):
        """If source has no new PRs, dest is unchanged."""
        original = (
            "# doc.md — Changelog\n\n"
            "## Auth\n\n"
            "### 2026-03-01 — PR #1 by alice\n"
            "**Changed:** Original.\n\n---\n"
        )
        dest = tmp_path / "dest.md"
        dest.write_text(original)
        source = tmp_path / "source.md"
        source.write_text(original)  # same content
        _merge_changelog_into(source, dest)
        assert dest.read_text() == original  # unchanged

    def test_new_section_added(self, tmp_path: Path):
        """New sections from source are appended to dest."""
        dest = tmp_path / "dest.md"
        dest.write_text(
            "# doc.md — Changelog\n\n"
            "## Auth\n\n"
            "### 2026-03-01 — PR #1 by alice\n"
            "**Changed:** Entry.\n\n---\n"
        )
        source = tmp_path / "source.md"
        source.write_text(
            "# doc.md — Changelog\n\n"
            "## API Endpoints\n\n"
            "### 2026-03-10 — PR #5 by bob\n"
            "**Changed:** New section entry.\n\n---\n"
        )
        _merge_changelog_into(source, dest)
        result = dest.read_text()
        assert "Auth" in result
        assert "API Endpoints" in result
        assert "PR #1" in result
        assert "PR #5" in result


# ---------------------------------------------------------------------------
# record_tracking
# ---------------------------------------------------------------------------

class TestRecordTracking:
    def test_creates_new_file(self, tmp_path: Path):
        record_tracking(tmp_path, 99, "github", "2026-03-20",
                         [{"doc": "guide.md", "section": "Auth", "operation": "REPLACE"}])
        data = json.loads((tmp_path / "feedback" / "open-prs.json").read_text())
        assert len(data) == 1
        assert data[0]["pr_number"] == 99

    def test_appends_to_existing(self, tmp_path: Path):
        fb = tmp_path / "feedback"
        fb.mkdir()
        (fb / "open-prs.json").write_text('[{"pr_number": 1, "state": "open"}]')
        record_tracking(tmp_path, 99, "github", "2026-03-20", [])
        data = json.loads((fb / "open-prs.json").read_text())
        assert len(data) == 2

    def test_idempotent(self, tmp_path: Path):
        record_tracking(tmp_path, 99, "github", "2026-03-20", [])
        record_tracking(tmp_path, 99, "github", "2026-03-20", [])
        data = json.loads((tmp_path / "feedback" / "open-prs.json").read_text())
        assert len(data) == 1


# ---------------------------------------------------------------------------
# add_reviewers — guards against CLI argument regressions
# ---------------------------------------------------------------------------

class TestAddReviewers:
    """Verify each platform's CLI invocation matches the actual CLI surface.

    These tests don't actually run the CLI — they capture the command lists
    sent to subprocess.run and assert the argument shape. This catches the
    class of bug where a CLI changes its accepted arguments and we silently
    drop reviewers (e.g., 'az repos pr reviewer add' does NOT accept -p).
    """

    def _captured_calls(self, monkeypatch, config: dict, pr_number: int = 1) -> list[list[str]]:
        """Run add_reviewers with subprocess.run patched to capture cmd lists."""
        import subprocess
        calls: list[list[str]] = []

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _Result()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        add_reviewers(config, pr_number)
        return calls

    def test_ado_command_has_no_project_flag(self, monkeypatch):
        """az repos pr reviewer add must not include -p/--project.

        This was a real production bug: the CLI rejected the command with
        'unrecognized arguments: -p Teamspace' and reviewers were silently
        dropped from every ADO PR.
        """
        calls = self._captured_calls(monkeypatch, {
            "platform": "ado",
            "ado": {"org": "myorg", "project": "MyProject"},
            "auto_pr": {"reviewers": ["a@x.com", "b@x.com"]},
        })
        assert len(calls) == 2
        for cmd in calls:
            assert "-p" not in cmd, f"-p must not appear in: {cmd}"
            assert "--project" not in cmd, f"--project must not appear in: {cmd}"
            assert "az" in cmd[0]
            assert "--id" in cmd
            assert "--reviewers" in cmd
            assert "--org" in cmd

    def test_ado_skips_when_no_org(self, monkeypatch):
        """Without ado.org configured, no reviewer commands should run."""
        calls = self._captured_calls(monkeypatch, {
            "platform": "ado",
            "ado": {},  # missing org
            "auto_pr": {"reviewers": ["a@x.com"]},
        })
        assert calls == []

    def test_github_uses_gh_pr_edit(self, monkeypatch):
        calls = self._captured_calls(monkeypatch, {
            "platform": "github",
            "github": {"owner": "me", "repo": "r"},
            "auto_pr": {"reviewers": ["a@x.com"]},
        })
        assert len(calls) == 1
        assert calls[0][:3] == ["gh", "pr", "edit"]
        assert "--add-reviewer" in calls[0]

    def test_no_op_when_no_reviewers(self, monkeypatch):
        calls = self._captured_calls(monkeypatch, {
            "platform": "ado",
            "ado": {"org": "x"},
            "auto_pr": {},  # no reviewers
        })
        assert calls == []

    def test_no_op_when_no_pr_number(self, monkeypatch):
        calls = self._captured_calls(monkeypatch, {
            "platform": "ado",
            "ado": {"org": "x"},
            "auto_pr": {"reviewers": ["a@x.com"]},
        }, pr_number=0)
        assert calls == []


# ---------------------------------------------------------------------------
# _run_pr_cli_with_retry — retry on transient errors, log on final failure
# ---------------------------------------------------------------------------
# Mirrors the Fix #2 contract that fetch_pr_details got: the bug we observed
# was `az repos pr create` failing silently mid-apply (returncode != 0,
# no log) — leaving the just-pushed autodocs branch orphaned with no PR
# and no surfaced reason in sync.log. This helper is the shared retry+log
# wrapper for create_pr and add_reviewers's per-platform CLI invocations.

class TestRunPrCliWithRetry:
    def _stub_run(self, monkeypatch, sequence):
        """Patch subprocess.run with a sequence of (returncode, stdout, stderr).
        Returns the recorded call list."""
        import subprocess
        calls: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            idx = len(calls)
            calls.append(list(cmd))
            rc, stdout, stderr = sequence[min(idx, len(sequence) - 1)]
            return type("_R", (), {"returncode": rc, "stdout": stdout, "stderr": stderr})()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        # Don't actually sleep between attempts during tests
        monkeypatch.setattr("apply_engine.time.sleep", lambda *_a, **_kw: None)
        return calls

    def test_success_first_try(self, monkeypatch, capsys):
        """Happy path: one call, no retry, no warning."""
        calls = self._stub_run(monkeypatch, [(0, "1234\n", "")])
        ok, stdout = _run_pr_cli_with_retry("az", "create_pr", ["az", "repos", "pr", "create"])
        assert ok is True
        assert stdout == "1234\n"
        assert len(calls) == 1
        assert "WARN" not in capsys.readouterr().err

    def test_transient_failure_then_success(self, monkeypatch, capsys):
        """Retryable error (503) → retry → success returns stdout, no warn."""
        calls = self._stub_run(monkeypatch, [
            (1, "", "TF503: Service Unavailable"),
            (0, "5678\n", ""),
        ])
        ok, stdout = _run_pr_cli_with_retry(
            "az", "create_pr", ["az", "repos", "pr", "create"],
            pr_label="branch x",
        )
        assert ok is True
        assert stdout == "5678\n"
        assert len(calls) == 2, "expected one retry"
        assert "WARN" not in capsys.readouterr().err

    def test_transient_failure_twice_warns(self, monkeypatch, capsys):
        """Retryable failure twice → return False, log WARN with pr_label."""
        calls = self._stub_run(monkeypatch, [
            (1, "", "network timeout"),
            (1, "", "network timeout"),
        ])
        ok, _ = _run_pr_cli_with_retry(
            "az", "create_pr", ["az", "repos", "pr", "create"],
            pr_label="branch user/me/autodocs-2026-05-14",
        )
        assert ok is False
        assert len(calls) == 2, "max two attempts (one retry)"
        warning = capsys.readouterr().err
        assert "WARN: create_pr(az)" in warning
        assert "branch user/me/autodocs-2026-05-14" in warning
        assert "timeout" in warning

    def test_permanent_failure_does_not_retry(self, monkeypatch, capsys):
        """Non-retryable error (e.g., unrecognized argument) → single call → warn."""
        calls = self._stub_run(monkeypatch, [
            (1, "", "ERROR: unrecognized argument: --bogus"),
        ])
        ok, _ = _run_pr_cli_with_retry(
            "az", "create_pr", ["az", "repos", "pr", "create"],
            pr_label="branch x",
        )
        assert ok is False
        assert len(calls) == 1, "permanent errors must NOT retry"
        warning = capsys.readouterr().err
        assert "WARN: create_pr(az)" in warning
        assert "unrecognized argument" in warning

    def test_cli_not_installed_silent(self, monkeypatch, capsys):
        """FileNotFoundError → return False silently. Same suppression as
        fetch_pr_details — operator notices the platform-wide failure
        without per-call log noise."""
        import subprocess

        def _missing(*_a, **_kw):
            raise FileNotFoundError("az: command not found")

        monkeypatch.setattr(subprocess, "run", _missing)
        ok, stdout = _run_pr_cli_with_retry("az", "create_pr", ["az", "repos"])
        assert ok is False
        assert stdout == ""
        assert "WARN" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# create_pr — silent failures are now observable
# ---------------------------------------------------------------------------

class TestCreatePrObservability:
    """Before Fix #6, create_pr returned None on any CLI failure with no log;
    an ADO API blip during apply silently dropped the PR even though the
    branch had been pushed. These tests pin the new contract: failures
    surface in stderr (routed to sync.err.log) with the branch name."""

    def _stub_run(self, monkeypatch, returncode: int, stdout: str = "", stderr: str = ""):
        import subprocess
        calls: list[list[str]] = []

        def _fake(cmd, **kwargs):
            calls.append(list(cmd))
            return type("_R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()

        monkeypatch.setattr(subprocess, "run", _fake)
        monkeypatch.setattr("apply_engine.time.sleep", lambda *_a, **_kw: None)
        return calls

    def test_ado_failure_returns_none_and_logs(self, monkeypatch, capsys):
        self._stub_run(monkeypatch, returncode=1, stderr="ERROR: unexpected failure")
        result = create_pr(
            {"platform": "ado", "ado": {"org": "myorg", "project": "MyProject", "repo": "r"}},
            branch="user/me/autodocs-2026-05-14",
            title="t", body="b",
        )
        assert result is None
        err = capsys.readouterr().err
        assert "WARN: create_pr(az)" in err
        assert "branch user/me/autodocs-2026-05-14" in err
        assert "unexpected failure" in err

    def test_ado_success_returns_pr_number(self, monkeypatch, capsys):
        self._stub_run(monkeypatch, returncode=0, stdout="1564563\n")
        result = create_pr(
            {"platform": "ado", "ado": {"org": "myorg", "project": "MyProject", "repo": "r"}},
            branch="x", title="t", body="b",
        )
        assert result == 1564563
        assert "WARN" not in capsys.readouterr().err

    def test_github_failure_logs(self, monkeypatch, capsys):
        self._stub_run(monkeypatch, returncode=1, stderr="GraphQL error: not found")
        result = create_pr(
            {"platform": "github", "github": {"owner": "o", "repo": "r"}},
            branch="x", title="t", body="b",
        )
        assert result is None
        err = capsys.readouterr().err
        assert "WARN: create_pr(gh)" in err
        assert "not found" in err

    def test_gitlab_failure_logs(self, monkeypatch, capsys):
        self._stub_run(monkeypatch, returncode=1, stderr="403 forbidden")
        result = create_pr(
            {"platform": "gitlab", "gitlab": {"project_path": "g/r"}},
            branch="x", title="t", body="b",
        )
        assert result is None
        err = capsys.readouterr().err
        assert "WARN: create_pr(glab)" in err

    def test_bitbucket_http_failure_logs(self, monkeypatch, capsys):
        """Bitbucket uses urllib not subprocess, but the failure must still
        surface (the silent-fallback pattern is the same)."""
        import urllib.error
        import urllib.request

        def _raise(*_a, **_kw):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        monkeypatch.setenv("BITBUCKET_TOKEN", "tok")
        result = create_pr(
            {"platform": "bitbucket", "bitbucket": {"workspace": "ws", "repo": "r"}},
            branch="user/me/x", title="t", body="b",
        )
        assert result is None
        err = capsys.readouterr().err
        assert "WARN: create_pr(bitbucket)" in err
        assert "user/me/x" in err


# ---------------------------------------------------------------------------
# add_reviewers — same retry/log treatment applied to reviewer assignment
# ---------------------------------------------------------------------------

class TestAddReviewersObservability:
    """Before Fix #6, _run_reviewer_cmd printed a warning but didn't retry;
    a single ADO API flake silently dropped that reviewer. Verify the new
    helper retries transients and surfaces permanent failures."""

    def _stub_run(self, monkeypatch, sequence):
        import subprocess
        calls: list[list[str]] = []

        def _fake(cmd, **kwargs):
            idx = len(calls)
            calls.append(list(cmd))
            rc, stdout, stderr = sequence[min(idx, len(sequence) - 1)]
            return type("_R", (), {"returncode": rc, "stdout": stdout, "stderr": stderr})()

        monkeypatch.setattr(subprocess, "run", _fake)
        monkeypatch.setattr("apply_engine.time.sleep", lambda *_a, **_kw: None)
        return calls

    def test_ado_reviewer_transient_then_success(self, monkeypatch, capsys):
        """503 once, then OK: one retry, no warn, two calls total."""
        calls = self._stub_run(monkeypatch, [
            (1, "", "TF503 Service Unavailable"),
            (0, "", ""),
        ])
        add_reviewers(
            {"platform": "ado", "ado": {"org": "myorg"},
             "auto_pr": {"reviewers": ["a@x.com"]}},
            pr_number=42,
        )
        assert len(calls) == 2
        assert "WARN" not in capsys.readouterr().err

    def test_ado_reviewer_permanent_failure_warns(self, monkeypatch, capsys):
        calls = self._stub_run(monkeypatch, [
            (1, "", "ERROR: User not found"),
        ])
        add_reviewers(
            {"platform": "ado", "ado": {"org": "myorg"},
             "auto_pr": {"reviewers": ["typo@x.com"]}},
            pr_number=42,
        )
        assert len(calls) == 1
        err = capsys.readouterr().err
        assert "WARN: add_reviewer(az)" in err
        assert "PR #42, reviewer typo@x.com" in err
        assert "User not found" in err

    def test_multi_reviewer_independent_failures(self, monkeypatch, capsys):
        """Failure for one reviewer must not block the next."""
        calls = self._stub_run(monkeypatch, [
            (1, "", "User not found"),  # for first reviewer (permanent → no retry)
            (0, "", ""),                # for second reviewer (success)
        ])
        add_reviewers(
            {"platform": "ado", "ado": {"org": "myorg"},
             "auto_pr": {"reviewers": ["typo@x.com", "ok@x.com"]}},
            pr_number=42,
        )
        # 1 (fail, no retry) + 1 (success) = 2 calls
        assert len(calls) == 2
        err = capsys.readouterr().err
        assert "WARN: add_reviewer(az)" in err
        assert "typo@x.com" in err
        # Second reviewer succeeded — no warning for ok@x.com
        assert "ok@x.com" not in err
