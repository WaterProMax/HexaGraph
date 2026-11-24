"""Card 6: crash recovery marks unknown executions and never replays them."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import GrantRejected
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workflow.projection import project_workflow_projection
from tests.p1_support import install_plan


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def _seed_running(tmp_path: Path) -> tuple[Workbench, object]:
    bench = _bench(tmp_path)
    project = bench.create_project("recovery")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    task = run.tasks["T-01"]
    task["evidence"] = []
    bench._set_state(run, task, "scheduled")
    task["revision"] = 5
    task["evidence"] = []
    bench._persist_snapshot(run)
    return bench, run


@pytest.mark.asyncio
async def test_restored_running_task_is_needs_reconciliation_and_not_dispatched(tmp_path) -> None:
    bench, run = _seed_running(tmp_path)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]

    assert task["needs_reconciliation"] is True
    assert task["paused"] is True
    assert project_workflow_projection(run=restored.runs[run_id]).stage == "needs_reconciliation"
    assert await restored.schedule_once(restored.runs[run_id]) == []

    report = restored.reconcile_run(restored.runs[run_id])
    assert report["needs_reconciliation"] is True
    assert [item["task_code"] for item in report["tasks"]] == ["T-01"]
    assert report["tasks"][0]["state"] == "running"
    # Idempotent, read-only: a second call changes nothing and never executes.
    assert restored.reconcile_run(restored.runs[run_id]) == report


@pytest.mark.asyncio
async def test_manual_retry_on_reconciliation_task_is_rejected(tmp_path) -> None:
    bench, run = _seed_running(tmp_path)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    restored_run = restored.runs[run_id]
    with pytest.raises(GrantRejected) as exc:
        await restored.control_task(
            restored_run, "T-01", "retry", 5, "force retry", actor="owner"
        )
    assert exc.value.category == "needs_reconciliation"
    assert restored_run.tasks["T-01"]["state"] == "running"


@pytest.mark.asyncio
async def test_explicit_schedule_of_flagged_task_is_rejected(tmp_path) -> None:
    bench, run = _seed_running(tmp_path)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    with pytest.raises(GrantRejected) as exc:
        await restored.schedule_once(restored.runs[run_id], task_codes={"T-01"})
    assert exc.value.category == "needs_reconciliation"