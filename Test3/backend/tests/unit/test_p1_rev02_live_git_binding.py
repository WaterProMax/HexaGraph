"""P1-REV-02 / F-10: git writes must bind auth, an active grant and workspace state.

Offline only: fake runners record argv, and the one real-git test uses a local
bare repository and never contacts a remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth
from app.schemas.execution_grant import ExecutionGrant
from app.tools.live_git import commit_files, create_pr_idempotent, push_once

RUN_ID = "run-1"
REMOTE_URL = "https://github.com/WaterProMax/HexaGraph.git"


def _auth(
    *,
    feature_branch: str = "feat/p1-demo",
    base_branch: str = "teamwork-001",
    owner: str = "WaterProMax",
    repo: str = "HexaGraph",
    remote: str = "origin",
) -> GitHubWriteAuth:
    return GitHubWriteAuth(
        owner=owner,
        repo=repo,
        remote=remote,
        base_branch=base_branch,
        feature_branch=feature_branch,
    )


def _grant(
    *,
    feature_branch: str = "feat/p1-demo",
    base_branch: str = "teamwork-001",
    owner: str = "WaterProMax",
    repo: str = "HexaGraph",
    status: str = "active",
    run_id: str = RUN_ID,
) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner=owner,
        repo_name=repo,
        base_branch=base_branch,
        feature_branch=feature_branch,
        allowed_tool_refs=["python -m pytest"],
        status=status,  # type: ignore[arg-type]
        created_at="2026-11-19T00:00:00+00:00",
    )


class StateShell:
    """Fake runner that answers workspace-state queries explicitly."""

    def __init__(
        self,
        *,
        branch: str = "feat/p1-demo",
        remote_url: str = REMOTE_URL,
        head: str = "sha-1",
        prs: list[dict] | None = None,
    ) -> None:
        self.branch = branch
        self.remote_url = remote_url
        self.head = head
        self.prs = list(prs or [])
        self.calls: list[list[str]] = []
        self.push_calls = 0
        self.create_calls = 0

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:4] == ["git", "symbolic-ref", "--short", "HEAD"]:
            return 0, self.branch
        if argv[:3] == ["git", "remote", "get-url"]:
            return 0, self.remote_url
        if argv[:3] == ["git", "rev-parse", "HEAD"] or argv[:2] == ["git", "rev-parse"]:
            return 0, self.head
        if argv[:2] == ["git", "push"]:
            self.push_calls += 1
            return 0, "pushed"
        if argv[:3] == ["gh", "pr", "list"]:
            return 0, "[]"
        if argv[:3] == ["gh", "pr", "create"]:
            self.create_calls += 1
            url = f"https://github.com/WaterProMax/HexaGraph/pull/{self.create_calls}"
            self.prs.append({"url": url})
            return 0, url
        return 0, ""


class ExplodingShell:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        raise AssertionError(f"write path must not run: {argv}")


def _mutating_calls(shell) -> list[list[str]]:
    return [
        argv
        for argv in shell.calls
        if argv[:2] == ["git", "push"]
        or argv[:3] == ["git", "add", "--"]
        or argv[:3] == ["git", "add", "-A"]
        or argv[:3] == ["gh", "pr", "create"]
    ]


@pytest.mark.parametrize("branch", ["main", "master"])
def test_push_to_protected_branch_is_rejected(tmp_path: Path, branch: str) -> None:
    shell = StateShell(branch=branch)
    with pytest.raises(GitHubWriteDenied):
        push_once(
            auth=_auth(feature_branch=branch),
            grant=_grant(feature_branch=branch),
            run_id=RUN_ID,
            marker_path=tmp_path / "marker.json",
            workspace=tmp_path,
            runner=shell,
        )
    assert shell.push_calls == 0
    assert not any("HEAD:refs/heads/main" in argv or "HEAD:refs/heads/master" in argv for argv in shell.calls)


def test_push_to_base_branch_is_rejected(tmp_path: Path) -> None:
    shell = StateShell(branch="teamwork-001")
    with pytest.raises(GitHubWriteDenied):
        push_once(
            auth=_auth(feature_branch="teamwork-001"),
            grant=_grant(feature_branch="teamwork-001"),
            run_id=RUN_ID,
            marker_path=tmp_path / "marker.json",
            workspace=tmp_path,
            runner=shell,
        )
    assert shell.push_calls == 0


def test_workspace_branch_mismatch_blocks_commit_and_push(tmp_path: Path) -> None:
    shell = StateShell(branch="feat/somewhere-else")
    auth, grant = _auth(), _grant()
    with pytest.raises(GitHubWriteDenied):
        commit_files(tmp_path, ["a.txt"], "msg", auth=auth, grant=grant, run_id=RUN_ID, runner=shell)
    with pytest.raises(GitHubWriteDenied):
        push_once(auth=auth, grant=grant, run_id=RUN_ID, marker_path=tmp_path / "m.json", workspace=tmp_path, runner=shell)
    assert _mutating_calls(shell) == []


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/OtherOwner/HexaGraph.git",
        "https://github.com/WaterProMax/OtherRepo.git",
        "git@github.com:OtherOwner/HexaGraph.git",
        "https://gitlab.com/WaterProMax/HexaGraph.git",
        "not-a-url",
    ],
)
def test_remote_url_mismatch_blocks_commit_and_push(tmp_path: Path, remote_url: str) -> None:
    shell = StateShell(remote_url=remote_url)
    auth, grant = _auth(), _grant()
    with pytest.raises(GitHubWriteDenied):
        commit_files(tmp_path, ["a.txt"], "msg", auth=auth, grant=grant, run_id=RUN_ID, runner=shell)
    with pytest.raises(GitHubWriteDenied):
        push_once(auth=auth, grant=grant, run_id=RUN_ID, marker_path=tmp_path / "m.json", workspace=tmp_path, runner=shell)
    assert _mutating_calls(shell) == []


def test_commit_without_authorization_is_rejected(tmp_path: Path) -> None:
    shell = ExplodingShell()
    with pytest.raises(GitHubWriteDenied):
        commit_files(tmp_path, ["a.txt"], "msg", auth=None, grant=None, run_id=RUN_ID, runner=shell)
    assert shell.calls == []


@pytest.mark.parametrize(
    "grant",
    [
        _grant(status="revoked"),
        _grant(status="consumed"),
        _grant(owner="OtherOwner"),
        _grant(repo="OtherRepo"),
        _grant(feature_branch="feat/other"),
        _grant(base_branch="main"),
        _grant(run_id="other-run"),
    ],
)
def test_inactive_or_mismatched_grant_blocks_commit(tmp_path: Path, grant: ExecutionGrant) -> None:
    shell = ExplodingShell()
    with pytest.raises(GitHubWriteDenied):
        commit_files(tmp_path, ["a.txt"], "msg", auth=_auth(), grant=grant, run_id=RUN_ID, runner=shell)
    assert shell.calls == []


def test_grant_id_is_not_optional_marker_metadata(tmp_path: Path) -> None:
    shell = StateShell()
    first = push_once(
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
        marker_path=tmp_path / "marker.json",
        workspace=tmp_path,
        runner=shell,
    )
    assert first.pushed is True
    marker = (tmp_path / "marker.json").read_text(encoding="utf-8")
    assert '"grant_id": "G-1"' in marker
    second = push_once(
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
        marker_path=tmp_path / "marker.json",
        workspace=tmp_path,
        runner=shell,
    )
    assert second.pushed is False
    assert shell.push_calls == 1


@pytest.mark.parametrize(
    "paths",
    [
        ["../escape.txt"],
        ["/etc/passwd"],
        [""],
        ["a.txt", "*.py"],
        ["a.txt", "-f"],
    ],
)
def test_commit_rejects_unsafe_or_ambiguous_paths(tmp_path: Path, paths: list[str]) -> None:
    shell = StateShell()
    with pytest.raises(GitHubWriteDenied):
        commit_files(tmp_path, paths, "msg", auth=_auth(), grant=_grant(), run_id=RUN_ID, runner=shell)
    assert _mutating_calls(shell) == []


def test_commit_uses_explicit_file_list_and_no_force(tmp_path: Path) -> None:
    workspace = _real_repo(tmp_path)
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    sha = commit_files(
        workspace,
        ["a.txt"],
        "commit a only",
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
    )
    assert sha
    names = subprocess.run(
        ["git", "show", "--name-only", "--format=", sha],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "a.txt" in names
    assert "b.txt" not in names
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "b.txt" in status


def test_push_success_uses_only_authorized_feature_ref(tmp_path: Path) -> None:
    shell = StateShell()
    result = push_once(
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
        marker_path=tmp_path / "marker.json",
        workspace=tmp_path,
        runner=shell,
    )
    assert result.pushed is True
    push = next(argv for argv in shell.calls if argv[:2] == ["git", "push"])
    assert push == ["git", "push", "origin", "HEAD:refs/heads/feat/p1-demo"]
    assert "--force" not in push
    assert "teamwork-001" not in push


def test_gh_calls_carry_explicit_repo(tmp_path: Path) -> None:
    shell = StateShell()
    url = create_pr_idempotent(
        auth=_auth(),
        grant=_grant(),
        run_id=RUN_ID,
        workspace=tmp_path,
        runner=shell,
    )
    assert url.endswith("/pull/1")
    list_argv = next(argv for argv in shell.calls if argv[:3] == ["gh", "pr", "list"])
    create_argv = next(argv for argv in shell.calls if argv[:3] == ["gh", "pr", "create"])
    for argv in (list_argv, create_argv):
        assert "--repo" in argv
        assert argv[argv.index("--repo") + 1] == "WaterProMax/HexaGraph"


def _real_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    workspace = tmp_path / "workspace"
    subprocess.run(["git", "clone", str(origin), str(workspace)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feat/p1-demo"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", REMOTE_URL],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    return workspace