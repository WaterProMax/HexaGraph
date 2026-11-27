from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.api import routes
from app.events.bus import BUS
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi_structure.json"


def _bench(tmp_path) -> Workbench:
    return Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path, execution_policy=ExecutionPolicy(local_execution_authorized=True))


def _app(tmp_path):
    app = create_app()
    app.state.workbench = _bench(tmp_path)
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _new_run(app):
    bench = app.state.workbench
    project = bench.create_project("demo")
    return bench.create_run(project["id"], "idea")


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


# ---------- 404 ----------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/runs/nope", None),
        ("GET", "/api/runs/nope/events/history", None),
        ("GET", "/api/runs/nope/events", None),
        ("GET", "/api/runs/nope/tasks", None),
        ("GET", "/api/tasks/nope", None),
        ("POST", "/api/projects/nope/runs", {"idea": "x"}),
        ("POST", "/api/gates/nope/resolve", {"decision": "通过"}),
        ("POST", "/api/tasks/nope/retry", {"expected_revision": 0, "reason": "x"}),
        ("POST", "/api/runs/nope/pause", None),
        ("POST", "/api/runs/nope/terminate", {"confirm": True}),
        ("POST", "/api/crs/CR-999/decision", {"decision": "批准"}),
    ],
)
async def test_unknown_resource_is_404(app, method, path, body) -> None:
    async with _client(app) as client:
        res = await client.request(method, path, json=body)
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_unknown_cr_on_existing_run_is_404(app) -> None:
    run = _new_run(app)
    await app.state.workbench.submit_cr(run, "改点东西", [])
    async with _client(app) as client:
        res = await client.post("/api/crs/CR-DOES-NOT-EXIST/decision", json={"decision": "批准"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_cr_decision_validation_failed_maps_to_400(app, monkeypatch) -> None:
    from app.errors import ValidationFailed

    run = _new_run(app)
    cr = await app.state.workbench.submit_cr(run, "改点东西", [])
    code = run.crs[0]["code"]

    async def boom(self, run, payload):
        raise ValidationFailed("变更单不存在")

    monkeypatch.setattr(Workbench, "decide_cr", boom)
    async with _client(app) as client:
        res = await client.post(f"/api/crs/{code}/decision", json={"decision": "批准"})
    assert cr is not None
    assert res.status_code == 400


# ---------- 400 / 409 / 422 stay as-is ----------


@pytest.mark.asyncio
async def test_terminate_requires_confirm(app) -> None:
    run = _new_run(app)
    async with _client(app) as client:
        assert (await client.post(f"/api/runs/{run.id}/terminate", json={})).status_code == 400
        assert (await client.post(f"/api/runs/{run.id}/terminate", json={"confirm": False})).status_code == 400
        assert (await client.post(f"/api/runs/{run.id}/terminate")).status_code == 422


@pytest.mark.asyncio
async def test_validation_422_and_limits_400(app) -> None:
    run = _new_run(app)
    async with _client(app) as client:
        assert (await client.post("/api/projects", json={})).status_code == 422
        assert (await client.get(f"/api/runs/{run.id}/events/history?after=abc")).status_code == 422
        assert (await client.get(f"/api/runs/{run.id}/trace/impact")).status_code == 422
        assert (await client.patch(f"/api/runs/{run.id}/limits", json=[1])).status_code == 422
        assert (await client.patch(f"/api/runs/{run.id}/limits", json={"nope": 1})).status_code == 400


@pytest.mark.asyncio
async def test_gate_stale_revision_is_409(app) -> None:
    run = _new_run(app)
    gate = app.state.workbench._gate(run, "测试关卡", {})["gate"]
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "通过", "expected_revision": run.revision + 99},
        )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_task_control_stale_revision_is_409_and_missing_field_422(app) -> None:
    run = _new_run(app)
    run.tasks["T-01"] = {
        "id": "task-1",
        "code": "T-01",
        "state": "needs_human",
        "revision": 3,
        "card": {"sources": []},
    }
    async with _client(app) as client:
        res = await client.post("/api/tasks/T-01/retry", json={"expected_revision": 0, "reason": "x"})
        assert res.status_code == 409, res.text
        assert (await client.post("/api/tasks/T-01/retry", json={})).status_code == 422


# ---------- never 500 ----------


@pytest.mark.asyncio
async def test_accept_without_spec_is_not_500(app) -> None:
    run = _new_run(app)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/accept")
    assert res.status_code == 409
    assert "spec" in res.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["abc", "-5", "1.5", ""])
async def test_invalid_last_event_id_does_not_500(app, value) -> None:
    run = _new_run(app)
    app.state.workbench.emit(run, "x.y")
    request = SimpleNamespace(app=app)
    resp = await routes.event_sse(run.id, request, value)
    assert resp.status_code == 200
    first = await asyncio.wait_for(resp.body_iterator.__anext__(), 1)
    assert first.startswith("id: 1\n")
    await resp.body_iterator.aclose()


