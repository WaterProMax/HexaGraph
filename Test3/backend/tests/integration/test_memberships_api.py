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


def _bot_body(name: str) -> dict:
    return {
        "display_name": name,
        "role_template": "developer",
        "provider_ref": "dashscope",
        "model": "qwen-plus",
        "slot": "coder",
        "secret_ref": "DASHSCOPE_API_KEY",
    }


async def _create_bot(client: AsyncClient, name: str) -> str:
    res = await client.post("/api/bots", json=_bot_body(name))
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


async def _add_member(client: AsyncClient, project_id: str, bot_id: str, *, leader: bool = False):
    return await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": leader},
    )


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_bot_joins_two_projects_as_leader(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    p2 = bench.create_project("P2")["id"]
    async with _client(app) as client:
        bot_id = await _create_bot(client, "Alice")
        first = await _add_member(client, p1, bot_id, leader=True)
        second = await _add_member(client, p2, bot_id, leader=True)
        p1_list = await client.get(f"/api/projects/{p1}/memberships")
        p2_list = await client.get(f"/api/projects/{p2}/memberships")
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["is_leader"] is True
    assert [item["bot_id"] for item in p1_list.json()["items"]] == [bot_id]
    assert [item["bot_id"] for item in p2_list.json()["items"]] == [bot_id]


@pytest.mark.asyncio
async def test_second_leader_in_same_project_is_409(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        first = await _create_bot(client, "Alice")
        second = await _create_bot(client, "Bob")
        assert (await _add_member(client, p1, first, leader=True)).status_code == 201
        res = await _add_member(client, p1, second, leader=True)
    assert res.status_code == 409
    assert res.json()["error_category"] == "leader_already_set"


@pytest.mark.asyncio
async def test_delete_membership_keeps_bot_and_other_project(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    p2 = bench.create_project("P2")["id"]
    async with _client(app) as client:
        bot_id = await _create_bot(client, "Alice")
        await _add_member(client, p1, bot_id)
        await _add_member(client, p2, bot_id)
        removed = await client.delete(f"/api/projects/{p1}/memberships/{bot_id}")
        p1_list = await client.get(f"/api/projects/{p1}/memberships")
        p2_list = await client.get(f"/api/projects/{p2}/memberships")
        bot = await client.get(f"/api/bots/{bot_id}")
    assert removed.status_code == 204
    assert p1_list.json()["items"] == []
    assert [item["bot_id"] for item in p2_list.json()["items"]] == [bot_id]
    assert bot.status_code == 200


@pytest.mark.asyncio
async def test_delete_missing_membership_is_404(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        res = await client.delete(f"/api/projects/{p1}/memberships/no-such-bot")
    assert res.status_code == 404
    assert res.json()["error_category"] == "membership_not_found"


@pytest.mark.asyncio
async def test_archived_bot_cannot_join_project(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        bot_id = await _create_bot(client, "Alice")
        await client.post(f"/api/bots/{bot_id}/archive", json={})
        res = await _add_member(client, p1, bot_id)
    assert res.status_code == 403
    assert res.json()["error_category"] == "bot_archived"


@pytest.mark.asyncio
async def test_unknown_project_and_bot_errors(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        missing_project = await client.get("/api/projects/no-such/memberships")
        existing_project = await _create_bot(client, "Alice")
        missing_bot = await _add_member(client, p1, "no-such-bot")
    assert missing_project.status_code == 404
    assert missing_project.json()["error_category"] == "project_not_found"
    assert missing_bot.status_code == 404
    assert missing_bot.json()["error_category"] == "bot_not_found"
    assert existing_project


@pytest.mark.asyncio
async def test_concurrent_leader_set_leaves_one_leader(app) -> None:
    bench = app.state.workbench
    p3 = bench.create_project("P3")["id"]
    async with _client(app) as first, _client(app) as second:
        bot_a = await _create_bot(first, "Alice")
        bot_b = await _create_bot(first, "Bob")
        left, right = await asyncio.gather(
            _add_member(first, p3, bot_a, leader=True),
            _add_member(second, p3, bot_b, leader=True),
        )
        listed = await first.get(f"/api/projects/{p3}/memberships")
    assert sorted([left.status_code, right.status_code]) == [201, 409]
    assert sum(1 for item in listed.json()["items"] if item["is_leader"]) == 1