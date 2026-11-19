"""P1-REV-06: an unknown PR list result must never fall through to create."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth
from app.tools.live_git import create_pr_idempotent


class ScriptedShell:
    def __init__(self, *, list_result: tuple[int, str] | None = None, lose_first_create: bool = False) -> None:
        self.list_result = list_result
        self.lose_first_create = lose_first_create
        self.prs: list[dict[str, str]] = []
        self.create_calls = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:3] == ["gh", "pr", "list"]:
            if self.list_result is not None:
                return self.list_result
            return 0, json.dumps(self.prs)
        if argv[:3] == ["gh", "pr", "create"]:
            self.create_calls += 1
            url = f"https://github.com/WaterProMax/HexaGraph/pull/{self.create_calls}"
            self.prs.append({"url": url})
            if self.lose_first_create and self.create_calls == 1:
                return 1, "network lost after create"
            return 0, url
        return 0, ""


def _auth() -> GitHubWriteAuth:
    return GitHubWriteAuth(
        owner="WaterProMax",
        repo="HexaGraph",
        remote="origin",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
    )


def test_list_failure_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(1, "gh: temporarily unavailable"))
    with pytest.raises(GitHubWriteDenied):
        create_pr_idempotent(_auth(), workspace=tmp_path, runner=shell)
    assert shell.create_calls == 0


def test_bad_json_list_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(0, "{not json"))
    with pytest.raises(GitHubWriteDenied):
        create_pr_idempotent(_auth(), workspace=tmp_path, runner=shell)
    assert shell.create_calls == 0


def test_lost_create_response_is_reconciled_without_second_create(tmp_path: Path) -> None:
    shell = ScriptedShell(lose_first_create=True)
    with pytest.raises(GitHubWriteDenied):
        create_pr_idempotent(_auth(), workspace=tmp_path, runner=shell)
    url = create_pr_idempotent(_auth(), workspace=tmp_path, runner=shell)
    assert url == "https://github.com/WaterProMax/HexaGraph/pull/1"
    assert shell.create_calls == 1