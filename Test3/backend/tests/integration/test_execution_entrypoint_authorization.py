"""Card 3: no execution entry bypasses the unified authorization decision."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.p1_support import install_plan, make_bench


class _RealProvider:
    def __init__(self) -> None:
        self.calls = []


def _app(tmp_path, provider):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _approved_run(app):
    bench = app.state.workbench
    project = bench.create_project("authz-http")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["spec"] = {"features": [], "nonfunc": [], "scenarios": [], "chapters": []}
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.gates.append(
        {"id": "G-P", "kind": "PLAN基线确认", "status": "approved", "payload": {}}
    )
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.artifacts["approved_baseline_hashes"] = {"PLAN": "p" * 64}
    install_plan(bench, run, ["T-01"])
    return run


@pytest.mark.asyncio
async def test_schedule_task_control_and_accept_reject_real_legacy(tmp_path) -> None:
    app = _app(tmp_path, _RealProvider())
    run = _approved_run(app)
    before = {code: (task["state"], task["revision"]) for code, task in run.tasks.items()}

    async with _client(app) as client:
        scheduled = await client.post(f"/api/runs/{run.id}/schedule")
        retried = await client.post(
            f"/api/tasks/T-01/retry",
            json={"expected_revision": 1, "reason": "manual retry"},
        )
        accepted = await client.post(f"/api/runs/{run.id}/accept")

    assert scheduled.status_code == 403, scheduled.text
    assert scheduled.json()["error_category"] == "profile_not_granted_v1"
    assert retried.status_code == 403, retried.text
    assert retried.json()["error_category"] == "profile_not_granted_v1"
    assert accepted.status_code == 403, accepted.text
    assert accepted.json()["error_category"] == "profile_not_granted_v1"
    # No side effects: no task moved and no acceptance gate opened.
    assert {code: (task["state"], task["revision"]) for code, task in run.tasks.items()} == before
    assert not any(gate["kind"] == "验收确认" for gate in run.gates)


@pytest.mark.asyncio
async def test_scripted_schedule_remains_available_without_grant(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, ScriptedProvider([]))
    run = _approved_run(app)
    bench = app.state.workbench

    async def fake_execute(run_state, code):
        run_state.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)

    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run.id}/schedule", json={"task_codes": ["T-01"]})

    assert res.status_code == 200, res.text
    assert res.json()["started"] == ["T-01"]
    assert bench.execution_safety_ready is False