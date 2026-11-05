from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


@pytest.mark.asyncio
async def test_health_and_project_flow(tmp_path) -> None:
    app = create_app()
    app.state.workbench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        created = await client.post("/api/projects", json={"name": "demo"})
        assert created.status_code == 200
        listed = await client.get("/api/projects")
        assert listed.json()
