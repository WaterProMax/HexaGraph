"""P1-REV-03 / F-07: evidence files must be written without following links.

These tests never depend on Docker: the isolation boundary is replaced by an
explicit fake result, while the filesystem writer under test stays real.  Every
escape target is a temporary directory; nothing touches user data.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from app.errors import EvidenceWriteFailed
from app.execution import evidence as evidence_mod
from app.execution.evidence import cleanup_evidence_dir, create_evidence_dir, write_evidence_file
from app.execution.isolated import execute_task_granted
from app.execution.isolation import IsolationPreflight
from app.schemas.execution_grant import ExecutionGrant


def _grant(tool_refs: list[str] | None = None) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id="run-1",
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=list(tool_refs or ["python -c"]),
        created_at="2026-11-19T00:00:00+00:00",
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def _fake_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only the container boundary; the evidence writer stays real."""
    monkeypatch.setattr(
        "app.execution.isolated.preflight_isolation",
        lambda: IsolationPreflight(available=True, backend="docker", reason="", details={"image": "test-image"}),
    )

    async def fake_run(argv, *, cwd, timeout, env_allow=None, output_limit=None):
        return {
            "exit_code": 0,
            "output": "fake-stdout\nfake-stderr\n",
            "timeout": False,
            "truncated": False,
            "backend": "docker",
            "image": "test-image",
        }

    monkeypatch.setattr("app.execution.isolated.run_isolated", fake_run)


def test_evidence_dir_and_files_are_private(tmp_path: Path) -> None:
    directory = create_evidence_dir()
    try:
        assert _mode(directory) == 0o700
        target = write_evidence_file(directory, "T-01.log", "hello evidence")
        assert target.read_text(encoding="utf-8") == "hello evidence"
        assert _mode(target) == 0o600
        assert (target.parent / "T-01.log").exists()
    finally:
        cleanup_evidence_dir(directory)
    assert not directory.exists()


def test_evidence_directories_are_unpredictable_per_task(tmp_path: Path) -> None:
    first = create_evidence_dir()
    second = create_evidence_dir()
    try:
        assert first != second
        assert first.name.startswith("test3-evidence-")
        assert second.name.startswith("test3-evidence-")
        assert first.resolve().parent == second.resolve().parent
        assert _mode(first) == _mode(second) == 0o700
    finally:
        cleanup_evidence_dir(first)
        cleanup_evidence_dir(second)


def test_existing_file_symlink_is_refused_and_target_untouched(tmp_path: Path) -> None:
    directory = create_evidence_dir()
    outside = tmp_path / "sentinel.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    os.chmod(outside, 0o640)
    before = (outside.read_text(encoding="utf-8"), _mode(outside))
    (directory / "T-01.json").symlink_to(outside)
    try:
        with pytest.raises(EvidenceWriteFailed):
            write_evidence_file(directory, "T-01.json", "payload")
        assert os.path.islink(directory / "T-01.json")
        assert (outside.read_text(encoding="utf-8"), _mode(outside)) == before
    finally:
        cleanup_evidence_dir(directory)
    assert outside.read_text(encoding="utf-8") == "outside-secret"


