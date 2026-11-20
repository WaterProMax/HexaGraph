"""F-06 closeout: the container runs on a copy; only write_set changes land.

No Docker is needed.  ``run_isolated`` is replaced with a fake that mutates the
copy it receives, while preflight, staging, scope filtering and host write-back
use the real implementation.  Escape targets live under ``tmp_path`` only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.errors import WriteDenied
from app.execution import evidence as evidence_store
from app.execution.isolated import execute_task_granted
from app.execution.isolation import IsolationPreflight
from app.execution.workspace_scope import (
    ScopedChange,
    _write_regular,
    apply_changes,
    cleanup_worktree_copy,
    collect_changes,
    prepare_worktree_copy,
)
from app.schemas.execution_grant import ExecutionGrant

RUN_ID = "run-1"


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
        allowed_tool_refs=["python -c"],
        created_at="2026-11-19T00:00:00+00:00",
    )


def _available() -> IsolationPreflight:
    return IsolationPreflight(available=True, backend="docker", reason="", details={"image": "test-image"})


async def _run(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    *,
    write_set: list[str] | None,
    exit_code: int = 0,
):
    captured: list[Path] = []
    created: list[Path] = []
    real_create = evidence_store.create_evidence_dir

    def tracking_create() -> Path:
        directory = real_create()
        created.append(directory)
        return directory

    monkeypatch.setattr("app.execution.isolated.preflight_isolation", _available)
    monkeypatch.setattr("app.execution.evidence.create_evidence_dir", tracking_create)

    async def fake_run(argv, *, cwd, timeout, env_allow=None, output_limit=None):
        captured.append(Path(cwd))
        mutate(Path(cwd))
        return {
            "exit_code": exit_code,
            "output": "pytest started\n",
            "timeout": False,
            "truncated": False,
            "backend": "docker",
            "image": "test-image",
        }

    monkeypatch.setattr("app.execution.isolated.run_isolated", fake_run)
    try:
        result = await execute_task_granted(
            RUN_ID,
            "T-01",
            _grant(),
            isolation_root=root,
            writes=[],
            test_command=["python", "-c", "print('ok')"],
            write_set=write_set,
            tool_refs=["python -c"],
            whitelist=["python -c"],
        )
    finally:
        for directory in created:
            evidence_store.cleanup_evidence_dir(directory)
    return result, captured


@pytest.mark.asyncio
async def test_in_scope_change_is_applied_and_out_of_scope_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "allowed.txt").write_text("old", encoding="utf-8")
    (root / "keep.txt").write_text("keep", encoding="utf-8")

    def mutate(work: Path) -> None:
        (work / "allowed.txt").write_text("new", encoding="utf-8")
        (work / "keep.txt").write_text("hacked", encoding="utf-8")
        (work / "evil.txt").write_text("evil", encoding="utf-8")

    result, captured = await _run(root, monkeypatch, mutate, write_set=["allowed.txt"])
    assert captured and captured[0] != root
    assert not captured[0].exists(), "temporary copy must be cleaned up"
    assert (root / "allowed.txt").read_text(encoding="utf-8") == "new"
    assert (root / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (root / "evil.txt").exists()
    scope = result.evidence["scope"]
    assert scope["applied"] == ["allowed.txt"]
    reasons = {item["path"]: item["reason"] for item in scope["discarded"]}
    assert reasons["keep.txt"] == "outside-write-set"
    assert reasons["evil.txt"] == "outside-write-set"


@pytest.mark.asyncio
async def test_symlink_changes_are_not_written_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "allowed.txt").write_text("old", encoding="utf-8")
    outside = tmp_path / "outside-sentinel.txt"
    outside.write_text("sentinel", encoding="utf-8")

    def mutate(work: Path) -> None:
        (work / "allowed.txt").unlink()
        (work / "allowed.txt").symlink_to(outside)
        (work / "added-link.txt").symlink_to(outside)

    result, _captured = await _run(root, monkeypatch, mutate, write_set=["allowed.txt", "added-link.txt"])
    assert outside.read_text(encoding="utf-8") == "sentinel"
    assert (root / "allowed.txt").is_file()
    assert not (root / "allowed.txt").is_symlink()
    assert (root / "allowed.txt").read_text(encoding="utf-8") == "old"
    assert not (root / "added-link.txt").exists()
    reasons = {item["path"]: item["reason"] for item in result.evidence["scope"]["discarded"]}
    assert reasons["allowed.txt"] == "symlink"
    assert reasons["added-link.txt"] == "symlink"


@pytest.mark.asyncio
async def test_in_scope_writeback_does_not_rewrite_out_of_scope_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    allowed = root / "allowed.txt"
    evil = root / "evil.txt"
    allowed.write_text("shared-original", encoding="utf-8")
    os.link(allowed, evil)
    original_inode = os.stat(evil).st_ino
    assert os.stat(allowed).st_ino == original_inode

    def mutate(work: Path) -> None:
        (work / "allowed.txt").write_text("in-scope-new-content", encoding="utf-8")

    result, _captured = await _run(root, monkeypatch, mutate, write_set=["allowed.txt"])
    assert result.evidence["scope"]["applied"] == ["allowed.txt"]
    assert allowed.read_text(encoding="utf-8") == "in-scope-new-content"
    assert evil.read_text(encoding="utf-8") == "shared-original"
    assert os.stat(evil).st_ino == original_inode
    assert os.stat(allowed).st_ino != os.stat(evil).st_ino
    assert os.stat(evil).st_nlink == 1


def test_write_regular_refuses_host_symlink_target(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel", encoding="utf-8")
    (root / "allowed.txt").symlink_to(outside)
    with pytest.raises(WriteDenied):
        _write_regular(root, "allowed.txt", b"new")
    assert outside.read_text(encoding="utf-8") == "sentinel"
    assert (root / "allowed.txt").is_symlink()


@pytest.mark.asyncio
async def test_deletions_follow_write_set_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "allowed.txt").write_text("a", encoding="utf-8")
    (root / "keep.txt").write_text("k", encoding="utf-8")

    def mutate(work: Path) -> None:
        (work / "allowed.txt").unlink()
        (work / "keep.txt").unlink()

    result, _captured = await _run(root, monkeypatch, mutate, write_set=["allowed.txt"])
    assert not (root / "allowed.txt").exists()
    assert (root / "keep.txt").read_text(encoding="utf-8") == "k"
    assert result.evidence["scope"]["applied"] == ["allowed.txt"]
    assert {item["path"] for item in result.evidence["scope"]["discarded"]} == {"keep.txt"}


@pytest.mark.asyncio
async def test_container_changes_are_discarded_when_write_set_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "allowed.txt").write_text("old", encoding="utf-8")

    def mutate(work: Path) -> None:
        (work / "allowed.txt").write_text("new", encoding="utf-8")
        (work / "extra.txt").write_text("x", encoding="utf-8")

    result, _captured = await _run(root, monkeypatch, mutate, write_set=None)
    assert (root / "allowed.txt").read_text(encoding="utf-8") == "old"
    assert not (root / "extra.txt").exists()
    assert result.evidence["scope"]["applied"] == []
    assert len(result.evidence["scope"]["discarded"]) == 2


def test_scope_copy_collects_added_modified_deleted(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "modified.txt").write_text("v1", encoding="utf-8")
    (root / "deleted.txt").write_text("gone", encoding="utf-8")
    copy = prepare_worktree_copy(root)
    try:
        (copy.work / "modified.txt").write_text("v2", encoding="utf-8")
        (copy.work / "deleted.txt").unlink()
        (copy.work / "added.txt").write_text("new", encoding="utf-8")
        changes = {change.path: change.kind for change in collect_changes(copy)}
        assert changes == {"modified.txt": "modified", "deleted.txt": "deleted", "added.txt": "added"}
    finally:
        cleanup_worktree_copy(copy)


def test_apply_rejects_unsafe_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    copy = prepare_worktree_copy(root)
    try:
        with pytest.raises(WriteDenied):
            apply_changes(copy, [ScopedChange(path="../escape.txt", kind="added")], ["escape.txt"])
    finally:
        cleanup_worktree_copy(copy)