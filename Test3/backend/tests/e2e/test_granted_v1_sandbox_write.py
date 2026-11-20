"""F-04: the production granted entry is enabled and materialized, but closed.

Until F-05/F-06 finish the unified grant boundary and the real isolation backend,
``execute_task`` must reject granted runs with ``execution_safety_not_ready`` and
must never fall back to the legacy model/auto-merge chain.  This file uses the
production enable/materialize service path; it does not inject
``granted_execution`` by hand and does not start an isolated worker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import GrantRejected
from app.execution.run_profile import run_execution_profile
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from tests.p1_support import make_bench, make_grant


def _card(code: str, write_set: list[str]) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": code,
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "d",
            "write_set": write_set,
            "outputs": write_set,
            "acceptance": [
                AcceptanceCheck(cmd=["python", "-m", "pytest", "-q"], pass_criteria="ok", from_criterion="F1")
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


async def _prepared(tmp_path: Path, card: TaskCard):
    bench = make_bench(tmp_path)
    project = bench.create_project("granted")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "7"
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    bench._materialize_tasks(run)
    plan_hash = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    await bench.enable_granted_execution(run.id, {"PLAN": plan_hash})
    await bench.add_grant(make_grant(run.id, [card.code]))
    return bench, run


@pytest.mark.asyncio
async def test_granted_execution_is_refused_until_safety_is_ready(tmp_path: Path) -> None:
    card = _card("T-01", ["foo.txt", "tests/test_ok.py"])
    bench, run = await _prepared(tmp_path, card)
    try:
        assert run_execution_profile(run) == "granted_v1"
        spec = run.tasks["T-01"]["granted_execution"]
        assert spec["approved_plan_hash"]
        assert spec["task_codes"] == ["T-01"]
        assert spec["command"]

        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "execution_safety_not_ready"
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
        assert not (tmp_path / "foo.txt").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_retry_on_granted_run_is_refused(tmp_path: Path) -> None:
    card = _card("T-02", ["tests/test_fail.py"])
    bench, run = await _prepared(tmp_path, card)
    run.tasks["T-02"]["state"] = "failed"
    run.tasks["T-02"]["revision"] = 1
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.control_task(run, "T-02", "retry", 1, "review repro")
        assert excinfo.value.category == "execution_safety_not_ready"
        assert run.tasks["T-02"]["state"] != "done"
    finally:
        await bench.close()