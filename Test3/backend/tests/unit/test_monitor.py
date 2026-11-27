from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.monitor import build_monitor_snapshot
from app.services.runtime import RunState, Workbench
from app.settings import load_models, load_roles


def _task(state: str, role: str, parent: str, **extra):
    card = {
        "code": extra.pop("code", "T"),
        "title": extra.pop("title", "任务"),
        "role": role,
        "parent": parent,
        "module": parent,
        "points": 1,
    }
    task = {
        "state": state,
        "card": card,
        "revision": 1,
        "tokens_used": 0,
        "repair_rounds": 0,
        "evidence": [],
        "review_issues": [],
    }
    task.update(extra)
    return task


def _run() -> RunState:
    run = RunState(id="run-1", project_id="proj-1", idea="demo")
    run.engine.current = "7"
    run.tokens_used = 180
    run.artifacts["plan"] = {
        "work_packages": [
            {"code": "W1", "title": "登录", "module": "M1"},
            {"code": "W2", "title": "验收", "module": "M2"},
        ]
    }
    run.tasks = {
        "W1-01": _task("done", "coder", "W1", code="W1-01", title="实现登录", tokens_used=100, repair_rounds=1),
        "W1-02": _task(
            "failed", "coder", "W1", code="W1-02", title="补测试", tokens_used=50, repair_rounds=2,
            last_error="测试失败",
        ),
        "W2-01": _task("running", "tester", "W2", code="W2-01", title="联调", tokens_used=30),
        "W2-02": _task("blocked", "tester", "W2", code="W2-02", title="回归", blocked_by=["W2-01"]),
    }
    run.events = [
        {"seq": 1, "ts": "2026-11-24T10:00:00+00:00", "kind": "task.state_changed", "subject": "W1-01", "payload": {"code": "W1-01", "to": "running"}},
        {"seq": 2, "ts": "2026-11-24T10:00:05+00:00", "kind": "task.state_changed", "subject": "W1-01", "payload": {"code": "W1-01", "to": "done"}},
        {"seq": 3, "ts": "2026-11-24T10:00:06+00:00", "kind": "llm.fallback", "subject": "coder", "payload": {"slot": "coder"}},
    ]
    return run


def test_monitor_snapshot_rolls_up_packages_and_agents() -> None:
    models = SimpleNamespace(
        slots={
            "coder": SimpleNamespace(model="qwen-coder"),
            "flagship_alt": SimpleNamespace(model="qwen-max"),
        }
    )
    roles = SimpleNamespace(
        roles={
            "coder": SimpleNamespace(slot="coder"),
            "tester": SimpleNamespace(slot="flagship_alt"),
        }
    )
    snapshot = build_monitor_snapshot(_run(), models, roles)

    summary = snapshot["run"]
    assert summary["task_count"] == 4
    assert summary["done"] == 1
    assert summary["failed"] == 1
    assert summary["running"] == 1
    assert summary["blocked"] == 1
    assert summary["repair_rounds"] == 3
    assert summary["fallback_count"] == 1
    assert summary["fallback_by_slot"] == {"coder": 1}

    packages = {item["code"]: item for item in snapshot["work_packages"]}
    assert packages["W1"]["total"] == 2
    assert packages["W1"]["failed"] == 1
    assert packages["W2"]["running"] == 1
    assert packages["W2"]["blocked"] == 1

    tasks = {item["code"]: item for item in snapshot["tasks"]}
    assert tasks["W1-01"]["model"] == "qwen-coder"
    assert tasks["W1-01"]["duration_seconds"] == 5.0
    assert tasks["W1-02"]["last_error"] == "测试失败"

    agents = {item["role"]: item for item in snapshot["agents"]}
    assert agents["coder"]["total"] == 2
    assert agents["coder"]["done"] == 1
    assert agents["coder"]["failed"] == 1
    assert agents["coder"]["success_rate"] == 50
    assert agents["coder"]["failure_reasons"] == [{"reason": "测试失败", "count": 1}]
    assert agents["tester"]["model"] == "qwen-max"
    assert agents["tester"]["blocked"] == 1


def test_monitor_endpoint_events_carry_timestamps(tmp_path: Path) -> None:
    bench = Workbench(
        Gateway(load_models(), ScriptedProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    run = RunState(id="run-1", project_id="proj-1", idea="demo")
    bench.emit(run, "task.state_changed", "T-01", {"code": "T-01", "to": "running"})
    event = run.events[-1]
    assert event["ts"].startswith("20")
    snapshot = bench.monitor_snapshot(run)
    assert snapshot["run"]["id"] == "run-1"
    assert snapshot["run"]["first_event_at"] == event["ts"]