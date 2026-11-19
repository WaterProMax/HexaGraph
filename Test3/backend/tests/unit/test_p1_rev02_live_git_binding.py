"""P1-REV-02: git adapter must refuse protected refs and unauthenticated commits.

Offline only: fake runner records argv; no git remote is contacted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth
from app.tools.live_git import commit_all, push_once


class RecordingShell:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[:2] == ["git", "rev-parse"]:
            return 0, "sha-1"
        return 0, "ok"


def _auth(feature_branch: str = "main", base_branch: str = "teamwork-001") -> GitHubWriteAuth:
    return GitHubWriteAuth(
        owner="WaterProMax",
        repo="HexaGraph",
        remote="origin",
        base_branch=base_branch,
        feature_branch=feature_branch,
    )


def test_push_to_main_is_rejected(tmp_path: Path) -> None:
    shell = RecordingShell()
    try:
        with pytest.raises(GitHubWriteDenied):
            push_once(_auth("main"), marker_path=tmp_path / "marker.json", workspace=tmp_path, runner=shell)
    finally:
        pass
    push_argv = [argv for argv in shell.calls if argv[:2] == ["git", "push"]]
    assert push_argv == []
    assert not any("HEAD:refs/heads/main" in argv for argv in shell.calls)


def test_unauthenticated_commit_does_not_stage_everything(tmp_path: Path) -> None:
    shell = RecordingShell()
    with pytest.raises(Exception):
        commit_all(tmp_path, "no authorization", runner=shell)
    assert not any(argv[:3] == ["git", "add", "-A"] for argv in shell.calls)