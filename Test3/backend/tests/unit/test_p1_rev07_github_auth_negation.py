"""P1-REV-07 / F-09: GitHub write authorization must be an explicit allow record.

Only a structured record (JSON object or its canonical single-line form) with a
positive ``authorize`` verb and every required field is accepted.  Natural
language, negations, substrings and partial records are rejected.  No test
touches the network or a real remote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth, parse_github_write_auth
from app.tools.live_git import create_pr_idempotent, push_once

NEGATED = (
    "do not authorize github_write owner=expected repo=repo remote=origin "
    "base_branch=teamwork-001 feature_branch=feat/review"
)

CANONICAL = (
    "github_write_grant_v1 authorize owner=example-owner repo=example-repo "
    "remote=origin base_branch=teamwork-001 feature_branch=feat/test3-agent-team-v1 "
    "allow_push=true allow_pr_create=true allow_merge=false allow_deploy=false"
)


def _record(**overrides):
    record = {
        "type": "github_write_grant_v1",
        "verb": "authorize",
        "owner": "example-owner",
        "repo": "example-repo",
        "remote": "origin",
        "base_branch": "teamwork-001",
        "feature_branch": "feat/test3-agent-team-v1",
        "allow_push": True,
        "allow_pr_create": True,
        "allow_merge": False,
        "allow_deploy": False,
    }
    record.update(overrides)
    return record


def _parse_or_none(text: str | None) -> GitHubWriteAuth | None:
    try:
        return parse_github_write_auth(text)
    except GitHubWriteDenied:
        return None


def test_negated_sentence_is_not_accepted() -> None:
    assert _parse_or_none(NEGATED) is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "github_write",
        "github_write owner=expected",
        "authorize github_write owner=expected repo=repo remote=origin "
        "base_branch=teamwork-001 feature_branch=feat/review",
        "授权 github_write：owner=expected repo=repo remote=origin "
        "base_branch=teamwork-001 feature_branch=feat/review",
        json.dumps(["github_write_grant_v1"]),
        json.dumps(_record(type="github_write")),
        "{not json",
    ],
)
def test_incomplete_unstructured_or_empty_authorization_is_rejected(text) -> None:
    assert _parse_or_none(text) is None


@pytest.mark.parametrize(
    "verb",
    ["deny", "revoke", "do not authorize", "DO_NOT_AUTHORIZE", "AUTHORIZE", ""],
)
def test_illegal_verb_is_rejected(verb: str) -> None:
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(verb=verb)))


@pytest.mark.parametrize(
    "field",
    ["owner", "repo", "remote", "base_branch", "feature_branch"],
)
def test_missing_required_field_is_rejected(field: str) -> None:
    record = _record()
    record.pop(field)
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(record))


@pytest.mark.parametrize("field", ["owner", "repo", "remote", "base_branch", "feature_branch"])
def test_empty_required_field_is_rejected(field: str) -> None:
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(**{field: "  "})))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allow_push", "true"),
        ("allow_push", 1),
        ("allow_push", False),
        ("allow_pr_create", False),
        ("allow_merge", True),
        ("allow_deploy", True),
    ],
)
def test_unsafe_permission_flags_are_rejected(field: str, value) -> None:
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(**{field: value})))


def test_structured_record_is_accepted_exactly() -> None:
    parsed = parse_github_write_auth(json.dumps(_record()))
    assert isinstance(parsed, GitHubWriteAuth)
    assert parsed.owner == "example-owner"
    assert parsed.repo == "example-repo"
    assert parsed.remote == "origin"
    assert parsed.base_branch == "teamwork-001"
    assert parsed.feature_branch == "feat/test3-agent-team-v1"


def test_canonical_single_line_is_accepted_exactly() -> None:
    parsed = parse_github_write_auth(CANONICAL)
    assert isinstance(parsed, GitHubWriteAuth)
    assert parsed.owner == "example-owner"
    assert parsed.repo == "example-repo"
    assert parsed.remote == "origin"
    assert parsed.base_branch == "teamwork-001"
    assert parsed.feature_branch == "feat/test3-agent-team-v1"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(extra="surprise")))


def test_field_values_must_not_contain_whitespace_or_control_characters() -> None:
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(feature_branch="feat/a b")))
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth(json.dumps(_record(repo="repo\n")))


class _ExplodingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        raise AssertionError(f"rejected authorization must not run: {argv}")


def test_rejected_records_never_reach_git_or_gh(tmp_path: Path) -> None:
    for text in (NEGATED, "github_write", json.dumps(_record(verb="deny")), ""):
        auth = _parse_or_none(text)
        assert auth is None, text
        runner = _ExplodingRunner()
        with pytest.raises(GitHubWriteDenied):
            push_once(auth, marker_path=tmp_path / "marker.json", workspace=tmp_path, runner=runner)
        with pytest.raises(GitHubWriteDenied):
            create_pr_idempotent(auth, workspace=tmp_path, runner=runner)
        assert runner.calls == []
    assert not (tmp_path / "marker.json").exists()