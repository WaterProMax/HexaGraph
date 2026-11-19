"""P1-REV-07: a negated sentence must never parse as a GitHub write grant."""

from __future__ import annotations

import json

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import parse_github_write_auth

NEGATED = (
    "do not authorize github_write owner=expected repo=repo remote=origin "
    "base_branch=teamwork-001 feature_branch=feat/review"
)


def test_negated_sentence_is_not_accepted() -> None:
    try:
        parsed = parse_github_write_auth(NEGATED)
    except GitHubWriteDenied:
        parsed = None
    assert parsed is None


def test_structured_record_is_accepted_exactly() -> None:
    record = {
        "type": "github_write_grant_v1",
        "verb": "authorize",
        "owner": "expected-owner",
        "repo": "expected-repo",
        "remote": "origin",
        "base_branch": "teamwork-001",
        "feature_branch": "feat/review",
        "allow_push": True,
        "allow_pr_create": True,
        "allow_merge": False,
        "allow_deploy": False,
    }
    parsed = parse_github_write_auth(json.dumps(record))
    assert parsed is not None
    assert parsed.owner == "expected-owner"
    assert parsed.repo == "expected-repo"
    assert parsed.feature_branch == "feat/review"


@pytest.mark.parametrize("text", ["", None, "github_write owner=expected"])
def test_incomplete_or_empty_authorization_is_rejected(text) -> None:
    try:
        parsed = parse_github_write_auth(text)
    except GitHubWriteDenied:
        parsed = None
    assert parsed is None