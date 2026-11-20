from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _body(**overrides) -> dict:
    body = {
        "skill_id": "review",
        "version": "1.0.0",
        "description_md": "x",
        "allowed_tool_refs": ["git_read"],
    }
    body.update(overrides)
    return body


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_create_and_list_versions(app) -> None:
    async with _client(app) as client:
        created = await client.post("/api/skills", json=_body())
        listed = await client.get("/api/skills/review/versions")
        all_skills = await client.get("/api/skills")
    assert created.status_code == 201, created.text
    assert created.json()["version"] == "1.0.0"
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["version"] == "1.0.0"
    assert len(all_skills.json()["items"]) == 1


@pytest.mark.asyncio
async def test_duplicate_version_is_409_and_keeps_old_description(app) -> None:
    async with _client(app) as client:
        first = await client.post("/api/skills", json=_body())
        second = await client.post("/api/skills", json=_body(description_md="y"))
        listed = await client.get("/api/skills/review/versions")
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_category"] == "skill_version_exists"
    assert listed.json()["items"][0]["description_md"] == "x"


@pytest.mark.asyncio
async def test_missing_skill_is_404(app) -> None:
    async with _client(app) as client:
        res = await client.get("/api/skills/no-such/versions")
    assert res.status_code == 404
    assert res.json()["error_category"] == "skill_not_found"


@pytest.mark.asyncio
async def test_invalid_body_is_400_validation_error(app) -> None:
    async with _client(app) as client:
        res = await client.post("/api/skills", json={"skill_id": "review"})
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_concurrent_duplicate_posts_leave_one_row(app) -> None:
    async with _client(app) as first, _client(app) as second:
        left, right = await asyncio.gather(
            first.post("/api/skills", json=_body()),
            second.post("/api/skills", json=_body()),
        )
        listed = await first.get("/api/skills/review/versions")
    assert sorted([left.status_code, right.status_code]) == [201, 409]
    assert len(listed.json()["items"]) == 1