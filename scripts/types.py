"""Shared type definitions for autodocs helpers."""

from __future__ import annotations

from typing import TypedDict


class FileInfo(TypedDict):
    change_type: str
    path: str


class PRInfo(TypedDict, total=False):
    number: int
    title: str
    author: str
    classification: str
    files: list[FileInfo]


class DriftEntry(TypedDict):
    date: str
    doc: str
    section: str
    trigger: str
    confidence: str


class Alert(TypedDict, total=False):
    doc: str
    section: str
    prs: list[int]
    confidence: str
    description_hint: str


class ChangelogEntry(TypedDict, total=False):
    pr_number: int | None
    text: str


class DocSection(TypedDict, total=False):
    name: str
    disambiguated: str
    level: int
    parent: str


class VerifyResult(TypedDict, total=False):
    doc: str
    find_text: str
    confidence: str
    status: str
    reason: str


class ReplaceValue(TypedDict, total=False):
    value: str
    type: str
    status: str
    source: str
    reason: str


class ReplaceResult(TypedDict, total=False):
    doc: str
    section: str
    gate: str
    values: list[ReplaceValue]


class FeedbackPR(TypedDict, total=False):
    pr_number: int
    platform: str
    date: str
    state: str
    merged_date: str
    close_reason: str
    suggestions: list[dict[str, str]]
