from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import set_approved_baseline_hashes, set_run_execution_profile
from app.execution.simulation import ExecutionPolicy
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


@pytest.fixture
async def app(tmp_path):
    app = create_app()
    bench = Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )
    # Test-injected safety: granted schedules below exercise grant policy, not isolation.
    bench.execution_safety_ready = True
    app.state.workbench = bench
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _run(app, *, granted: bool):
    bench = app.state.workbench
    project = bench.create_project("schedule")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01"), _card("T-02")]).model_dump()
    bench._materialize_tasks(run)
    if granted:
        set_run_execution_profile(run, "granted_v1")
        set_approved_baseline_hashes(run, {"PLAN": "aaa"})
        run.artifacts["baseline_provenance"] = "fixture"
    return run


def _stub_execute(app, monkeypatch) -> None:
    bench = app.state.workbench

    async def fake_execute(run, code):
        run.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)


def _grant_body(task_codes: list[str]) -> dict:
    return {
        "execution_profile": "granted_v1",
        "task_codes": task_codes,
        "approved_baseline_hashes": {"PLAN": "aaa"},
        "repo_remote": "origin",
        "repo_owner": "WaterProMax",
        "repo_name": "HexaGraph",
        "base_branch": "teamwork-001",
        "feature_branch": "feat-p1-demo",
        "allowed_tool_refs": [],
    }


@pytest.mark.asyncio
async def test_subset_schedule_succeeds(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=True)
    async with _client(app) as client:
        await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(["T-01", "T-02"]))
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 200, res.text
    assert res.json()["started"] == ["T-01"]


@pytest.mark.asyncio
async def test_granted_without_grant_is_403(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=True)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 403
    assert res.json()["error_category"] == "grant_required"


@pytest.mark.asyncio
async def test_superset_is_409_scope_mismatch(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=True)
    async with _client(app) as client:
        await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(["T-01"]))
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01", "T-99"]})
    assert res.status_code == 409
    assert res.json()["error_category"] == "scope_mismatch"


@pytest.mark.asyncio
async def test_empty_request_is_409(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=True)
    run.tasks["T-01"]["state"] = "done"
    async with _client(app) as client:
        await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(["T-01"]))
        res = await client.post(f"/api/runs/{run.id}/schedule", json={})
    assert res.status_code == 409
    assert res.json()["error_category"] == "empty_request"


@pytest.mark.asyncio
async def test_revision_bump_does_not_block_schedule(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=True)
    run.revision += 3
    async with _client(app) as client:
        await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(["T-01"]))
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 200, res.text
    assert res.json()["started"] == ["T-01"]


@pytest.mark.asyncio
async def test_legacy_schedule_is_unchanged_without_grant(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app, granted=False)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/schedule", json={})
    assert res.status_code == 200, res.text
    assert "error_category" not in res.json()
    assert set(res.json()["started"]) == {"T-01", "T-02"}