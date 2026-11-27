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

DECISION = "d" * 64
PLAN = "a" * 64


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
async def app(tmp_path):
    app = create_app()
    bench = Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )
    bench.execution_safety_ready = True
    app.state.workbench = bench
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _run(app, *, hashes: dict[str, str] | None = None):
    bench = app.state.workbench
    project = bench.create_project("dag")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01"), _card("T-02", ["T-01"])]).model_dump()
    bench._materialize_tasks(run)
    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, hashes if hashes is not None else {"PLAN": PLAN, "DecisionPackage": DECISION})
    run.artifacts["baseline_provenance"] = "fixture"
    return run


def _stub_execute(app, monkeypatch) -> list[str]:
    bench = app.state.workbench
    calls: list[str] = []

    async def fake_execute(run, code):
        calls.append(code)
        run.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    return calls


def _grant_body(task_codes: list[str], hashes: dict[str, str]) -> dict:
    return {
        "execution_profile": "granted_v1",
        "task_codes": task_codes,
        "approved_baseline_hashes": hashes,
        "repo_remote": "origin",
        "repo_owner": "WaterProMax",
        "repo_name": "HexaGraph",
        "base_branch": "teamwork-001",
        "feature_branch": "feat-p5-demo",
        "allowed_tool_refs": [],
    }


@pytest.mark.asyncio
async def test_schedule_with_matching_plan_and_decision_hash(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app)
    async with _client(app) as client:
        created = await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(["T-01", "T-02"], {"PLAN": PLAN, "DecisionPackage": DECISION}),
        )
        assert created.status_code == 201, created.text
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 200, res.text
    assert res.json()["started"] == ["T-01"]


@pytest.mark.asyncio
async def test_successor_requested_before_predecessor_is_dag_blocked(app, monkeypatch) -> None:
    calls = _stub_execute(app, monkeypatch)
    run = _run(app)
    async with _client(app) as client:
        await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(["T-01", "T-02"], {"PLAN": PLAN, "DecisionPackage": DECISION}),
        )
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-02"]})
    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "dag_blocked"
    assert calls == []
    assert run.tasks["T-02"]["state"] != "done"


@pytest.mark.asyncio
async def test_missing_decision_hash_is_baseline_stale(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app)
    async with _client(app) as client:
        await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(["T-01", "T-02"], {"PLAN": PLAN, "DecisionPackage": DECISION}),
        )
        # A later baseline edit invalidates the signed DecisionPackage hash.
        set_approved_baseline_hashes(run, {"PLAN": PLAN})
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "baseline_stale"


@pytest.mark.asyncio
async def test_grant_without_decision_key_is_not_newly_blocked(app, monkeypatch) -> None:
    """P1 grants only signed PLAN; P5 must not add a new hard requirement to them."""
    _stub_execute(app, monkeypatch)
    run = _run(app, hashes={"PLAN": PLAN})
    async with _client(app) as client:
        created = await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(["T-01"], {"PLAN": PLAN}),
        )
        assert created.status_code == 201, created.text
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_successor_runs_after_predecessor_without_new_grant(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    run = _run(app)
    async with _client(app) as client:
        await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(["T-01", "T-02"], {"PLAN": PLAN, "DecisionPackage": DECISION}),
        )
        first = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})
        assert first.status_code == 200, first.text
        run.tasks["T-01"]["state"] = "done"
        app.state.workbench._refresh_ready(run)
        second = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-02"]})
        grants = await client.get(f"/api/runs/{run.id}/execution-grants")
    assert second.status_code == 200, second.text
    assert second.json()["started"] == ["T-02"]
    active = [g for g in grants.json()["items"] if g["status"] == "active"]
    assert len(active) == 1


@pytest.mark.asyncio
async def test_legacy_schedule_ignores_dag_enforcement(app, monkeypatch) -> None:
    _stub_execute(app, monkeypatch)
    bench = app.state.workbench
    project = bench.create_project("legacy")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01"), _card("T-02", ["T-01"])]).model_dump()
    bench._materialize_tasks(run)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-02"]})
    assert res.status_code == 200, res.text