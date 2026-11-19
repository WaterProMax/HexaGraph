from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth, parse_github_write_auth
from app.tools.live_git import create_pr_idempotent, push_once

AUTH_TEXT = json.dumps(
    {
        "type": "github_write_grant_v1",
        "verb": "authorize",
        "owner": "WaterProMax",
        "repo": "HexaGraph",
        "remote": "origin",
        "base_branch": "teamwork-001",
        "feature_branch": "feat/p1-demo",
        "allow_push": True,
        "allow_pr_create": True,
        "allow_merge": False,
        "allow_deploy": False,
    }
)


class FakeShell:
    def __init__(self, head: str = "sha-1") -> None:
        self.head = head
        self.calls: list[list[str]] = []
        self.prs: list[dict] = []
        self.push_calls = 0
        self.create_calls = 0

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:2] == ["git", "rev-parse"]:
            return 0, self.head
        if argv[:2] == ["git", "push"]:
            self.push_calls += 1
            return 0, "pushed"
        if argv[:3] == ["gh", "pr", "list"]:
            return 0, json.dumps(self.prs)
        if argv[:3] == ["gh", "pr", "create"]:
            self.create_calls += 1
            url = f"https://github.com/WaterProMax/HexaGraph/pull/{self.create_calls}"
            self.prs.append({"url": url})
            return 0, url
        return 0, ""


@pytest.fixture
def auth() -> GitHubWriteAuth:
    parsed = parse_github_write_auth(AUTH_TEXT)
    assert parsed is not None
    return parsed


def test_parse_authorization_sentence(auth: GitHubWriteAuth) -> None:
    assert auth.owner == "WaterProMax"
    assert auth.repo == "HexaGraph"
    assert auth.remote == "origin"
    assert auth.base_branch == "teamwork-001"
    assert auth.feature_branch == "feat/p1-demo"
    assert parse_github_write_auth(None) is None
    assert parse_github_write_auth("no authorization here") is None
    with pytest.raises(GitHubWriteDenied):
        parse_github_write_auth("授权 github_write：owner=WaterProMax repo=HexaGraph")


def test_push_is_idempotent_for_same_sha(auth: GitHubWriteAuth, tmp_path: Path) -> None:
    shell = FakeShell(head="sha-1")
    marker = tmp_path / "push-marker.json"
    first = push_once(auth, marker_path=marker, workspace=tmp_path, grant_id="G-1", runner=shell)
    second = push_once(auth, marker_path=marker, workspace=tmp_path, grant_id="G-1", runner=shell)
    assert first.pushed is True
    assert second.pushed is False
    assert second.sha == first.sha == "sha-1"
    assert shell.push_calls == 1


def test_create_pr_is_idempotent(auth: GitHubWriteAuth, tmp_path: Path) -> None:
    shell = FakeShell()
    first = create_pr_idempotent(auth, workspace=tmp_path, runner=shell)
    second = create_pr_idempotent(auth, workspace=tmp_path, runner=shell)
    assert first == second == "https://github.com/WaterProMax/HexaGraph/pull/1"
    assert shell.create_calls == 1


def test_push_without_authorization_is_denied(tmp_path: Path) -> None:
    shell = FakeShell()
    with pytest.raises(GitHubWriteDenied):
        push_once(None, marker_path=tmp_path / "marker.json", workspace=tmp_path, runner=shell)
    assert shell.calls == []


def test_push_never_targets_base_branch(auth: GitHubWriteAuth, tmp_path: Path) -> None:
    shell = FakeShell()
    push_once(auth, marker_path=tmp_path / "marker.json", workspace=tmp_path, runner=shell)
    push_argv = next(argv for argv in shell.calls if argv[:2] == ["git", "push"])
    joined = " ".join(push_argv)
    assert "refs/heads/teamwork-001" not in joined
    assert "teamwork-001" not in push_argv


def test_no_merge_or_deploy_helpers() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "tools" / "live_git.py").read_text(encoding="utf-8")
    for forbidden in ("pr merge", "gh merge", "git merge --no-ff origin", "deploy"):
        assert forbidden not in source


def test_concurrent_pr_creation_opens_one(auth: GitHubWriteAuth, tmp_path: Path) -> None:
    shell = FakeShell()

    def call() -> str:
        return create_pr_idempotent(auth, workspace=tmp_path, runner=shell)

    with ThreadPoolExecutor(max_workers=2) as pool:
        urls = list(pool.map(lambda _: call(), range(2)))
    assert len(set(urls)) == 1
    assert shell.create_calls == 1