from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.memory.access import MemoryAccessService, MemoryForbidden
from app.memory.store import MemoryStore
from app.schemas.memory import MemoryCreate
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import MemoryRecordRow


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


async def _add_member(client: AsyncClient, project_id: str, bot_id: str) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": False},
    )
    assert res.status_code == 201, res.text


async def _seed_memories(bench, owner_bot_id: str, project_id: str):
    async with bench.db_session() as session:
        store = MemoryStore(session)
        private = await store.create(
            MemoryCreate(
                owner_bot_id=owner_bot_id,
                visibility="private",
                sources=[],
                body={"text": "private-v1"},
            )
        )
        await store.append_version(private.mem_id, 1, body={"text": "private-v2"})
        project = await store.create(
            MemoryCreate(
                owner_bot_id=owner_bot_id,
                project_id=project_id,
                visibility="project",
                sources=[],
                body={"text": "project"},
            )
        )
        await session.commit()
    return private.mem_id, project.mem_id


async def _memory_count(bench) -> int:
    async with bench.db_session() as session:
        return (
            await session.execute(select(func.count()).select_from(MemoryRecordRow))
        ).scalar_one()


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_removed_member_keeps_private_history_and_memory_rows(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        b1 = await _create_bot(client, "B1")
        b2 = await _create_bot(client, "B2")
        await _add_member(client, p1, b1)
        await _add_member(client, p1, b2)
    private_id, project_id = await _seed_memories(bench, b1, p1)
    before = await _memory_count(bench)

    async with _client(app) as client:
        removed = await client.delete(f"/api/projects/{p1}/memberships/{b1}")
        bot = await client.get(f"/api/bots/{b1}")
    assert removed.status_code == 204
    assert bot.status_code == 200

    async with bench.db_session() as session:
        access = MemoryAccessService(MemoryStore(session))
        assert (await access.get(b1, private_id, 1)).body == {"text": "private-v1"}
        assert (await access.get(b1, private_id)).body == {"text": "private-v2"}
        with pytest.raises(MemoryForbidden):
            await access.get(b1, project_id)
        assert (await access.get(b2, project_id)).body == {"text": "project"}
        assert (await MemoryStore(session).get(project_id)).body == {"text": "project"}
    assert await _memory_count(bench) == before == 3


@pytest.mark.asyncio
async def test_concurrent_read_and_membership_delete_never_500(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        b1 = await _create_bot(client, "B1")
        b2 = await _create_bot(client, "B2")
        await _add_member(client, p1, b1)
        await _add_member(client, p1, b2)
    private_id, project_id = await _seed_memories(bench, b1, p1)
    before = await _memory_count(bench)

    async def read_history():
        async with bench.db_session() as session:
            access = MemoryAccessService(MemoryStore(session))
            first = await access.get(b1, private_id, 1)
            latest = await access.get(b1, private_id)
            try:
                await access.get(b1, project_id)
                project_state = "visible"
            except MemoryForbidden:
                project_state = "forbidden"
            return first.body, latest.body, project_state

    async with _client(app) as client:
        private_bodies, delete_result = await asyncio.gather(
            read_history(),
            client.delete(f"/api/projects/{p1}/memberships/{b1}"),
        )
    assert delete_result.status_code == 204
    assert private_bodies[0] == {"text": "private-v1"}
    assert private_bodies[1] == {"text": "private-v2"}
    assert private_bodies[2] in {"visible", "forbidden"}

    async with bench.db_session() as session:
        access = MemoryAccessService(MemoryStore(session))
        with pytest.raises(MemoryForbidden):
            await access.get(b1, project_id)
        assert (await access.get(b2, project_id)).body == {"text": "project"}
    assert await _memory_count(bench) == before == 3