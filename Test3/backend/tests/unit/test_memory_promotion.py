from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.bots.registry import BotRegistry
from app.memory.access import MemoryForbidden
from app.memory.promotion import MemoryPromotionService, VisibilityNotProject
from app.memory.store import MemoryStore, MemoryVersionConflict, SecretInBody
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.memory import MemoryCreate, MemorySource


@pytest.fixture
async def factory(tmp_path: Path):
    from app.storage.db import make_engine, session_factory, sqlite_url
    from app.storage.migrate import upgrade_database

    db = tmp_path / "memory-promotion.db"
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


async def _seed_project_memory(factory):
    async with factory() as session:
        owner = await BotRegistry(session).create(_bot("Owner"))
        outsider = await BotRegistry(session).create(_bot("Outsider"))
        await session.commit()
    async with factory() as session:
        service = MembershipService(session, project_exists=lambda _pid: True)
        await service.add(
            "P1", MembershipCreate(bot_id=owner.bot_id, role_in_project="dev")
        )
        await session.commit()
    async with factory() as session:
        record = await MemoryStore(session).create(
            MemoryCreate(
                owner_bot_id=owner.bot_id,
                project_id="P1",
                visibility="project",
                sources=[MemorySource(kind="doc", ref="notes.md", sha="v1")],
                body={"text": "v1"},
                title="project note",
            )
        )
        await session.commit()
    return owner.bot_id, outsider.bot_id, record.mem_id


@pytest.mark.asyncio
async def test_publish_project_memory_records_promoter(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        record = await MemoryPromotionService(MemoryStore(session)).publish(
            mem_id, 1, actor=owner
        )
        await session.commit()
    assert record.status == "published"
    assert record.promoted_by == owner
    assert record.promoted_at
    assert record.body == {"text": "v1"}


@pytest.mark.asyncio
async def test_private_memory_cannot_be_published(factory) -> None:
    owner, _outsider, _mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        record = await MemoryStore(session).create(
            MemoryCreate(
                owner_bot_id=owner,
                visibility="private",
                sources=[],
                body={"text": "private"},
            )
        )
        await session.commit()
    async with factory() as session:
        with pytest.raises(VisibilityNotProject):
            await MemoryPromotionService(MemoryStore(session)).publish(
                record.mem_id, 1, actor=owner
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_non_member_cannot_publish(factory) -> None:
    _owner, outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        with pytest.raises(MemoryForbidden):
            await MemoryPromotionService(MemoryStore(session)).publish(
                mem_id, 1, actor=outsider
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_supersede_marks_old_and_creates_pending_new_version(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(mem_id, 1, actor=owner)
        await session.commit()
    async with factory() as session:
        new = await MemoryPromotionService(MemoryStore(session)).supersede(
            mem_id,
            1,
            body={"text": "v2"},
            sources=[MemorySource(kind="doc", ref="notes.md", sha="v2")],
            actor=owner,
        )
        await session.commit()
    assert new.version == 2 and new.status == "pending"
    async with factory() as session:
        store = MemoryStore(session)
        old = await store.get(mem_id, 1)
        latest = await store.get(mem_id)
    assert old.status == "superseded"
    assert old.body == {"text": "v1"}
    assert old.promoted_by == owner
    assert latest.version == 2 and latest.body == {"text": "v2"}


@pytest.mark.asyncio
async def test_publish_expected_version_mismatch_is_conflict(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        store = MemoryStore(session)
        await store.append_version(mem_id, 1, body={"text": "v2"})
        await session.commit()
    async with factory() as session:
        with pytest.raises(MemoryVersionConflict):
            await MemoryPromotionService(MemoryStore(session)).publish(
                mem_id, 1, actor=owner
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_publish_is_idempotent_conflict_after_published(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(mem_id, 1, actor=owner)
        await session.commit()
    async with factory() as session:
        with pytest.raises(MemoryVersionConflict):
            await MemoryPromotionService(MemoryStore(session)).publish(
                mem_id, 1, actor=owner
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_supersede_secret_is_rejected_without_new_version(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(mem_id, 1, actor=owner)
        await session.commit()
    async with factory() as session:
        with pytest.raises(SecretInBody):
            await MemoryPromotionService(MemoryStore(session)).supersede(
                mem_id,
                1,
                body={"api_key": "sk-leak"},
                sources=[],
                actor=owner,
            )
        await session.rollback()
    async with factory() as session:
        store = MemoryStore(session)
        assert (await store.get(mem_id, 1)).status == "published"
        assert (await store.get(mem_id)).version == 1


@pytest.mark.asyncio
async def test_concurrent_publish_has_one_winner(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)

    async def publish() -> str:
        async with factory() as session:
            try:
                await MemoryPromotionService(MemoryStore(session)).publish(
                    mem_id, 1, actor=owner
                )
                await session.commit()
                return "ok"
            except MemoryVersionConflict:
                await session.rollback()
                return "conflict"
            except Exception as exc:  # surfaced by the assertion below
                await session.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(publish(), publish())
    assert sorted(results) == ["conflict", "ok"]
    async with factory() as session:
        record = await MemoryStore(session).get(mem_id)
    assert record.status == "published"
    assert record.promoted_by == owner


@pytest.mark.asyncio
async def test_concurrent_supersede_creates_only_one_new_version(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(mem_id, 1, actor=owner)
        await session.commit()

    async def supersede(text_value: str) -> str:
        async with factory() as session:
            try:
                await MemoryPromotionService(MemoryStore(session)).supersede(
                    mem_id,
                    1,
                    body={"text": text_value},
                    sources=[],
                    actor=owner,
                )
                await session.commit()
                return "ok"
            except MemoryVersionConflict:
                await session.rollback()
                return "conflict"
            except Exception as exc:  # surfaced by the assertion below
                await session.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(supersede("a"), supersede("b"))
    assert sorted(results) == ["conflict", "ok"]
    async with factory() as session:
        store = MemoryStore(session)
        versions = await store.list(latest_only=False)
        old = await store.get(mem_id, 1)
    assert sorted(item.version for item in versions) == [1, 2]
    assert old.status == "superseded"

@pytest.mark.asyncio
async def test_non_existent_expected_version_is_conflict_not_missing(factory) -> None:
    owner, _outsider, mem_id = await _seed_project_memory(factory)
    async with factory() as session:
        with pytest.raises(MemoryVersionConflict):
            await MemoryPromotionService(MemoryStore(session)).publish(
                mem_id, 99, actor=owner
            )
        await session.rollback()
