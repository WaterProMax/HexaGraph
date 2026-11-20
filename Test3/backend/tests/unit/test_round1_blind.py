from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bots.registry import BotRegistry
from app.discussion.models import DiscussionBudget
from app.discussion.proposals import (
    BudgetExhausted,
    DuplicateProposal,
    list_proposals,
    open_cross_review,
    start_round,
    submit_proposal,
)
from app.discussion.session_store import DiscussionSessionStore, Forbidden, InvalidStatus, NotParticipant
from app.leader.steward import DiscussionSteward
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import DiscussionProposalRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "p4-round1.db"
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


async def _seeded(factory, *, max_rounds: int = 3):
    async with factory() as session:
        bots = [await BotRegistry(session).create(_bot(name)) for name in ["Leader", "Alice", "Bob"]]
        await session.commit()
    leader, alice, bob = [bot.bot_id for bot in bots]
    async with factory() as session:
        membership = MembershipService(session, project_exists=lambda _pid: True)
        await membership.add("P1", MembershipCreate(bot_id=leader, role_in_project="dev", is_leader=True))
        await membership.add("P1", MembershipCreate(bot_id=alice, role_in_project="dev"))
        await membership.add("P1", MembershipCreate(bot_id=bob, role_in_project="dev"))
        await session.commit()
    steward_budget = DiscussionBudget(max_rounds=max_rounds)
    async with factory() as session:
        record = await DiscussionSteward(session, project_exists=lambda _pid: True).create_session(
            "P1", leader, [alice, bob], {"text": "req"}, steward_budget
        )
        await session.commit()
    async with factory() as session:
        await DiscussionSteward(session, project_exists=lambda _pid: True).group(
            record.session_id, actor_bot_id=leader, participant_bot_ids=[alice, bob]
        )
        await session.commit()
    return leader, alice, bob, record.session_id


async def _start(factory, session_id: str, actor: str):
    async with factory() as session:
        record = await start_round(session_id, actor_bot_id=actor, session=session)
        await session.commit()
        return record


async def _submit(factory, session_id: str, author: str, text: str):
    async with factory() as session:
        result = await submit_proposal(session_id, author, text, session=session)
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_start_round_one_sets_independent_status(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory)
    record = await _start(factory, session_id, leader)
    assert record.status == "round1_independent"
    assert record.current_round == 1
    assert session_id


@pytest.mark.asyncio
async def test_non_leader_cannot_start_round(factory) -> None:
    _leader, alice, _bob, session_id = await _seeded(factory)
    async with factory() as session:
        with pytest.raises(Forbidden):
            await start_round(session_id, actor_bot_id=alice, session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_sealed_list_hides_other_author_body(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory)
    await _start(factory, session_id, leader)
    await _submit(factory, session_id, alice, "Alice-plan")
    async with factory() as session:
        bob_items = await list_proposals(session_id, bob, session=session)
        alice_items = await list_proposals(session_id, alice, session=session)
    assert bob_items[0]["sealed"] is True
    assert bob_items[0]["body_md"] is None
    assert "Alice-plan" not in json.dumps(bob_items)
    assert alice_items[0]["body_md"] == "Alice-plan"


@pytest.mark.asyncio
async def test_all_submissions_unseal_and_open_cross_review(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory)
    await _start(factory, session_id, leader)
    await _submit(factory, session_id, alice, "Alice-plan")
    result = await _submit(factory, session_id, bob, "Bob-plan")
    assert result["sealed"] is False
    async with factory() as session:
        record = await DiscussionSessionStore(session).get(session_id)
        alice_items = await list_proposals(session_id, alice, session=session)
        bob_items = await list_proposals(session_id, bob, session=session)
    assert record.status == "cross_review"
    assert {item["body_md"] for item in alice_items} == {"Alice-plan", "Bob-plan"}
    assert {item["body_md"] for item in bob_items} == {"Alice-plan", "Bob-plan"}
    assert all(item["sealed"] is False for item in alice_items)


@pytest.mark.asyncio
async def test_duplicate_and_non_participant_are_rejected(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory)
    await _start(factory, session_id, leader)
    await _submit(factory, session_id, alice, "Alice-plan")
    async with factory() as session:
        with pytest.raises(DuplicateProposal):
            await submit_proposal(session_id, alice, "again", session=session)
        await session.rollback()
    async with factory() as session:
        with pytest.raises(NotParticipant):
            await submit_proposal(session_id, "outsider", "not allowed", session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_open_cross_review_before_complete_is_invalid(factory) -> None:
    leader, alice, _bob, session_id = await _seeded(factory)
    await _start(factory, session_id, leader)
    await _submit(factory, session_id, alice, "Alice-plan")
    async with factory() as session:
        with pytest.raises(InvalidStatus):
            await open_cross_review(session_id, session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_list_before_start_is_invalid(factory) -> None:
    _leader, alice, _bob, session_id = await _seeded(factory)
    async with factory() as session:
        with pytest.raises(InvalidStatus):
            await list_proposals(session_id, alice, session=session)


@pytest.mark.asyncio
async def test_budget_exhaustion_sets_status(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory, max_rounds=1)
    await _start(factory, session_id, leader)
    await _submit(factory, session_id, alice, "Alice-plan")
    await _submit(factory, session_id, bob, "Bob-plan")
    async with factory() as session:
        with pytest.raises(BudgetExhausted):
            await start_round(session_id, actor_bot_id=leader, session=session)
        await session.commit()
    async with factory() as session:
        record = await DiscussionSessionStore(session).get(session_id)
    assert record.status == "budget_exhausted"


@pytest.mark.asyncio
async def test_concurrent_submissions_leave_both_proposals(factory) -> None:
    leader, alice, bob, session_id = await _seeded(factory)
    await _start(factory, session_id, leader)

    async def submit(author: str, text: str) -> None:
        async with factory() as session:
            await submit_proposal(session_id, author, text, session=session)
            await session.commit()

    await asyncio.gather(submit(alice, "Alice-plan"), submit(bob, "Bob-plan"))
    async with factory() as session:
        record = await DiscussionSessionStore(session).get(session_id)
        items = await list_proposals(session_id, alice, session=session)
        count = (
            await session.execute(
                select(func.count())
                .select_from(DiscussionProposalRow)
                .where(DiscussionProposalRow.session_id == session_id)
            )
        ).scalar_one()
    assert record.status == "cross_review"
    assert {item["body_md"] for item in items} == {"Alice-plan", "Bob-plan"}
    assert count == 2