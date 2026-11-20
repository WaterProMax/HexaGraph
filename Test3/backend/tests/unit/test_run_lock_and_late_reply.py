from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import GrantRejected
from app.execution.generation import GenerationGuard
from app.execution.run_lock import RunLockRegistry
from app.execution.run_profile import set_approved_baseline_hashes, set_run_execution_profile
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.schemas.execution_grant import ExecutionGrant
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

DECISION = "d" * 64
PLAN = "a" * 64


def test_two_writers_never_overlap() -> None:
    registry = RunLockRegistry()
    peak = 0
    state = {"inside": 0}

    async def writer() -> None:
        nonlocal peak
        async with registry.write_scope("run-1"):
            state["inside"] += 1
            peak = max(peak, state["inside"])
            await asyncio.sleep(0.01)
            state["inside"] -= 1

    async def main() -> None:
        await asyncio.gather(writer(), writer())

    asyncio.run(main())
    assert peak == 1
    assert registry.holders("run-1") == 0


def test_nested_execution_reenters_instead_of_deadlocking() -> None:
    registry = RunLockRegistry()

    async def main() -> None:
        async with registry.write_scope("run-1"):
            assert registry.holders("run-1") == 1
            # asyncio.gather wraps coroutines in child tasks, which inherit the
            # context variable marking the run as held.
            await asyncio.gather(_nested(registry), _nested(registry))

    asyncio.run(main())
    assert registry.holders("run-1") == 0


async def _nested(registry: RunLockRegistry) -> None:
    async with registry.write_scope("run-1"):
        assert registry.holders("run-1") == 1


def test_generation_bump_drops_late_reply(tmp_path: Path) -> None:
    guard = GenerationGuard()
    target = tmp_path / "late.txt"
    generation_a = guard.new_id("run-1")
    generation_b = guard.bump("run-1")

    async def late_callback(generation_id: str) -> None:
        # Production shape: only the current generation may write.
        if not guard.is_current("run-1", generation_id):
            return
        target.write_text("late", encoding="utf-8")

    asyncio.run(late_callback(generation_a))
    assert not target.exists()
    assert guard.is_current("run-1", generation_b)
    asyncio.run(late_callback(generation_b))
    assert target.read_text(encoding="utf-8") == "late"


def test_new_id_does_not_invalidate_siblings() -> None:
    guard = GenerationGuard()
    first = guard.new_id("run-1")
    second = guard.new_id("run-1")
    assert guard.is_current("run-1", first)
    assert guard.is_current("run-1", second)
    guard.bump("run-1")
    assert not guard.is_current("run-1", first)
    assert not guard.is_current("run-1", second)


def _card(code: str, depends_on: list[str] | None = None) -> TaskCard:
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
            "depends_on": depends_on or [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


@pytest.fixture
async def bench(tmp_path):
    workbench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    try:
        yield workbench
    finally:
        await workbench.close()


def _grant(run_id: str, task_codes: list[str]) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="grant-1",
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=task_codes,
        approved_baseline_hashes={"PLAN": PLAN, "DecisionPackage": DECISION},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat-p5-demo",
        allowed_tool_refs=[],
        created_at="2026-11-20T00:00:00+00:00",
    )


def _granted_run(bench: Workbench, task_codes: list[str]):
    project = bench.create_project("runs")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(
        tasks=[_card("T-01"), _card("T-02", ["T-01"])]
    ).model_dump()
    bench._materialize_tasks(run)
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": PLAN, "DecisionPackage": DECISION})
    return run


async def test_continuous_execution_within_one_grant(bench, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_execute(run, code):
        calls.append(code)
        run.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    run = _granted_run(bench, ["T-01", "T-02"])
    await bench.add_grant(_grant(run.id, ["T-01", "T-02"]))
    run.tasks["T-01"]["state"] = "done"
    bench._refresh_ready(run)

    started = await bench.schedule_once(run)
    assert started == ["T-02"]
    assert calls == ["T-02"]
    grants = await bench.grants_for_run(run.id)
    assert [g.status for g in grants] == ["active"]


async def test_out_of_scope_and_missing_grant_still_rejected(bench, monkeypatch) -> None:
    async def fake_execute(run, code):
        run.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    run = _granted_run(bench, ["T-01", "T-02"])
    await bench.add_grant(_grant(run.id, ["T-01"]))
    with pytest.raises(GrantRejected) as out_of_scope:
        await bench.schedule_once(run, task_codes={"T-99"})
    assert out_of_scope.value.category == "scope_mismatch"

    no_grant = _granted_run(bench, ["T-01", "T-02"])
    with pytest.raises(GrantRejected) as missing:
        await bench.schedule_once(no_grant, task_codes={"T-01"})
    assert missing.value.category == "grant_required"


async def test_pause_bumps_generation(bench) -> None:
    run = _granted_run(bench, ["T-01"])
    before = bench._generations.new_id(run.id)
    bench.set_run_control(run, "pause")
    assert not bench._generations.is_current(run.id, before)
    assert bench._generations.current_ids(run.id)