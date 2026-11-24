"""Card 2: HTTP surfaces expose honest evidence labels."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider([])), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _scripted_done_run(bench):
    project = bench.create_project("evidence-api")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.tasks["T-01"] = {"state": "done", "code": "T-01", "card": {}, "evidence": []}
    run.artifacts["acceptance"] = {"features": [], "nonfunc": [], "matrix": []}
    run.gates.append(
        {"id": "G-A", "kind": "验收确认", "status": "approved", "payload": {"pass": True}}
    )
    return run


@pytest.mark.asyncio
async def test_monitor_and_profile_expose_scripted_evidence(app) -> None:
    run = _scripted_done_run(app.state.workbench)
    async with _client(app) as client:
        monitor = await client.get(f"/api/runs/{run.id}/monitor")
        profile = await client.get(f"/api/runs/{run.id}/execution-profile")

    monitor_evidence = monitor.json()["workflow"]["evidence"]
    assert monitor_evidence["level"] == "scripted"
    assert monitor_evidence["execution_mode"] == "simulated"
    assert "脚本" in monitor_evidence["verification_label"]
    assert profile.json()["evidence"]["level"] == "scripted"


@pytest.mark.asyncio
async def test_module_acceptance_listing_carries_evidence_level(app) -> None:
    run = _scripted_done_run(app.state.workbench)
    async with _client(app) as client:
        res = await client.get(
            f"/api/runs/{run.id}/module-acceptances", headers={"X-Bot-Id": "bot-1"}
        )
    assert res.status_code == 200, res.text
    assert res.json()["evidence"]["level"] == "scripted"