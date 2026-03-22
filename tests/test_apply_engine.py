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
    apply_edits,
    build_pr_body,
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