# ---------- SSE ----------


def _sse(app, run, last_id=None):
    return routes.event_sse(run.id, SimpleNamespace(app=app), last_id)


async def _next(resp, timeout=1.0) -> str:
    return await asyncio.wait_for(resp.body_iterator.__anext__(), timeout)


async def _next_event(resp, timeout=1.0) -> str:
    while True:
        frame = await _next(resp, timeout)
        if frame != ": ping\n\n":
            return frame


def _id(frame: str) -> int:
    return int(frame.split("\n")[0].removeprefix("id: "))


@pytest.mark.asyncio
async def test_sse_pushes_new_event_within_one_second(app) -> None:
    run = _new_run(app)
    base = len(run.events)
    resp = await _sse(app, run, str(base))
    assert (await _next(resp)) == ": ping\n\n"
    pending = asyncio.ensure_future(_next(resp))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    app.state.workbench.emit(run, "stage.started", "S1", {"a": 1})
    frame = await pending
    assert time.monotonic() - started < 1.0
    assert frame.startswith(f"id: {base + 1}\nevent: message\ndata: ")
    assert frame.endswith("\n\n")
    data = json.loads(frame.split("data: ", 1)[1])
    assert data["seq"] == base + 1 and data["kind"] == "stage.started" and data["payload"] == {"a": 1}
    await resp.body_iterator.aclose()


@pytest.mark.asyncio
async def test_sse_last_event_id_resume_no_duplicates_in_order(app) -> None:
    run = _new_run(app)
    base = len(run.events)
    for i in range(5):
        app.state.workbench.emit(run, f"k.{i}")
    resp = await _sse(app, run, str(base + 3))
    assert [_id(await _next_event(resp)), _id(await _next_event(resp))] == [base + 4, base + 5]
    for i in range(3):
        app.state.workbench.emit(run, f"m.{i}")
    more = [_id(await _next_event(resp)) for _ in range(3)]
    assert more == [base + 6, base + 7, base + 8]
    await resp.body_iterator.aclose()


@pytest.mark.asyncio
async def test_sse_event_between_replay_and_subscribe_is_not_lost(app) -> None:
    run = _new_run(app)
    base = len(run.events)
    app.state.workbench.emit(run, "a")
    resp = await _sse(app, run, str(base))
    assert _id(await _next_event(resp)) == base + 1
    app.state.workbench.emit(run, "b")
    app.state.workbench.emit(run, "c")
    ids = [_id(await _next_event(resp)) for _ in range(2)]
    assert ids == [base + 2, base + 3]
    await resp.body_iterator.aclose()


@pytest.mark.asyncio
async def test_sse_heartbeat_every_interval(app, monkeypatch) -> None:
    monkeypatch.setattr(routes, "SSE_HEARTBEAT_SECONDS", 0.05)
    run = _new_run(app)
    resp = await _sse(app, run, str(len(run.events)))
    assert (await _next(resp)) == ": ping\n\n"
    assert (await _next(resp)) == ": ping\n\n"
    await resp.body_iterator.aclose()


@pytest.mark.asyncio
async def test_sse_disconnect_unsubscribes(app) -> None:
    run = _new_run(app)
    resp = await _sse(app, run)
    await _next(resp)
    assert len(BUS._subs[run.id]) == 1
    await resp.body_iterator.aclose()
    assert len(BUS._subs[run.id]) == 0


# ---------- OpenAPI structure snapshot ----------


def _ref(schema: dict | None) -> str | None:
    if not schema:
        return None
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    return schema.get("type")


def openapi_structure(spec: dict) -> dict:
    paths: dict = {}
    for path, item in sorted(spec["paths"].items()):
        for method, op in sorted(item.items()):
            body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
            paths[f"{method.upper()} {path}"] = {
                "params": sorted(f"{p['in']}:{p['name']}{'*' if p.get('required') else ''}" for p in op.get("parameters", [])),
                "body": _ref(body),
                "responses": sorted(op.get("responses", {})),
            }
    schemas = {
        name: {
            "required": sorted(s.get("required", [])),
            "properties": {k: _ref(v) or v.get("anyOf") and "anyOf" or "any" for k, v in sorted(s.get("properties", {}).items())},
        }
        for name, s in sorted(spec.get("components", {}).get("schemas", {}).items())
    }
    return {"paths": paths, "schemas": schemas}


@pytest.mark.asyncio
async def test_openapi_structure_matches_snapshot(app) -> None:
    async with _client(app) as client:
        res = await client.get("/openapi.json")
    current = openapi_structure(res.json())
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current == expected, "OpenAPI 结构变化；确认是有意修改后用 UPDATE_OPENAPI_SNAPSHOT=1 重新生成并更新 docs/API.md"
