"""P1-REV-08: granted profile and execution specs need a production source.

Uses only the production create/enable/materialize service path.  It never calls
the internal test setter and never injects ``granted_execution`` by hand.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.execution.run_profile import run_execution_profile
from app.main import create_app
from app.schemas.docs import TaskGraph
from tests.p1_support import make_bench, make_card

ENABLE_BODY = {
    "execution_profile": "granted_v1",
    "approved_baseline_hashes": {"PLAN": "aaa"},
    "allowed_tool_refs": ["python -m pytest"],
}

GRANT_BODY = {
    "execution_profile": "granted_v1",
    "task_codes": ["T-01"],
    "approved_baseline_hashes": {"PLAN": "aaa"},
    "repo_remote": "origin",
    "repo_owner": "WaterProMax",
    "repo_name": "HexaGraph",
    "base_branch": "teamwork-001",
    "feature_branch": "feat/p1-demo",
    "allowed_tool_refs": ["python -m pytest"],
}


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


@pytest.fixture
async def app(tmp_path: Path):
    app = create_app()
    app.state.workbench = make_bench(tmp_path)
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _run_with_plan(app, code: str = "T-01"):
    bench = app.state.workbench
    project = bench.create_project("p1-rev08")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[make_card(code)]).model_dump()
    return run


@pytest.mark.asyncio
async def test_production_enable_then_materialize_has_real_spec(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    async with _client(app) as client:
        enabled = await client.post(f"/api/runs/{run.id}/execution-profile", json=ENABLE_BODY)
        assert enabled.status_code == 200, enabled.text

        assert run_execution_profile(run) == "granted_v1"
        bench._materialize_tasks(run)
        spec = run.tasks["T-01"].get("granted_execution")
        assert isinstance(spec, dict) and spec
        expected_hash = hashlib.sha256(
            json.dumps(run.artifacts["plan"], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert spec["approved_plan_hash"] == expected_hash
        assert spec["task_codes"] == ["T-01"]
        assert spec["command"]
        assert "tool_refs" in spec
        assert spec.get("source", "").startswith("server")

        granted = await client.post(f"/api/runs/{run.id}/execution-grants", json=GRANT_BODY)
        assert granted.status_code == 201, granted.text
        spec = run.tasks["T-01"]["granted_execution"]
        assert spec["grant_id"] == granted.json()["grant_id"]


@pytest.mark.asyncio
async def test_client_cannot_downgrade_or_enable_legacy(app) -> None:
    run = _run_with_plan(app, "T-01")
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run.id}/execution-profile",
            json={**ENABLE_BODY, "execution_profile": "legacy"},
        )
    assert res.status_code in {400, 422}
    assert run_execution_profile(run) != "granted_v1"


@pytest.mark.asyncio
async def test_ordinary_create_run_materialization_has_no_granted_spec(app) -> None:
    bench = app.state.workbench
    project = bench.create_project("p1-rev08")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[make_card("T-01")]).model_dump()
    bench._materialize_tasks(run)
    assert "granted_execution" not in run.tasks["T-01"]


@pytest.mark.asyncio
async def test_legacy_run_cannot_create_grant(app) -> None:
    bench = app.state.workbench
    project = bench.create_project("p1-rev08")
    run = bench.create_run(project["id"], "idea")
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-grants", json=GRANT_BODY)
    assert res.status_code == 403
    assert res.json()["error_category"] == "profile_not_granted_v1"

@pytest.mark.asyncio
async def test_enable_survives_restart_via_sqlite(app) -> None:
    from app.execution.run_profile import run_approved_baseline_hashes
    from tests.p1_support import make_bench

    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    async with _client(app) as client:
        enabled = await client.post(f"/api/runs/{run.id}/execution-profile", json=ENABLE_BODY)
        assert enabled.status_code == 200, enabled.text
    data_dir = bench.data_dir
    await bench.close()

    restored = make_bench(data_dir)
    try:
        recovered = restored.runs[run.id]
        assert run_execution_profile(recovered) == "granted_v1"
        assert run_approved_baseline_hashes(recovered) == {"PLAN": "aaa"}
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_granted_retry_and_accept_are_controlled_409(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    async with _client(app) as client:
        assert (await client.post(f"/api/runs/{run.id}/execution-profile", json=ENABLE_BODY)).status_code == 200
        bench._materialize_tasks(run)
        run.tasks["T-01"]["state"] = "failed"
        run.tasks["T-01"]["revision"] = 1
        retry = await client.post(
            f"/api/tasks/T-01/retry",
            json={"expected_revision": 1, "reason": "safety gate"},
        )
        assert retry.status_code == 409, retry.text
        assert retry.json()["error_category"] == "execution_safety_not_ready"
        assert run.tasks["T-01"]["state"] == "failed"

        run.artifacts["spec"] = {}
        accepted = await client.post(f"/api/runs/{run.id}/accept")
        assert accepted.status_code == 409, accepted.text
        assert accepted.json()["error_category"] == "execution_safety_not_ready"
