from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bots.registry import BotArchived, BotRegistry
from app.projects.membership import (
    LeaderAlreadySet,
    MembershipCreate,
    MembershipExists,
    MembershipNotFound,
    MembershipService,
    ProjectNotFound,
)
from app.schemas.bot import BotCreate
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import ProjectMembershipRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "membership.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


async def _bot(factory, name: str) -> str:
    async with factory() as session:
        bot = await BotRegistry(session).create(
            BotCreate(
                display_name=name,
                role_template="developer",
                provider_ref="dashscope",
                model="qwen-plus",
                slot="coder",
                secret_ref="DASHSCOPE_API_KEY",
            )
        )
        await session.commit()
        return bot.bot_id


def _service(session) -> MembershipService:
    return MembershipService(session, project_exists=lambda project_id: True)


@pytest.mark.asyncio
async def test_same_bot_can_join_multiple_projects(factory) -> None:

    bot_id = await _bot(factory, "Alice")
    async with factory() as session:
        service = _service(session)
        first = await service.add("P1", MembershipCreate(bot_id=bot_id, role_in_project="dev", is_leader=True))
        second = await service.add("P2", MembershipCreate(bot_id=bot_id, role_in_project="dev", is_leader=True))
        await session.commit()
    assert first.project_id == "P1" and first.is_leader is True
    assert second.project_id == "P2"
    async with factory() as session:
        service = _service(session)
        assert [m.bot_id for m in await service.list("P1")] == [bot_id]
        assert [m.bot_id for m in await service.list("P2")] == [bot_id]


@pytest.mark.asyncio
async def test_second_leader_is_rejected(factory) -> None:

    first_bot = await _bot(factory, "Alice")
    second_bot = await _bot(factory, "Bob")
    async with factory() as session:
        await _service(session).add(
            "P1", MembershipCreate(bot_id=first_bot, role_in_project="dev", is_leader=True)
        )
        await session.commit()
    async with factory() as session:
        with pytest.raises(LeaderAlreadySet):
            await _service(session).add(
                "P1", MembershipCreate(bot_id=second_bot, role_in_project="dev", is_leader=True)
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_duplicate_membership_is_rejected(factory) -> None:

    bot_id = await _bot(factory, "Alice")
    async with factory() as session:
        await _service(session).add(
            "P1", MembershipCreate(bot_id=bot_id, role_in_project="dev")
        )
        await session.commit()
    async with factory() as session:
        with pytest.raises(MembershipExists):
            await _service(session).add(
                "P1", MembershipCreate(bot_id=bot_id, role_in_project="qa")
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_remove_keeps_bot_row_and_other_projects(factory) -> None:

    bot_id = await _bot(factory, "Alice")
    async with factory() as session:
        service = _service(session)
        await service.add("P1", MembershipCreate(bot_id=bot_id, role_in_project="dev"))
        await service.add("P2", MembershipCreate(bot_id=bot_id, role_in_project="dev"))
        await session.commit()
    async with factory() as session:
        service = _service(session)
        await service.remove("P1", bot_id)
        await session.commit()
        assert await service.list("P1") == []
        assert [m.bot_id for m in await service.list("P2")] == [bot_id]
    async with factory() as session:
        assert (await BotRegistry(session).get(bot_id)).bot_id == bot_id


@pytest.mark.asyncio
async def test_remove_missing_membership_raises(factory) -> None:
    async with factory() as session:
        with pytest.raises(MembershipNotFound):
            await _service(session).remove("P1", "no-such-bot")


@pytest.mark.asyncio
async def test_unknown_project_raises(factory) -> None:
    async with factory() as session:
        service = MembershipService(session, project_exists=lambda project_id: False)
        with pytest.raises(ProjectNotFound):
            await service.list("missing")


@pytest.mark.asyncio
async def test_archived_bot_cannot_join(factory) -> None:

    bot_id = await _bot(factory, "Alice")
    async with factory() as session:
        await BotRegistry(session).archive(bot_id)
        await session.commit()
    async with factory() as session:
        with pytest.raises(BotArchived):
            await _service(session).add(
                "P1", MembershipCreate(bot_id=bot_id, role_in_project="dev")
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_concurrent_leaders_leave_exactly_one(factory) -> None:

    first_bot = await _bot(factory, "Alice")
    second_bot = await _bot(factory, "Bob")

    async def add(bot_id: str) -> str:
        async with factory() as session:
            try:
                await _service(session).add(
                    "P1", MembershipCreate(bot_id=bot_id, role_in_project="dev", is_leader=True)
                )
                await session.commit()
                return "ok"
            except LeaderAlreadySet:
                await session.rollback()
                return "leader_already_set"
            except Exception as exc:  # surfaced by the assertion below
                await session.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(add(first_bot), add(second_bot))
    assert sorted(results) == ["leader_already_set", "ok"]
    async with factory() as session:
        leaders = (
            await session.execute(
                select(func.count())
                .select_from(ProjectMembershipRow)
                .where(ProjectMembershipRow.project_id == "P1", ProjectMembershipRow.is_leader == 1)
            )
        ).scalar_one()
    assert leaders == 1
