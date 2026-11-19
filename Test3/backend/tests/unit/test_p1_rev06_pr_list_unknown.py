"""P1-REV-06 / F-11: only a confirmed "no open PR" may create a pull request.

``gh pr list`` has three outcomes: absent (empty list), exists (a URL) and
unknown (non-zero exit, bad JSON, unexpected shape, runner failure).  Unknown
must never fall through to ``gh pr create``.
"""

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
EXISTING_URL = "https://github.com/WaterProMax/HexaGraph/pull/7"


class ScriptedShell:
    def __init__(
        self,
        *,
        list_result: tuple[int, str] | None = None,
        create_result: tuple[int, str] | None = None,
        lose_first_create: bool = False,
        raise_on_list: bool = False,
    ) -> None:
        self.list_result = list_result
        self.create_result = create_result
        self.lose_first_create = lose_first_create
        self.raise_on_list = raise_on_list
        self.prs: list[dict[str, str]] = []
        self.create_calls = 0
        self.list_calls = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:4] == ["git", "symbolic-ref", "--short", "HEAD"]:
            return 0, "feat/p1-demo"
        if argv[:3] == ["git", "remote", "get-url"]:
            return 0, REMOTE_URL
        if argv[:3] == ["gh", "pr", "list"]:
            self.list_calls += 1
            if self.raise_on_list:
                raise RuntimeError("gh list exploded")
            if self.list_result is not None:
                return self.list_result
            return 0, json.dumps(self.prs)
        if argv[:3] == ["gh", "pr", "create"]:
            self.create_calls += 1
            url = f"https://github.com/WaterProMax/HexaGraph/pull/{self.create_calls}"
            self.prs.append({"url": url})
            if self.create_result is not None:
                return self.create_result
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
    with pytest.raises(GitHubWriteDenied) as excinfo:
        _create(shell, tmp_path)
    assert "cannot determine" in str(excinfo.value)
    assert shell.create_calls == 0


def test_bad_json_list_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(0, "{not json"))
    with pytest.raises(GitHubWriteDenied) as excinfo:
        _create(shell, tmp_path)
    assert "cannot determine" in str(excinfo.value)
    assert shell.create_calls == 0


@pytest.mark.parametrize(
    "rows",
    [
        json.dumps({"url": EXISTING_URL}),
        json.dumps(["https://github.com/WaterProMax/HexaGraph/pull/1"]),
        json.dumps([{"url": ""}]),
        json.dumps([{"url": 3}]),
        json.dumps([None]),
        json.dumps([{}]),
    ],
)
def test_unexpected_list_structure_blocks_create(tmp_path: Path, rows: str) -> None:
    shell = ScriptedShell(list_result=(0, rows))
    with pytest.raises(GitHubWriteDenied) as excinfo:
        _create(shell, tmp_path)
    assert "cannot determine" in str(excinfo.value)
    assert shell.create_calls == 0


def test_list_runner_exception_blocks_create(tmp_path: Path) -> None:
    shell = ScriptedShell(raise_on_list=True)
    with pytest.raises(GitHubWriteDenied) as excinfo:
        _create(shell, tmp_path)
    assert "cannot determine" in str(excinfo.value)
    assert shell.create_calls == 0


def test_empty_list_allows_create(tmp_path: Path) -> None:
    shell = ScriptedShell()
    url = _create(shell, tmp_path)
    assert url.endswith("/pull/1")
    assert shell.create_calls == 1


def test_confirmed_existing_pr_is_reused_without_create(tmp_path: Path) -> None:
    shell = ScriptedShell(list_result=(0, json.dumps([{"url": EXISTING_URL}])))
    url = _create(shell, tmp_path)
    assert url == EXISTING_URL
    assert shell.create_calls == 0


def test_lost_create_response_is_reconciled_without_second_create(tmp_path: Path) -> None:
    shell = ScriptedShell(lose_first_create=True)
    with pytest.raises(GitHubWriteDenied):
        _create(shell, tmp_path)
    url = _create(shell, tmp_path)
    assert url == "https://github.com/WaterProMax/HexaGraph/pull/1"
    assert shell.create_calls == 1


def test_create_success_without_url_is_reconciled_on_retry(tmp_path: Path) -> None:
    shell = ScriptedShell(create_result=(0, "ok"))
    with pytest.raises(GitHubWriteDenied):
        _create(shell, tmp_path)
    url = _create(shell, tmp_path)
    assert url == "https://github.com/WaterProMax/HexaGraph/pull/1"
    assert shell.create_calls == 1