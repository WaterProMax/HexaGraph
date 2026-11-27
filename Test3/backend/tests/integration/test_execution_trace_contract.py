"""I0 contract tests for the read endpoints.

The task list must stay list-safe (no step bodies) while the dedicated trace
route carries the steps; the monitor snapshot only gains counts and last-step
metadata.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.execution.trace_log import EXECUTION_PATH_LEGACY
from app.main import create_app
from app.services.monitor import build_monitor_snapshot


def _step(step: int, name: str = "read_file") -> dict:
    return {
        "step": step,
        "kind": "tool",
        "name": name,
        "status": "ok",
        "started_at": "2026-11-26T00:00:00+00:00",
        "ended_at": "2026-11-26T00:00:00+00:00",
        "duration_ms": 5,
        "model": "",
        "slot": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "finish_reason": "",
        "input_summary": "path=src/app.py",
        "output_summary": "chars=1200; preview=def main(): TRACE_ONLY_MARKER",
        "error": None,
        "truncated": True,
    }


def _attempt(status: str, steps: list[dict]) -> dict:
    return {
        "attempt_id": "attempt-1",
        "status": status,
        "started_at": "2026-11-26T00:00:00+00:00",
        "ended_at": "2026-11-26T00:00:01+00:00",
        "role": "coder",
        "context_hash": "ctx",
        "memory_context_hash": "mem",
        "manual_revision": 1,
        "skill_bundle_hash": "",
        "commit": "",
        "execution_path": EXECUTION_PATH_LEGACY,
        "context_injected": True,
        "execution_steps": steps,
    }


def _task(with_steps: bool = True) -> dict:
    current = _attempt("finished_ok", [_step(1), _step(2, "write_file")] if with_steps else [])
    return {
        "id": "run-1:T-01",
        "code": "T-01",
        "state": "done",
        "revision": 2,
        "card": {"code": "T-01", "title": "Task", "role": "coder"},
        "attempt": current,
        "attempt_history": [dict(current)],
        "role_memory": {"manual_text": "must-not-leak"},
    }


def _workbench(tasks: dict) -> SimpleNamespace:
    run = SimpleNamespace(id="run-1", project_id="p-1", tasks=tasks)
    return SimpleNamespace(runs={"run-1": run})


@pytest.fixture
async def api():
    app = create_app()
    app.state.workbench = _workbench({"T-01": _task()})
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as http:
        yield SimpleNamespace(client=http, app=app)


@pytest.mark.asyncio
async def test_task_list_strips_step_bodies(api) -> None:
    response = await api.client.get("/api/runs/run-1/tasks")
    assert response.status_code == 200
    payload = response.json()
    task = payload[0]
    assert "execution_steps" not in task["attempt"]
    assert all("execution_steps" not in item for item in task["attempt_history"])
    # Summaries stay, so a list can still show progress at a glance.
    assert task["attempt"]["execution_step_count"] == 2
    assert task["attempt"]["last_execution_step"] == {
        "kind": "tool",
        "name": "write_file",
        "status": "ok",
        "duration_ms": 5,
    }
    assert "role_memory" not in task
    assert "must-not-leak" not in response.text
    # No step I/O text may ride along with the list.
    assert "TRACE_ONLY_MARKER" not in response.text


@pytest.mark.asyncio
async def test_task_detail_also_strips_step_bodies(api) -> None:
    response = await api.client.get("/api/tasks/T-01")
    assert response.status_code == 200
    assert "execution_steps" not in response.json()["attempt"]
    assert "TRACE_ONLY_MARKER" not in response.text


@pytest.mark.asyncio
async def test_execution_trace_route_returns_steps(api) -> None:
    response = await api.client.get("/api/runs/run-1/tasks/T-01/execution-trace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert payload["task_code"] == "T-01"
    assert payload["execution_path"] == EXECUTION_PATH_LEGACY
    assert payload["context_injected"] is True
    assert payload["current_attempt_id"] == "attempt-1"
    assert len(payload["attempts"]) == 1
    steps = payload["attempts"][0]["steps"]
    assert [item["name"] for item in steps] == ["read_file", "write_file"]
    assert steps[0]["kind"] == "tool"
    assert steps[0]["truncated"] is True
    assert steps[0]["error"] is None


@pytest.mark.asyncio
async def test_execution_trace_empty_task_is_not_404(api) -> None:
    api.app.state.workbench = _workbench({"T-02": _task(with_steps=False)})
    response = await api.client.get("/api/runs/run-1/tasks/T-02/execution-trace")
    assert response.status_code == 200
    assert response.json()["attempts"][0]["steps"] == []


@pytest.mark.asyncio
async def test_execution_trace_unknown_task_and_run_are_404(api) -> None:
    assert (await api.client.get("/api/runs/run-1/tasks/NOPE/execution-trace")).status_code == 404
    assert (await api.client.get("/api/runs/run-x/tasks/T-01/execution-trace")).status_code == 404


def test_monitor_snapshot_adds_lightweight_trace_summary() -> None:
    task = _task()
    run = SimpleNamespace(
        id="run-1",
        project_id="p-1",
        status="running",
        paused=False,
        revision=1,
        tokens_used=0,
        events=[],
        artifacts={},
        tasks={"T-01": task},
        engine=SimpleNamespace(current="4"),
        limits={},
    )
    snapshot = build_monitor_snapshot(run, None, None)
    row = snapshot["tasks"][0]
    assert row["execution_path"] == EXECUTION_PATH_LEGACY
    assert row["context_injected"] is True
    assert row["execution_step_count"] == 2
    assert row["last_execution_step"]["name"] == "write_file"
    # Monitor stays lightweight: no step I/O text in the snapshot.
    assert "TRACE_ONLY_MARKER" not in str(snapshot)


def test_monitor_snapshot_tolerates_tasks_without_attempts() -> None:
    run = SimpleNamespace(
        id="run-1",
        project_id="p-1",
        status="pending",
        paused=False,
        revision=1,
        tokens_used=0,
        events=[],
        artifacts={},
        tasks={"T-09": {"code": "T-09", "state": "pending", "card": {"title": "Task", "role": "coder"}}},
        engine=SimpleNamespace(current="1"),
        limits={},
    )
    row = build_monitor_snapshot(run, None, None)["tasks"][0]
    assert row["execution_path"] == ""
    assert row["context_injected"] is False
    assert row["execution_step_count"] == 0
    assert row["last_execution_step"] is None