def test_directory_symlink_redirect_is_refused(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside-evidence"
    outside_dir.mkdir()
    os.chmod(outside_dir, 0o755)
    link = tmp_path / "linked-evidence"
    link.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(EvidenceWriteFailed):
        write_evidence_file(link, "T-01.json", "payload")
    assert list(outside_dir.iterdir()) == []


def test_symlink_swap_at_open_time_is_not_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic TOCTOU: the link appears after the directory fd is open."""
    directory = create_evidence_dir()
    outside = tmp_path / "swap-sentinel.txt"
    outside.write_text("swap-secret", encoding="utf-8")
    original = evidence_mod._open_new_file
    calls: list[str] = []

    def swapping_open(dir_fd: int, name: str) -> int:
        calls.append(name)
        (directory / name).symlink_to(outside)
        return original(dir_fd, name)

    monkeypatch.setattr(evidence_mod, "_open_new_file", swapping_open)
    try:
        with pytest.raises(EvidenceWriteFailed):
            write_evidence_file(directory, "swap.json", "payload")
        assert calls == ["swap.json"]
        assert outside.read_text(encoding="utf-8") == "swap-secret"
        assert os.path.islink(directory / "swap.json")
    finally:
        cleanup_evidence_dir(directory)


def test_non_regular_file_is_refused_without_hanging(tmp_path: Path) -> None:
    directory = create_evidence_dir()
    fifo = directory / "pipe.json"
    os.mkfifo(fifo)
    outcome: dict[str, object] = {}

    def attempt() -> None:
        try:
            write_evidence_file(directory, "pipe.json", "payload")
        except EvidenceWriteFailed as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(3)
    try:
        assert not worker.is_alive(), "evidence write blocked on a non-regular file"
        assert isinstance(outcome.get("error"), EvidenceWriteFailed)
        assert stat.S_ISFIFO(os.lstat(fifo).st_mode)
    finally:
        cleanup_evidence_dir(directory)


def test_failed_write_never_returns_success_and_cleanup_is_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "cleanup-sentinel.txt"
    outside.write_text("keep-me", encoding="utf-8")
    directory = create_evidence_dir()
    write_evidence_file(directory, "ok.log", "log")
    original = evidence_mod._open_new_file

    def failing_open(dir_fd: int, name: str) -> int:
        if name.endswith(".json"):
            raise OSError("simulated evidence write failure")
        return original(dir_fd, name)

    monkeypatch.setattr(evidence_mod, "_open_new_file", failing_open)
    try:
        with pytest.raises(EvidenceWriteFailed):
            write_evidence_file(directory, "T-01.json", "{}")
        cleanup_evidence_dir(directory)
        assert not directory.exists()
        assert outside.read_text(encoding="utf-8") == "keep-me"
    finally:
        monkeypatch.undo()
        cleanup_evidence_dir(directory)


@pytest.mark.asyncio
async def test_worker_writes_evidence_through_safe_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_isolation(monkeypatch)
    root = tmp_path / "wt"
    root.mkdir()
    result = await execute_task_granted(
        "run-1",
        "T-01",
        _grant(),
        isolation_root=root,
        writes=[],
        test_command=["python", "-c", "print('ok')"],
        tool_refs=["python -c"],
        whitelist=["python -c"],
    )
    log_path = Path(result.log_path)
    evidence_path = Path(result.evidence_path)
    assert log_path.is_file()
    assert evidence_path.is_file()
    assert _mode(log_path.parent) == 0o700
    assert _mode(log_path) == 0o600
    assert _mode(evidence_path) == 0o600
    assert log_path.read_text(encoding="utf-8") == "fake-stdout\nfake-stderr\n"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["commands"][0]["output"] == "fake-stdout\nfake-stderr\n"
    assert evidence["isolation"]["backend"] == "docker"
    assert evidence["ok"] is True
    cleanup_evidence_dir(evidence_path.parent)


@pytest.mark.asyncio
async def test_worker_raises_instead_of_returning_success_when_evidence_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_isolation(monkeypatch)
    outside = tmp_path / "worker-sentinel.txt"
    outside.write_text("worker-secret", encoding="utf-8")
    created: list[Path] = []
    real_create = evidence_mod.create_evidence_dir

    def tracking_create() -> Path:
        directory = real_create()
        created.append(directory)
        return directory

    monkeypatch.setattr(evidence_mod, "create_evidence_dir", tracking_create)
    original = evidence_mod._open_new_file

    def failing_open(dir_fd: int, name: str) -> int:
        if name.endswith(".json"):
            raise OSError("simulated json failure")
        return original(dir_fd, name)

    monkeypatch.setattr(evidence_mod, "_open_new_file", failing_open)
    root = tmp_path / "wt"
    root.mkdir()
    with pytest.raises(EvidenceWriteFailed):
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(),
            isolation_root=root,
            writes=[],
            test_command=["python", "-c", "print('ok')"],
            tool_refs=["python -c"],
            whitelist=["python -c"],
        )
    assert created, "worker never reached the evidence writer"
    assert all(not directory.exists() for directory in created)
    assert outside.read_text(encoding="utf-8") == "worker-secret"