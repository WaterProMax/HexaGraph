from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


@pytest.fixture
async def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    await app.state.workbench._ensure_db()
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


async def test_archive_hides_project_until_restored(app):
    bench = app.state.workbench
    keep = bench.create_project("保留")
    hide = bench.create_project("归档")

    async with _client(app) as client:
        listed = await client.get("/api/projects")
        assert {p["id"] for p in listed.json()} == {keep["id"], hide["id"]}

        archived = await client.post(f"/api/projects/{hide['id']}/archive", json={})
        assert archived.status_code == 200
        assert archived.json()["archived"] is True

        listed = await client.get("/api/projects")
        assert [p["id"] for p in listed.json()] == [keep["id"]]

        all_projects = await client.get("/api/projects?include_archived=true")
        by_id = {p["id"]: p for p in all_projects.json()}
        assert by_id[hide["id"]]["archived"] is True

        restored = await client.post(f"/api/projects/{hide['id']}/restore", json={})
        assert restored.status_code == 200
        assert "archived" not in restored.json()

        listed = await client.get("/api/projects")
        assert {p["id"] for p in listed.json()} == {keep["id"], hide["id"]}


async def test_archive_persists_and_unknown_project_is_404(app, tmp_path):
    bench = app.state.workbench
    project = bench.create_project("持久化")

    async with _client(app) as client:
        missing = await client.post("/api/projects/nope/archive", json={})
        assert missing.status_code == 404
        await client.post(f"/api/projects/{project['id']}/archive", json={})

    restored = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    restored.restore_runs()
    try:
        assert restored.projects[project["id"]]["archived"] is True
    finally:
        await restored.close()