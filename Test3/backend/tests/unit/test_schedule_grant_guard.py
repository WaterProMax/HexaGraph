from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import GrantRejected
from app.execution.run_profile import set_approved_baseline_hashes, set_run_execution_profile
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.schemas.execution_grant import ExecutionGrant
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _card(code: str) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": code,
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "d",
            "write_set": [f"tests/test_{code.lower()}.py"],
            "outputs": [f"tests/test_{code.lower()}.py"],
            "acceptance": [
                AcceptanceCheck(
                    cmd=["python", "-m", "pytest", f"tests/test_{code.lower()}.py", "-q"],
                    pass_criteria="ok",
                    from_criterion="F1",
                )
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


def _bench(tmp_path: Path) -> tuple[Workbench, object]:
    bench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path, execution_policy=ExecutionPolicy(local_execution_authorized=True))
    bench.execution_safety_ready = True
    project = bench.create_project("grants")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01"), _card("T-02")]).model_dump()
    bench._materialize_tasks(run)
    return bench, run


@pytest.fixture
async def bench_run(tmp_path: Path):
    bench, run = _bench(tmp_path)
    try:
        yield bench, run
    finally:
        await bench.close()


def _grant(codes: list[str], *, status: str = "active") -> ExecutionGrant:
    return ExecutionGrant(
        grant_id=f"G-{'-'.join(codes)}-{status}",
        run_id="run",
        execution_profile="granted_v1",
        task_codes=codes,
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat-p1-demo",
        allowed_tool_refs=[],
        status=status,  # type: ignore[arg-type]
        created_at="2026-11-19T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_subset_grant_schedules_only_requested_task(bench_run, monkeypatch) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    await bench.add_grant(_grant(["T-01", "T-02"]).model_copy(update={"run_id": run.id}))
    calls: list[str] = []

    async def fake_execute(run_, code):
        calls.append(code)
        run_.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    started = await bench.schedule_once(run, task_codes={"T-01"})
    assert started == ["T-01"]
    assert calls == ["T-01"]


@pytest.mark.asyncio
async def test_granted_without_grant_is_403(bench_run) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    with pytest.raises(GrantRejected) as excinfo:
        await bench.schedule_once(run, task_codes={"T-01"})
    assert excinfo.value.category == "grant_required"
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_superset_is_scope_mismatch(bench_run) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    await bench.add_grant(_grant(["T-01"]).model_copy(update={"run_id": run.id}))
    with pytest.raises(GrantRejected) as excinfo:
        await bench.schedule_once(run, task_codes={"T-01", "T-99"})
    assert excinfo.value.category == "scope_mismatch"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_all_granted_tasks_done_and_no_body_is_empty_request(bench_run) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    await bench.add_grant(_grant(["T-01"]).model_copy(update={"run_id": run.id}))
    run.tasks["T-01"]["state"] = "done"
    with pytest.raises(GrantRejected) as excinfo:
        await bench.schedule_once(run)
    assert excinfo.value.category == "empty_request"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_revision_bump_does_not_stale_grant(bench_run, monkeypatch) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    await bench.add_grant(_grant(["T-01"]).model_copy(update={"run_id": run.id}))
    run.revision += 5

    async def fake_execute(run_, code):
        run_.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    assert await bench.schedule_once(run, task_codes={"T-01"}) == ["T-01"]


@pytest.mark.asyncio
async def test_legacy_schedule_never_requires_grant(bench_run, monkeypatch) -> None:
    bench, run = bench_run
    assert run.artifacts.get("execution_profile") is None
    calls: list[str] = []

    async def fake_execute(run_, code):
        calls.append(code)
        run_.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    assert await bench.schedule_once(run) == ["T-01", "T-02"]
    assert calls == ["T-01", "T-02"]


@pytest.mark.asyncio
async def test_concurrent_same_task_has_one_in_flight(bench_run, monkeypatch) -> None:
    bench, run = bench_run
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    run.artifacts["baseline_provenance"] = "fixture"
    await bench.add_grant(_grant(["T-01"]).model_copy(update={"run_id": run.id}))
    in_flight = 0
    peak = 0

    async def fake_execute(run_, code):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        run_.tasks[code]["state"] = "done"
        in_flight -= 1
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    await asyncio.gather(
        bench.schedule_once(run, task_codes={"T-01"}),
        bench.schedule_once(run, task_codes={"T-01"}),
    )
    assert peak == 1