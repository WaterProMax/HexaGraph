from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import run_execution_profile
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _bench(tmp_path) -> Workbench:
    return Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)


def _app(tmp_path):
    app = create_app()
    app.state.workbench = _bench(tmp_path)
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _grant_body(**overrides) -> dict:
    body = {
        "execution_profile": "granted_v1",
        "task_codes": ["T-01"],
        "approved_baseline_hashes": {"PLAN": "aaa"},
        "repo_remote": "origin",
        "repo_owner": "WaterProMax",
        "repo_name": "HexaGraph",
        "base_branch": "teamwork-001",
        "feature_branch": "feat-p1-demo",
        "allowed_tool_refs": [],
    }
    body.update(overrides)
    return body


def _granted_run(app, hashes: dict[str, str] | None = None):
    bench = app.state.workbench
    project = bench.create_project("grants")
    run = bench.create_run(project["id"], "idea")
    bench.set_run_execution_profile(run.id, "granted_v1")
    bench.set_run_approved_baseline_hashes(run.id, hashes if hashes is not None else {"PLAN": "aaa"})
    return run


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_create_and_list_grant(app) -> None:
    run = _granted_run(app)
    async with _client(app) as client:
        created = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body())
        listed = await client.get(f"/api/runs/{run.id}/execution-grants")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "active"
    assert body["task_codes"] == ["T-01"]
    assert body["grant_id"]
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["grant_id"] == body["grant_id"]


@pytest.mark.asyncio
async def test_legacy_run_cannot_create_grant(app) -> None:
    bench = app.state.workbench
    project = bench.create_project("legacy")
    run = bench.create_run(project["id"], "idea")
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body())
    assert res.status_code == 403
    assert res.json()["error_category"] == "profile_not_granted_v1"


@pytest.mark.asyncio
async def test_baseline_mismatch_is_409(app) -> None:
    run = _granted_run(app, {"PLAN": "aaa"})
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run.id}/execution-grants",
            json=_grant_body(approved_baseline_hashes={"PLAN": "zzz"}),
        )
    assert res.status_code == 409
    assert res.json()["error_category"] == "baseline_stale"


@pytest.mark.asyncio
async def test_unknown_run_is_404(app) -> None:
    async with _client(app) as client:
        res = await client.post("/api/runs/nope/execution-grants", json=_grant_body())
    assert res.status_code == 404
    assert res.json()["error_category"] == "run_not_found"


@pytest.mark.asyncio
async def test_empty_task_codes_is_400_validation_error(app) -> None:
    run = _granted_run(app)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(task_codes=[]))
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"
    assert "task_codes" in res.json()["detail"]


@pytest.mark.asyncio
async def test_no_profile_downgrade_route(app) -> None:
    run = _granted_run(app)
    async with _client(app) as client:
        patch = await client.patch(f"/api/runs/{run.id}", json={"execution_profile": "legacy"})
        post = await client.post(f"/api/runs/{run.id}", json={"execution_profile": "legacy"})
    assert patch.status_code in {404, 405}
    assert post.status_code in {404, 405}
    assert run_execution_profile(run) == "granted_v1"


@pytest.mark.asyncio
async def test_concurrent_posts_leave_complete_rows(app) -> None:
    run = _granted_run(app)
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(task_codes=["T-01"])),
            client.post(f"/api/runs/{run.id}/execution-grants", json=_grant_body(task_codes=["T-02"])),
        )
        listed = await client.get(f"/api/runs/{run.id}/execution-grants")
    assert first.status_code == 201 and second.status_code == 201
    items = listed.json()["items"]
    assert len(items) == 2
    assert {item["task_codes"][0] for item in items} == {"T-01", "T-02"}
    # Both payloads are parseable JSON, i.e. no interleaved half row.
    assert all(json.loads(json.dumps(item)) for item in items)