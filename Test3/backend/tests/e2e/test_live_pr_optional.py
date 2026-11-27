"""Optional live PR check: production adapter, fake runner, no network.

Default ``pytest -m 'not live'`` never selects this test.  Even when selected it
only parses a structured authorization from the environment; without one it
skips.  All git/gh calls go through an in-memory runner, so a pasted fixture
authorization can never write to a real GitHub remote.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth, parse_github_write_auth
from app.schemas.execution_grant import ExecutionGrant
from app.tools.live_git import create_pr_idempotent, push_once

RUN_ID = "run-1"
FAKE_PR_URL = "https://github.com/example-owner/example-repo/pull/42"


class FakeRunner:
    """Answers local git state and fake gh output; never touches a network."""

    def __init__(self, auth: GitHubWriteAuth) -> None:
        self.auth = auth
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:4] == ["git", "symbolic-ref", "--short", "HEAD"]:
            return 0, self.auth.feature_branch
        if argv[:3] == ["git", "remote", "get-url"]:
            return 0, f"https://github.com/{self.auth.owner}/{self.auth.repo}.git"
        if argv[:2] == ["git", "rev-parse"]:
            return 0, "sha-fixture"
        if argv[:2] == ["git", "push"]:
            return 0, "pushed"
        if argv[:3] == ["gh", "pr", "list"]:
            return 0, "[]"
        if argv[:3] == ["gh", "pr", "create"]:
            return 0, FAKE_PR_URL
        return 0, ""


@pytest.mark.live
def test_live_pr_optional(tmp_path: Path) -> None:
    raw = os.environ.get("TEST3_GITHUB_WRITE_AUTH")
    try:
        auth = parse_github_write_auth(raw)
    except GitHubWriteDenied:
        auth = None
    if auth is None:
        pytest.skip("missing structured github_write authorization")
    assert auth.feature_branch != auth.base_branch

    grant = ExecutionGrant(
        grant_id="G-live-fixture",
        run_id=RUN_ID,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "fixture"},
        repo_remote=auth.remote,
        repo_owner=auth.owner,
        repo_name=auth.repo,
        base_branch=auth.base_branch,
        feature_branch=auth.feature_branch,
        allowed_tool_refs=["python -m pytest"],
        status="active",
        created_at="2026-11-19T00:00:00+00:00",
    )
    runner = FakeRunner(auth)
    pushed = push_once(
        auth=auth,
        grant=grant,
        run_id=RUN_ID,
        marker_path=tmp_path / "marker.json",
        workspace=tmp_path,
        runner=runner,
    )
    assert pushed.pushed is True
    assert pushed.feature_branch == auth.feature_branch

    url = create_pr_idempotent(auth=auth, grant=grant, run_id=RUN_ID, workspace=tmp_path, runner=runner)
    assert url == FAKE_PR_URL

    push_argv = next(argv for argv in runner.calls if argv[:2] == ["git", "push"])
    assert f"HEAD:refs/heads/{auth.feature_branch}" in push_argv
    assert auth.base_branch not in push_argv
    assert "--force" not in push_argv
    for kind in ("list", "create"):
        argv = next(item for item in runner.calls if item[:3] == ["gh", "pr", kind])
        assert argv[argv.index("--repo") + 1] == f"{auth.owner}/{auth.repo}"
    marker = json.loads((tmp_path / "marker.json").read_text(encoding="utf-8"))
    assert marker["grant_id"] == grant.grant_id