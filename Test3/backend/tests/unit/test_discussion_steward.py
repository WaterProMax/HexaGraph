from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bots.registry import BotRegistry
from app.discussion.session_store import DiscussionSessionStore
from app.execution.baseline import hash_artifact
from app.leader.steward import (
    DiscussionSteward,
    Forbidden,
    InvalidParticipant,
    LeaderNotInProject,
)
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import DiscussionSessionRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "p4-steward.db"
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


async def _bots(factory, count: int) -> list[str]:
    names = ["Leader", "Alice", "Bob", "Carol", "Dave"]
    async with factory() as session:
        bots = [await BotRegistry(session).create(_bot(names[i])) for i in range(count)]
        await session.commit()
    return [bot.bot_id for bot in bots]


async def _one_bot(factory, name: str) -> str:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot(name))
        await session.commit()
        return bot.bot_id


async def _member(factory, project_id: str, bot_id: str, *, leader: bool = False) -> None:
    async with factory() as session:
        await MembershipService(session, project_exists=lambda _pid: True).add(
            project_id,
            MembershipCreate(bot_id=bot_id, role_in_project="dev", is_leader=leader),
        )
        await session.commit()


async def _seeded(factory, count: int = 3) -> list[str]:
    bots = await _bots(factory, count)
    await _member(factory, "P1", bots[0], leader=True)
    for bot_id in bots[1:]:
        await _member(factory, "P1", bot_id)
    return bots


def _steward(session) -> DiscussionSteward:
    return DiscussionSteward(session, project_exists=lambda pid: pid == "P1")


async def _count_sessions(factory) -> int:
    async with factory() as session:
        return (
            await session.execute(select(func.count()).select_from(DiscussionSessionRow))
        ).scalar_one()


@pytest.mark.asyncio
async def test_create_session_uses_leader_and_default_budget(factory) -> None:
    leader, alice, bob = await _seeded(factory)
    async with factory() as session:
        record = await _steward(session).create_session(
            "P1", leader, [leader, alice, bob], {"text": "requirement"}
        )
        await session.commit()
    assert record.status == "draft"
    assert record.current_round == 0
    assert record.participant_bot_ids == [leader, alice, bob]
    assert record.budget.max_rounds == 3
    assert record.requirement_snapshot_hash == hash_artifact({"text": "requirement"})
    assert record.decision_package is None


@pytest.mark.asyncio
async def test_group_replaces_participants_and_sets_grouping(factory) -> None:
    leader, alice, bob = await _seeded(factory)
    async with factory() as session:
        record = await _steward(session).create_session(
            "P1", leader, [leader, alice, bob], {"text": "r"}
        )
        await session.commit()
    async with factory() as session:
        grouped = await _steward(session).group(
            record.session_id, actor_bot_id=leader, participant_bot_ids=[leader, alice]
        )
        await session.commit()
    assert grouped.status == "grouping"
    assert grouped.participant_bot_ids == [leader, alice]


@pytest.mark.asyncio
async def test_non_leader_cannot_group(factory) -> None:
    leader, alice, bob = await _seeded(factory)
    async with factory() as session:
        record = await _steward(session).create_session(
            "P1", leader, [leader, alice, bob], {"text": "r"}
        )
        await session.commit()
    async with factory() as session:
        with pytest.raises(Forbidden):
            await _steward(session).group(
                record.session_id, actor_bot_id=alice, participant_bot_ids=[alice]
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_non_leader_bot_cannot_create_session(factory) -> None:
    leader, alice, _bob = await _seeded(factory)
    async with factory() as session:
        with pytest.raises(LeaderNotInProject):
            await _steward(session).create_session(
                "P1", alice, [leader, alice], {"text": "r"}
            )
        await session.rollback()
    assert await _count_sessions(factory) == 0


@pytest.mark.asyncio
async def test_non_member_participant_is_rejected_without_session(factory) -> None:
    leader, alice, _bob = await _seeded(factory)
    outsider = await _one_bot(factory, "Outsider")
    async with factory() as session:
        with pytest.raises(InvalidParticipant):
            await _steward(session).create_session(
                "P1", leader, [alice, outsider], {"text": "r"}
            )
        await session.rollback()
    assert await _count_sessions(factory) == 0


@pytest.mark.asyncio
async def test_five_participants_are_allowed(factory) -> None:
    bots = await _seeded(factory, 5)
    async with factory() as session:
        record = await _steward(session).create_session(
            "P1", bots[0], bots, {"text": "r"}
        )
        await session.commit()
    assert record.participant_bot_ids == bots


@pytest.mark.asyncio
async def test_concurrent_group_leaves_one_complete_list(factory) -> None:
    bots = await _seeded(factory, 5)
    leader = bots[0]
    async with factory() as session:
        record = await _steward(session).create_session(
            "P1", leader, bots, {"text": "r"}
        )
        await session.commit()

    async def group(participants: list[str]) -> None:
        async with factory() as session:
            await _steward(session).group(
                record.session_id, actor_bot_id=leader, participant_bot_ids=participants
            )
            await session.commit()

    first = [leader, bots[1]]
    second = [leader, bots[2], bots[3], bots[4]]
    await asyncio.gather(group(first), group(second))
    async with factory() as session:
        stored = await DiscussionSessionStore(session).get(record.session_id)
    assert stored.status == "grouping"
    assert stored.participant_bot_ids in (first, second)