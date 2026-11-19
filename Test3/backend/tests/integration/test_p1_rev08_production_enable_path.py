"""P1-REV-08: granted profile and execution specs need a production source.

Uses only the production create/enable/materialize service path.  It never calls
the internal test setter and never injects ``granted_execution`` by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.execution.baseline import hash_artifact
from app.execution.run_profile import run_approved_baseline_hashes, run_execution_profile
from app.main import create_app
from app.schemas.docs import TaskGraph
from tests.p1_support import make_bench, make_card


def _enable_body(plan_hash: str) -> dict:
    return {
        "execution_profile": "granted_v1",
        "approved_baseline_hashes": {"PLAN": plan_hash},
        "allowed_tool_refs": ["python -m pytest"],
    }


def _grant_body(plan_hash: str) -> dict:
    return {
        "execution_profile": "granted_v1",
        "task_codes": ["T-01"],
        "approved_baseline_hashes": {"PLAN": plan_hash},
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


def _approve_plan(bench, run) -> str:
    """Mirror the PLAN gate: human approval records the artifact digest."""
    digest = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    assert digest == hash_artifact(run.artifacts["plan"])
    return digest


@pytest.mark.asyncio
async def test_production_enable_then_materialize_has_real_spec(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    async with _client(app) as client:
        enabled = await client.post(f"/api/runs/{run.id}/execution-profile", json=_enable_body(plan_hash))
        assert enabled.status_code == 200, enabled.text

        assert run_execution_profile(run) == "granted_v1"
        bench._materialize_tasks(run)
        spec = run.tasks["T-01"].get("granted_execution")
        assert isinstance(spec, dict) and spec
        assert spec["approved_plan_hash"] == plan_hash
        assert spec["approved_baseline_hashes"] == {"PLAN": plan_hash}
        assert spec["task_codes"] == ["T-01"]
        assert spec["command"]
        assert "tool_refs" in spec
        assert spec.get("source", "").startswith("server")

        granted = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(plan_hash))
        assert granted.status_code == 201, granted.text
        spec = run.tasks["T-01"]["granted_execution"]
        assert spec["grant_id"] == granted.json()["grant_id"]


@pytest.mark.asyncio
async def test_enable_without_human_baseline_is_rejected(app) -> None:
    run = _run_with_plan(app, "T-01")
    body = _enable_body(hash_artifact(run.artifacts["plan"]))
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-profile", json=body)
    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "baseline_stale"
    assert run_execution_profile(run) == "legacy"
    assert run_approved_baseline_hashes(run) == {}


@pytest.mark.asyncio
async def test_enable_rejects_client_chosen_hashes(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    _approve_plan(bench, run)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-profile", json=_enable_body("aaa"))
    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "baseline_stale"
    assert run_execution_profile(run) == "legacy"


@pytest.mark.asyncio
async def test_enable_requires_the_plan_baseline_key(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    bench._record_approved_baseline(run, "REQUIREMENT", {"idea": run.idea})
    body = {
        "execution_profile": "granted_v1",
        "approved_baseline_hashes": run_approved_baseline_hashes(run),
        "allowed_tool_refs": ["python -m pytest"],
    }
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-profile", json=body)
    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "baseline_stale"
    assert run_execution_profile(run) == "legacy"


@pytest.mark.asyncio
async def test_enable_rejects_plan_hash_mismatch(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    body = {**_enable_body(plan_hash), "approved_plan_hash": "0" * 64}
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-profile", json=body)
    assert res.status_code == 400, res.text
    assert res.json()["error_category"] == "validation_error"
    assert run_execution_profile(run) == "legacy"


@pytest.mark.asyncio
async def test_repeated_enable_is_idempotent(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    body = _enable_body(plan_hash)
    async with _client(app) as client:
        first = await client.post(f"/api/runs/{run.id}/execution-profile", json=body)
        assert first.status_code == 200, first.text
        second = await client.post(f"/api/runs/{run.id}/execution-profile", json=body)
        assert second.status_code == 200, second.text
        profile = await client.get(f"/api/runs/{run.id}/execution-profile")
    assert second.json()["approved_baseline_hashes"] == {"PLAN": plan_hash}
    assert second.json()["approved_plan_hash"] == plan_hash
    assert profile.json()["execution_profile"] == "granted_v1"
    assert profile.json()["approved_baseline_hashes"] == {"PLAN": plan_hash}
    assert run_approved_baseline_hashes(run) == {"PLAN": plan_hash}


@pytest.mark.asyncio
async def test_client_cannot_downgrade_or_enable_legacy(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run.id}/execution-profile",
            json={**_enable_body(plan_hash), "execution_profile": "legacy"},
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
        res = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body("aaa"))
    assert res.status_code == 403
    assert res.json()["error_category"] == "profile_not_granted_v1"


@pytest.mark.asyncio
async def test_enable_survives_restart_via_sqlite(app) -> None:
    from tests.p1_support import make_bench

    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    async with _client(app) as client:
        enabled = await client.post(f"/api/runs/{run.id}/execution-profile", json=_enable_body(plan_hash))
        assert enabled.status_code == 200, enabled.text
    data_dir = bench.data_dir
    await bench.close()

    restored = make_bench(data_dir)
    try:
        recovered = restored.runs[run.id]
        assert run_execution_profile(recovered) == "granted_v1"
        assert run_approved_baseline_hashes(recovered) == {"PLAN": plan_hash}
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_granted_retry_and_accept_are_controlled_409(app) -> None:
    bench = app.state.workbench
    run = _run_with_plan(app, "T-01")
    plan_hash = _approve_plan(bench, run)
    async with _client(app) as client:
        enabled = await client.post(f"/api/runs/{run.id}/execution-profile", json=_enable_body(plan_hash))
        assert enabled.status_code == 200, enabled.text
        bench._materialize_tasks(run)
        run.tasks["T-01"]["state"] = "failed"
        run.tasks["T-01"]["revision"] = 1
        retry = await client.post(
            "/api/tasks/T-01/retry",
            json={"expected_revision": 1, "reason": "safety gate"},
        )
        assert retry.status_code == 409, retry.text
        assert retry.json()["error_category"] == "execution_safety_not_ready"
        assert run.tasks["T-01"]["state"] == "failed"

        run.artifacts["spec"] = {}
        accepted = await client.post(f"/api/runs/{run.id}/accept")
        assert accepted.status_code == 409, accepted.text
        assert accepted.json()["error_category"] == "execution_safety_not_ready"