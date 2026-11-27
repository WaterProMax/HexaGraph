from __future__ import annotations

from pathlib import Path

import pytest

from app.bots.registry import BotRegistry
from app.memory.access import MemoryAccessService, MemoryForbidden
from app.memory.store import MemoryStore
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.memory import MemoryCreate
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "memory-access.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


def _bot(name: str) -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref="dashscope",
        model="qwen-plus",
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
    )


async def _seed(factory):
    async with factory() as session:
        first = await BotRegistry(session).create(_bot("B1"))
        second = await BotRegistry(session).create(_bot("B2"))
        await session.commit()
    async with factory() as session:
        service = MembershipService(session, project_exists=lambda _pid: True)
        await service.add("P1", MembershipCreate(bot_id=first.bot_id, role_in_project="dev"))
        await service.add("P1", MembershipCreate(bot_id=second.bot_id, role_in_project="dev"))
        await session.commit()
    async with factory() as session:
        store = MemoryStore(session)
        private = await store.create(
            MemoryCreate(
                owner_bot_id=first.bot_id,
                visibility="private",
                sources=[],
                body={"text": "private-v1"},
            )
        )
        await store.append_version(private.mem_id, 1, body={"text": "private-v2"})
        project = await store.create(
            MemoryCreate(
                owner_bot_id=first.bot_id,
                project_id="P1",
                visibility="project",
                sources=[],
                body={"text": "project"},
            )
        )
        await session.commit()
    return first.bot_id, second.bot_id, private.mem_id, project.mem_id


async def _remove(factory, bot_id: str) -> None:
    async with factory() as session:
        await MembershipService(session, project_exists=lambda _pid: True).remove("P1", bot_id)
        await session.commit()


@pytest.mark.asyncio
async def test_other_bot_cannot_read_private_memory(factory) -> None:
    _b1, b2, private_id, _project_id = await _seed(factory)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        with pytest.raises(MemoryForbidden):
            await access.get(b2, private_id)
    async with factory() as session:
        assert (await MemoryStore(session).get(private_id, 1)).body == {"text": "private-v1"}


@pytest.mark.asyncio
async def test_project_member_can_read_project_memory(factory) -> None:
    _b1, b2, _private_id, project_id = await _seed(factory)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        record = await access.get(b2, project_id)
    assert record.body == {"text": "project"}


@pytest.mark.asyncio
async def test_owner_keeps_private_history_after_membership_removal(factory) -> None:
    b1, _b2, private_id, _project_id = await _seed(factory)
    await _remove(factory, b1)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        first = await access.get(b1, private_id, 1)
        latest = await access.get(b1, private_id)
    assert first.body == {"text": "private-v1"}
    assert latest.body == {"text": "private-v2"}


@pytest.mark.asyncio
async def test_removed_member_loses_project_visibility_but_rows_remain(factory) -> None:
    b1, b2, private_id, project_id = await _seed(factory)
    await _remove(factory, b1)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        with pytest.raises(MemoryForbidden):
            await access.get(b1, project_id)
        assert (await access.get(b2, project_id)).body == {"text": "project"}
        assert [item.mem_id for item in await access.list_visible(b1)] == [private_id]
        assert [item.mem_id for item in await access.list_visible(b2)] == [project_id]
        assert (await MemoryStore(session).get(project_id)).body == {"text": "project"}


@pytest.mark.asyncio
async def test_write_permissions_follow_visibility(factory) -> None:
    b1, b2, _private_id, _project_id = await _seed(factory)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        with pytest.raises(MemoryForbidden):
            await access.create(
                b2,
                MemoryCreate(
                    owner_bot_id=b1,
                    visibility="private",
                    sources=[],
                    body={"text": "not-mine"},
                ),
            )
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        created = await access.create(
            b2,
            MemoryCreate(
                owner_bot_id=b2,
                project_id="P1",
                visibility="project",
                sources=[],
                body={"text": "member-write"},
            ),
        )
        await session.commit()
    assert created.owner_bot_id == b2 and created.visibility == "project"
    await _remove(factory, b1)
    async with factory() as session:
        access = MemoryAccessService(MemoryStore(session))
        with pytest.raises(MemoryForbidden):
            await access.create(
                b1,
                MemoryCreate(
                    owner_bot_id=b1,
                    project_id="P1",
                    visibility="project",
                    sources=[],
                    body={"text": "removed-write"},
                ),
            )