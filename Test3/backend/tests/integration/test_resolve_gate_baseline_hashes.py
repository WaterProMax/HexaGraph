from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.baseline import hash_artifact
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
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
            "write_set": ["tests/test_feature.py"],
            "outputs": ["tests/test_feature.py"],
            "acceptance": [
                AcceptanceCheck(
                    cmd=["python", "-m", "pytest", "tests/test_feature.py", "-q"],
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


@pytest.fixture
async def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _grant_body() -> dict:
    return {
        "execution_profile": "granted_v1",
        "task_codes": ["T-01"],
        "approved_baseline_hashes": {"PLAN": "old"},
        "repo_remote": "origin",
        "repo_owner": "WaterProMax",
        "repo_name": "HexaGraph",
        "base_branch": "teamwork-001",
        "feature_branch": "feat-p1-demo",
        "allowed_tool_refs": [],
    }


def _granted_plan_run(app):
    bench = app.state.workbench
    project = bench.create_project("gate")
    run = bench.create_run(project["id"], "idea")
    plan = TaskGraph(tasks=[_card("T-01")]).model_dump()
    run.engine.current = "6"
    run.artifacts["plan"] = plan
    bench.set_run_execution_profile(run.id, "granted_v1")
    bench.set_run_approved_baseline_hashes(run.id, {"PLAN": "old"})
    gate = bench._gate(run, "PLAN基线确认", {})["gate"]
    return bench, run, plan, gate


@pytest.mark.asyncio
async def test_plan_approval_writes_hash_and_stales_old_grant(app) -> None:
    bench, run, plan, gate = _granted_plan_run(app)
    async with _client(app) as client:
        created = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body())
        assert created.status_code == 201, created.text
        resolved = await client.post(f"/api/gates/{gate['id']}/resolve", json={"decision": "approve"})
        assert resolved.status_code == 200, resolved.text
        blocked = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    expected = hash_artifact(plan)
    assert run.artifacts["approved_baseline_hashes"]["PLAN"] == expected
    grants = await bench.grants_for_run(run.id)
    assert grants[-1].status == "stale"
    assert blocked.status_code == 409
    assert blocked.json()["error_category"] == "baseline_stale"


@pytest.mark.asyncio
async def test_concurrent_resolve_keeps_one_complete_hash(app) -> None:
    bench, run, plan, gate = _granted_plan_run(app)
    async with _client(app) as client:
        await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body())
    before = run.revision
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post(f"/api/gates/{gate['id']}/resolve", json={"decision": "approve"}),
            client.post(f"/api/gates/{gate['id']}/resolve", json={"decision": "approve"}),
        )
    assert sorted([first.status_code, second.status_code]) == [200, 400]
    assert run.revision == before + 1
    assert run.artifacts["approved_baseline_hashes"]["PLAN"] == hash_artifact(plan)