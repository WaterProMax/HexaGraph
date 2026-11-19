from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import set_approved_baseline_hashes, set_run_execution_profile
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.schemas.execution_grant import ExecutionGrant
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


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
                AcceptanceCheck(
                    cmd=["python", "-c", "print('ok')"], pass_criteria="ok", from_criterion="F1"
                )
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


async def _bench_with_task(tmp_path: Path, card: TaskCard) -> tuple[Workbench, object]:
    bench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    project = bench.create_project("granted")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "7"
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    bench._materialize_tasks(run)
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, {"PLAN": "aaa"})
    grant = ExecutionGrant(
        grant_id=f"G-{card.code}",
        run_id=run.id,
        execution_profile="granted_v1",
        task_codes=[card.code],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=[],
        created_at="2026-11-19T00:00:00+00:00",
    )
    await bench.add_grant(grant)
    return bench, run


@pytest.fixture
async def bench(tmp_path):
    created: list[Workbench] = []
    yield created
    for item in created:
        await item.close()


@pytest.mark.asyncio
async def test_granted_task_writes_only_in_isolated_worktree(tmp_path: Path, bench) -> None:
    card = _card("T-01", ["foo.txt", "tests/test_ok.py"])
    workbench, run = await _bench_with_task(tmp_path, card)
    bench.append(workbench)
    run.tasks["T-01"]["granted_execution"] = {
        "writes": [
            {"path": "foo.txt", "content": "bar"},
            {"path": "tests/test_ok.py", "content": "def test_ok():\n    assert True\n"},
        ],
        "command": ["python", "-m", "pytest", "tests/test_ok.py", "-q"],
    }
    result = await workbench.execute_task(run, "T-01")
    isolated = tmp_path / "runs" / run.id / "wt" / "granted-T-01" / "foo.txt"
    assert isolated.read_text(encoding="utf-8") == "bar"
    assert not (tmp_path / "foo.txt").exists()
    assert result["state"] == "done"
    assert run.tasks["T-01"]["evidence"]
    evidence = run.tasks["T-01"]["evidence"][-1]
    assert evidence["ok"] is True
    assert Path(evidence["commands"][0]["log_path"]).is_file()


@pytest.mark.asyncio
async def test_granted_task_failure_keeps_evidence_and_fails_state(tmp_path: Path, bench) -> None:
    card = _card("T-02", ["tests/test_fail.py"])
    workbench, run = await _bench_with_task(tmp_path, card)
    bench.append(workbench)
    run.tasks["T-02"]["granted_execution"] = {
        "writes": [{"path": "tests/test_fail.py", "content": "def test_fail():\n    assert False\n"}],
        "command": ["python", "-m", "pytest", "tests/test_fail.py", "-q"],
    }
    result = await workbench.execute_task(run, "T-02")
    assert result["state"] != "done"
    evidence = run.tasks["T-02"]["evidence"][-1]
    assert evidence["ok"] is False
    assert evidence["commands"][0]["exit_code"] != 0
    assert Path(evidence["commands"][0]["log_path"]).is_file()