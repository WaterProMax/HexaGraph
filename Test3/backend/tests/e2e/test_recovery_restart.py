from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.orchestrator.transition import apply_transition
from app.workspace.gitops import init_repo_sync
from tests.e2e.test_must_fixes import _bench, _card, _ready_run


def _recovery_entries(data_dir: Path) -> list[dict]:
    path = data_dir / "recovery.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _start_running_task(bench, run) -> str:
    """把唯一任务推进到 running，并造出 repo，模拟“执行中被杀”。"""
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    apply_transition(run.tasks["T-01"], "scheduled")
    bench.emit(
        run,
        "task.state_changed",
        "T-01",
        {"code": "T-01", "event": "scheduled", "from": "ready", "to": "running"},
    )
    return run.id


def test_project_survives_restart_without_any_run(tmp_path: Path) -> None:
    """只建项目、还没建运行就重启，项目不能丢。"""
    bench, _ = _bench(tmp_path)
    project = bench.create_project("proj-only")
    assert (tmp_path / "projects.json").exists()

    bench2, _ = _bench(tmp_path)
    assert project["id"] in bench2.projects
    assert bench2.projects[project["id"]]["name"] == "proj-only"


@pytest.mark.asyncio
async def test_running_task_recovery_emits_event(tmp_path: Path) -> None:
    """恢复动作必须在事件流里留痕（原来只改状态、不写事件）。"""
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    run_id = _start_running_task(bench, run)

    bench2, _ = _bench(tmp_path)
    restored = bench2.runs[run_id]
    assert restored.tasks["T-01"]["state"] == "ready"

    recovered = [
        event
        for event in restored.events
        if event["kind"] == "task.state_changed" and (event.get("payload") or {}).get("event") == "interrupted"
    ]
    assert len(recovered) == 1
    assert recovered[0]["payload"]["reason"] == "recover"
    assert recovered[0]["payload"]["from"] == "running"
    assert recovered[0]["payload"]["to"] == "ready"


@pytest.mark.asyncio
async def test_recovery_is_idempotent_across_two_restarts(tmp_path: Path) -> None:
    """连续两次重启不重复恢复、不重复执行。"""
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    run_id = _start_running_task(bench, run)

    bench2, _ = _bench(tmp_path)
    bench3, _ = _bench(tmp_path)

    restored = bench3.runs[run_id]
    assert restored.tasks["T-01"]["state"] == "ready"
    repeats = [
        event
        for event in restored.events
        if event["kind"] == "task.state_changed" and (event.get("payload") or {}).get("event") == "interrupted"
    ]
    assert len(repeats) == 1


@pytest.mark.asyncio
async def test_corrupt_event_line_is_recorded(tmp_path: Path) -> None:
    """被截断/写坏的 JSONL 行不能静默丢，必须留下可读记录。"""
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    bench.emit(run, "stage.changed", "1", {"event": "x"})
    events = bench.data_dir / "runs" / run.id / "events.jsonl"
    with events.open("a", encoding="utf-8") as handle:
        handle.write("{broken-line\n")

    bench2, _ = _bench(tmp_path)
    assert run.id in bench2.runs
    reasons = [entry["reason"] for entry in _recovery_entries(tmp_path)]
    assert any(reason.startswith("events_corrupt_line:") for reason in reasons)


@pytest.mark.asyncio
async def test_snapshot_event_seq_gap_is_recorded(tmp_path: Path) -> None:
    """snapshot 的 event_seq 比实际 JSONL 多出事件时，必须记录丢失量。"""
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    for index in range(3):
        bench.emit(run, "stage.changed", str(index), {"i": index})
    bench._persist_snapshot(run)

    snap = bench.data_dir / "runs" / run.id / "snapshot.json"
    data = json.loads(snap.read_text(encoding="utf-8"))
    data["event_seq"] = int(data["event_seq"]) + 2
    snap.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bench2, _ = _bench(tmp_path)
    assert run.id in bench2.runs
    reasons = [entry["reason"] for entry in _recovery_entries(tmp_path)]
    assert any(reason.startswith("events_missing:") for reason in reasons)


@pytest.mark.asyncio
async def test_seq_is_not_reused_after_missing_event(tmp_path: Path) -> None:
    """JSONL 缺行后新事件不能复用已有 seq，否则 SSE 续传会错乱。"""
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    for index in range(3):
        bench.emit(run, "stage.changed", str(index), {"i": index})

    events = bench.data_dir / "runs" / run.id / "events.jsonl"
    lines = [line for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
    events.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    bench2, _ = _bench(tmp_path)
    restored = bench2.runs[run.id]
    before = [event["seq"] for event in restored.events]

    bench2.emit(restored, "stage.changed", "9", {"i": 9})
    seqs = [event["seq"] for event in restored.events]

    assert len(seqs) == len(set(seqs))
    assert seqs[-1] > max(before)


@pytest.mark.asyncio
async def test_schedule_loop_error_is_recorded(tmp_path: Path, monkeypatch) -> None:
    """调度异常必须可查，同时保持 continue 的降级语义。"""
    bench, _ = _bench(tmp_path)
    _ready_run(bench, _card())

    async def _boom(_run) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(bench, "schedule_once", _boom)
    bench.schedule_interval = 0.01
    bench.start_loop()
    try:
        await asyncio.sleep(0.2)
    finally:
        await bench.stop_loop()

    reasons = [entry["reason"] for entry in _recovery_entries(tmp_path)]
    assert any(reason.startswith("schedule_loop_error:") for reason in reasons)
