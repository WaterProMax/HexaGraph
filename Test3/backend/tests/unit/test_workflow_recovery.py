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

def _seed_ready_started(tmp_path: Path, *, with_repo: bool = False):
    bench = _bench(tmp_path)
    project = bench.create_project("ready-started")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    task = run.tasks["T-01"]
    if with_repo:
        from app.workspace.gitops import init_repo_sync

        init_repo_sync(bench.data_dir / "runs" / run.id / "repo", {"README.md": "x\n"})
    bench._begin_attempt(run, task, "T-01")
    bench._persist_snapshot(run)
    return bench, run


@pytest.mark.asyncio
async def test_cutpoint_a_ready_started_without_repo_blocks_replay(tmp_path, monkeypatch) -> None:
    bench, run = _seed_ready_started(tmp_path)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert task["state"] == "ready"
    assert task["needs_reconciliation"] is True
    assert task["paused"] is True

    calls: list[str] = []

    async def spy_execute(*_a, **_k):
        calls.append("execute")
        raise AssertionError("must not dispatch")

    monkeypatch.setattr(restored, "execute_task", spy_execute)
    assert await restored.schedule_once(restored.runs[run_id]) == []
    assert calls == []

    # Second restart keeps the block and still does not dispatch.
    await restored.close()
    again = _bench(tmp_path)
    assert again.runs[run_id].tasks["T-01"]["needs_reconciliation"] is True


@pytest.mark.asyncio
async def test_cutpoint_b_ready_started_with_repo_and_evidence_blocks(tmp_path) -> None:
    bench, run = _seed_ready_started(tmp_path, with_repo=True)
    run_id = run.id
    run.tasks["T-01"]["evidence"] = [{"kind": "command", "summary": "partial", "path": "x"}]
    bench._persist_snapshot(run)
    await bench.close()

    restored = _bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert task["needs_reconciliation"] is True
    assert restored._tasks_requiring_reconciliation(restored.runs[run_id], {}) == ["T-01"]


@pytest.mark.asyncio
async def test_old_snapshot_without_attempt_history_is_migrated_and_blocked(tmp_path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("legacy-attempt")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    task = run.tasks["T-01"]
    task["attempt"] = {
        "attempt_id": "A-old",
        "intent": "execute",
        "status": "started",
        "baseline_hashes": {},
        "repo": str(bench.data_dir / "runs" / run.id / "repo"),
        "commit": "",
        "task_code": "T-01",
    }
    bench._persist_snapshot(run)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert [item["attempt_id"] for item in task["attempt_history"]] == ["A-old"]
    assert task["needs_reconciliation"] is True


@pytest.mark.asyncio
async def test_pure_ready_without_attempt_is_not_flagged(tmp_path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("pure-ready")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    bench._persist_snapshot(run)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert task.get("needs_reconciliation") is not True
    assert restored._tasks_requiring_reconciliation(restored.runs[run_id], {}) == []
