from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

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
        "display_name": "Alice",
        "role_template": "developer",
        "provider_ref": "dashscope",
        "model": "qwen-plus",
        "slot": "coder",
        "secret_ref": "DASHSCOPE_API_KEY",
        "tool_policy": ["git_read"],
        "skill_bindings": [{"skill_id": "review", "pinned_version": "1.0.0"}],
        "token_budget": 12_345,
    }
    body.update(overrides)
    return body


def _bot_rows(tmp_path: Path) -> int:
    db = tmp_path / "test3.db"
    if not db.exists():
        return 0
    con = sqlite3.connect(db)
    try:
        try:
            return con.execute("select count(*) from bots").fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        con.close()


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_create_and_get_bot(app) -> None:
    async with _client(app) as client:
        created = await client.post("/api/bots", json=_body())
        assert created.status_code == 201, created.text
        bot_id = created.json()["bot_id"]
        fetched = await client.get(f"/api/bots/{bot_id}")
    assert bot_id
    payload = fetched.json()
    assert fetched.status_code == 200
    assert payload["display_name"] == "Alice"
    assert payload["role_template"] == "developer"
    assert payload["provider_ref"] == "dashscope"
    assert payload["model"] == "qwen-plus"
    assert payload["slot"] == "coder"
    assert payload["secret_ref"] == "DASHSCOPE_API_KEY"
    assert payload["tool_policy"] == ["git_read"]
    assert payload["skill_bindings"] == [{"skill_id": "review", "pinned_version": "1.0.0"}]
    assert payload["token_budget"] == 12_345
    assert payload["status"] == "active"


@pytest.mark.asyncio
async def test_duplicate_display_name_is_409(app) -> None:
    async with _client(app) as client:
        first = await client.post("/api/bots", json=_body(display_name="alice"))
        second = await client.post("/api/bots", json=_body(display_name="Alice"))
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_category"] == "bot_name_conflict"


@pytest.mark.asyncio
async def test_unknown_bot_is_404(app) -> None:
    async with _client(app) as client:
        res = await client.get("/api/bots/no-such-bot")
    assert res.status_code == 404
    assert res.json()["error_category"] == "bot_not_found"


@pytest.mark.asyncio
async def test_project_bots_route_is_not_registered(app, tmp_path: Path) -> None:
    async with _client(app) as client:
        await client.post("/api/bots", json=_body())
        before = _bot_rows(tmp_path)
        res = await client.post("/api/projects/p1/bots", json=_body(display_name="Injected"))
        after = _bot_rows(tmp_path)
    assert res.status_code in {404, 405}
    assert before == after == 1


@pytest.mark.asyncio
async def test_patch_model_updates_and_adds_pin_revision(app) -> None:
    async with _client(app) as client:
        created = await client.post("/api/bots", json=_body())
        bot_id = created.json()["bot_id"]
        patched = await client.patch(f"/api/bots/{bot_id}", json={"model": "gpt-4o-compatible"})
        fetched = await client.get(f"/api/bots/{bot_id}")
    assert patched.status_code == 200, patched.text
    assert patched.json()["model"] == "gpt-4o-compatible"
    assert patched.json()["pin_revision"] == 2
    assert fetched.json()["model"] == "gpt-4o-compatible"


@pytest.mark.asyncio
async def test_archive_and_archived_binding_change(app) -> None:
    async with _client(app) as client:
        created = await client.post("/api/bots", json=_body())
        bot_id = created.json()["bot_id"]
        archived = await client.post(f"/api/bots/{bot_id}/archive", json={})
        again = await client.post(f"/api/bots/{bot_id}/archive", json={})
        patched = await client.patch(f"/api/bots/{bot_id}", json={"model": "other-model"})
        fetched = await client.get(f"/api/bots/{bot_id}")
    assert archived.status_code == 200, archived.text
    assert archived.json() == {"bot_id": bot_id, "status": "archived"}
    assert again.status_code == 409
    assert again.json()["error_category"] == "bot_already_archived"
    assert patched.status_code == 409
    assert patched.json()["error_category"] == "bot_archived"
    assert fetched.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_list_filter_and_invalid_status(app) -> None:
    async with _client(app) as client:
        first = await client.post("/api/bots", json=_body(display_name="Alice"))
        await client.post("/api/bots", json=_body(display_name="Bob"))
        await client.post(f"/api/bots/{first.json()['bot_id']}/archive", json={})
        active = await client.get("/api/bots?status=active")
        archived = await client.get("/api/bots?status=archived")
        invalid = await client.get("/api/bots?status=paused")
    assert [item["display_name"] for item in active.json()["items"]] == ["Bob"]
    assert [item["display_name"] for item in archived.json()["items"]] == ["Alice"]
    assert invalid.status_code == 400
    assert invalid.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_invalid_create_body_is_400(app) -> None:
    async with _client(app) as client:
        res = await client.post("/api/bots", json={"display_name": "Alice"})
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_concurrent_create_same_name_leaves_one_row(app, tmp_path: Path) -> None:
    async with _client(app) as first, _client(app) as second:
        left, right = await asyncio.gather(
            first.post("/api/bots", json=_body(display_name="Alice")),
            second.post("/api/bots", json=_body(display_name="alice")),
        )
    assert sorted([left.status_code, right.status_code]) == [201, 409]
    assert _bot_rows(tmp_path) == 1