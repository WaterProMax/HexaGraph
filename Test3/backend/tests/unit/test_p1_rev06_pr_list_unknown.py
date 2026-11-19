"""P1-REV-06: an unknown PR list result must never fall through to create."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth
from app.schemas.execution_grant import ExecutionGrant
from app.tools.live_git import create_pr_idempotent

RUN_ID = "run-1"
REMOTE_URL = "https://github.com/WaterProMax/HexaGraph.git"


class ScriptedShell:
    def __init__(self, *, list_result: tuple[int, str] | None = None, lose_first_create: bool = False) -> None:
        self.list_result = list_result
        self.lose_first_create = lose_first_create
        self.prs: list[dict[str, str]] = []
        self.create_calls = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:4] == ["git", "symbolic-ref", "--short", "HEAD"]:
            return 0, "feat/p1-demo"
        if argv[:3] == ["git", "remote", "get-url"]:
            return 0, REMOTE_URL
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


def _grant() -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id=RUN_ID,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=["python -m pytest"],
        status="active",
        created_at="2026-11-19T00:00:00+00:00",
    )


def _create(shell: ScriptedShell, tmp_path: Path) -> str:
    return create_pr_idempotent(
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
        workspace=tmp_path,
        runner=shell,
    )


def test_list_failure_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(1, "gh: temporarily unavailable"))
    with pytest.raises(GitHubWriteDenied):
        _create(shell, tmp_path)
    assert shell.create_calls == 0


def test_bad_json_list_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(0, "{not json"))
    with pytest.raises(GitHubWriteDenied):
        _create(shell, tmp_path)
    assert shell.create_calls == 0


def test_lost_create_response_is_reconciled_without_second_create(tmp_path: Path) -> None:
    shell = ScriptedShell(lose_first_create=True)
    with pytest.raises(GitHubWriteDenied):
        _create(shell, tmp_path)
    url = _create(shell, tmp_path)
    assert url == "https://github.com/WaterProMax/HexaGraph/pull/1"
    assert shell.create_calls == 1