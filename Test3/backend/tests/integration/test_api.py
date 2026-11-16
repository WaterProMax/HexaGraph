from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.fixtures.study_room import scripted_m1_queue
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import get_settings, load_models, load_roles


@pytest.mark.asyncio
async def test_health_and_project_flow(tmp_path, monkeypatch) -> None:
    # Empty ScriptedProvider() + start_idea used to 400 with
    # "scripted queue empty for slot=..." whenever study-room auto-fill is off.
    # Seed the fixture here; do not drop the 200 / one-run assertions.
    monkeypatch.setattr(get_settings(), "test3_scripted_fixture", "")
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider(scripted_m1_queue())),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        created = await client.post("/api/projects", json={"name": "demo"})
        assert created.status_code == 200
        listed = await client.get("/api/projects")
        assert listed.json()
        proj_id = created.json()["id"]
        run_res = await client.post(
            f"/api/projects/{proj_id}/runs",
            json={"idea": "做一个帮同学在期末周找到有空位自习室的小程序。"},
        )
        assert run_res.status_code == 200
        runs = await client.get("/api/runs")
        assert runs.status_code == 200
        assert len(runs.json()) == 1
