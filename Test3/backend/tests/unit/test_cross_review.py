from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.agents.runtime import RoleRegistry
from app.bots.registry import BotRegistry
from app.discussion.converge import build_round_state
from app.discussion.cross_review import (
    DuplicateReview,
    ProposalNotFound,
    SelfReviewForbidden,
    proposal_spread,
    proposal_totals,
    score_spread,
    submit_review,
)
from app.discussion.models import ReviewBallot
from app.discussion.proposals import start_round, submit_proposal
from app.discussion.session_store import (
    DiscussionSessionStore,
    InvalidStatus,
    NotParticipant,
)
from app.leader.steward import DiscussionSteward
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import DiscussionProposalRow, DiscussionReviewRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "p4-review.db"
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


async def _seeded(factory, *, submit_all: bool = True):
    async with factory() as session:
        bots = [await BotRegistry(session).create(_bot(name)) for name in ["Leader", "Alice", "Bob", "Carol"]]
        await session.commit()
    leader, alice, bob, carol = [bot.bot_id for bot in bots]
    async with factory() as session:
        membership = MembershipService(session, project_exists=lambda _pid: True)
        await membership.add("P1", MembershipCreate(bot_id=leader, role_in_project="dev", is_leader=True))
        for bot_id in (alice, bob, carol):
            await membership.add("P1", MembershipCreate(bot_id=bot_id, role_in_project="dev"))
        await session.commit()
    async with factory() as session:
        record = await DiscussionSteward(session, project_exists=lambda _pid: True).create_session(
            "P1", leader, [alice, bob, carol], {"text": "req"}
        )
        await session.commit()
    async with factory() as session:
        await DiscussionSteward(session, project_exists=lambda _pid: True).group(
            record.session_id, actor_bot_id=leader, participant_bot_ids=[alice, bob, carol]
        )
        await session.commit()
    async with factory() as session:
        await start_round(record.session_id, actor_bot_id=leader, session=session)
        await session.commit()
    async with factory() as session:
        alice_result = await submit_proposal(record.session_id, alice, "Alice-plan", session=session)
        await session.commit()
    if submit_all:
        async with factory() as session:
            await submit_proposal(record.session_id, bob, "Bob-plan", session=session)
            await submit_proposal(record.session_id, carol, "Carol-plan", session=session)
            await session.commit()
    return leader, alice, bob, carol, record.session_id, alice_result["proposal_id"]


def _ballot(
    reviewer: str,
    proposal_id: str,
    *,
    with_justification: bool = True,
    score: int = 4,
) -> ReviewBallot:
    return ReviewBallot(
        reviewer_bot_id=reviewer,
        proposal_id=proposal_id,
        scores={"coverage": score, "evidence": 3},
        score_justification={"coverage": "ok", "evidence": "ok"} if with_justification else {},
        hard_gate_results={
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        dissent_items=[],
    )


async def _review_count(factory) -> int:
    async with factory() as session:
        return (
            await session.execute(select(func.count()).select_from(DiscussionReviewRow))
        ).scalar_one()


@pytest.mark.asyncio
async def test_review_is_persisted(factory) -> None:
    _leader, _alice, bob, _carol, session_id, proposal_id = await _seeded(factory)
    async with factory() as session:
        result = await submit_review(session_id, _ballot(bob, proposal_id), session=session)
        await session.commit()
    assert result["reviewer_bot_id"] == bob
    async with factory() as session:
        row = await session.get(DiscussionReviewRow, result["review_id"])
    assert row is not None
    assert row.payload["scores"] == {"coverage": 4, "evidence": 3}
    assert row.payload["score_justification"] == {"coverage": "ok", "evidence": "ok"}


@pytest.mark.asyncio
async def test_self_review_is_forbidden_without_a_row(factory) -> None:
    _leader, alice, _bob, _carol, session_id, proposal_id = await _seeded(factory)
    async with factory() as session:
        with pytest.raises(SelfReviewForbidden):
            await submit_review(session_id, _ballot(alice, proposal_id), session=session)
        await session.rollback()
    assert await _review_count(factory) == 0


@pytest.mark.asyncio
async def test_missing_justification_is_invalid() -> None:
    with pytest.raises(ValidationError):
        _ballot("reviewer", "proposal", with_justification=False)


@pytest.mark.asyncio
async def test_review_before_cross_review_is_invalid(factory) -> None:
    _leader, alice, bob, _carol, session_id, proposal_id = await _seeded(factory, submit_all=False)
    async with factory() as session:
        with pytest.raises(InvalidStatus):
            await submit_review(session_id, _ballot(bob, proposal_id), session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_non_participant_and_missing_proposal_are_rejected(factory) -> None:
    _leader, _alice, bob, _carol, session_id, proposal_id = await _seeded(factory)
    async with factory() as session:
        with pytest.raises(NotParticipant):
            await submit_review(session_id, _ballot("outsider", proposal_id), session=session)
        await session.rollback()
    async with factory() as session:
        with pytest.raises(ProposalNotFound):
            await submit_review(session_id, _ballot(bob, "no-such-proposal"), session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_duplicate_review_is_rejected(factory) -> None:
    _leader, _alice, bob, _carol, session_id, proposal_id = await _seeded(factory)
    async with factory() as session:
        await submit_review(session_id, _ballot(bob, proposal_id), session=session)
        await session.commit()
    async with factory() as session:
        with pytest.raises(DuplicateReview):
            await submit_review(session_id, _ballot(bob, proposal_id), session=session)
        await session.rollback()
    assert await _review_count(factory) == 1


@pytest.mark.asyncio
async def test_concurrent_reviewers_create_two_rows(factory) -> None:
    _leader, _alice, bob, carol, session_id, proposal_id = await _seeded(factory)

    async def review(reviewer: str) -> None:
        async with factory() as session:
            await submit_review(session_id, _ballot(reviewer, proposal_id), session=session)
            await session.commit()

    await asyncio.gather(review(bob), review(carol))
    assert await _review_count(factory) == 2


def test_score_spread_is_not_referenced_by_submit_review() -> None:
    assert "score_spread" not in inspect.getsource(submit_review)
    assert score_spread([_ballot("a", "p", score=3), _ballot("b", "p", score=5)]) == 2.0


def test_proposal_totals_averages_ballots_per_proposal() -> None:
    ballots = [
        _ballot("a", "p1", score=4),
        _ballot("b", "p1", score=5),
        _ballot("c", "p2", score=2),
    ]
    assert proposal_totals(ballots) == {"p1": 7.5, "p2": 5.0}


def test_proposal_totals_and_spread_handle_empty_input() -> None:
    assert proposal_totals([]) == {}
    assert proposal_spread([]) is None
    assert proposal_spread([_ballot("a", "p1")]) is None


def test_proposal_spread_is_zero_for_tied_averages() -> None:
    ballots = [_ballot("a", "p1", score=4), _ballot("b", "p2", score=4)]
    assert proposal_spread(ballots) == 0.0


def test_proposal_spread_respects_proposal_ids_and_skips_unscored() -> None:
    ballots = [
        _ballot("a", "p1", score=4),
        _ballot("b", "p2", score=5),
        _ballot("c", "p3", score=1),
        _ballot("d", "p5", score=5),
    ]
    assert proposal_spread(ballots) == 4.0
    assert proposal_spread(ballots, ["p1", "p2"]) == 1.0
    assert proposal_spread(ballots, ["p1", "p3", "p4"]) == 3.0
    assert proposal_spread(ballots, ["p1"]) is None
    assert proposal_spread(ballots, ["p4", "p6"]) is None
    assert proposal_spread(ballots, []) is None


@pytest.mark.asyncio
async def test_build_round_state_uses_current_round_proposal_spread(factory) -> None:
    _leader, alice, bob, _carol, session_id, _proposal_id = await _seeded(factory)
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(DiscussionProposalRow).where(
                        DiscussionProposalRow.session_id == session_id
                    )
                )
            ).scalars()
        )
    proposal_by_author = {row.author_bot_id: row.proposal_id for row in rows}
    async with factory() as session:
        await submit_review(
            session_id,
            _ballot(bob, proposal_by_author[alice], score=5),
            session=session,
        )
        await submit_review(
            session_id,
            _ballot(alice, proposal_by_author[bob], score=3),
            session=session,
        )
        await session.commit()
    async with factory() as session:
        record = await DiscussionSessionStore(session).get(session_id)
        state = await build_round_state(session, record)
    assert state.score_spread == 2.0


@pytest.mark.asyncio
async def test_build_round_state_without_reviews_has_no_spread(factory) -> None:
    _leader, _alice, _bob, _carol, session_id, _proposal_id = await _seeded(factory)
    async with factory() as session:
        record = await DiscussionSessionStore(session).get(session_id)
        state = await build_round_state(session, record)
    assert state.score_spread is None


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


async def _http_cross_reviewed(tmp_path):
    app = _app(tmp_path)
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = (await client.post("/api/bots", json=_bot_body("Leader"))).json()["bot_id"]
        alice = (await client.post("/api/bots", json=_bot_body("Alice"))).json()["bot_id"]
        bob = (await client.post("/api/bots", json=_bot_body("Bob"))).json()["bot_id"]
        for bot_id, is_leader in ((leader, True), (alice, False), (bob, False)):
            await client.post(
                f"/api/projects/{p1}/memberships",
                json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": is_leader},
            )
        created = await client.post(
            f"/api/projects/{p1}/discussion-sessions",
            json={
                "leader_bot_id": leader,
                "participant_bot_ids": [alice, bob],
                "requirement_snapshot": {"text": "req"},
            },
            headers={"X-Bot-Id": leader},
        )
        session_id = created.json()["session_id"]
        await client.post(
            f"/api/discussion-sessions/{session_id}/group",
            json={"participant_bot_ids": [alice, bob]},
            headers={"X-Bot-Id": leader},
        )
        await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={},
            headers={"X-Bot-Id": leader},
        )
        first = await client.post(
            f"/api/discussion-sessions/{session_id}/proposals",
            json={"author_bot_id": alice, "body_md": "Alice-plan"},
            headers={"X-Bot-Id": alice},
        )
        await client.post(
            f"/api/discussion-sessions/{session_id}/proposals",
            json={"author_bot_id": bob, "body_md": "Bob-plan"},
            headers={"X-Bot-Id": bob},
        )
    return app, leader, alice, bob, session_id, first.json()["proposal_id"]


def _review_body(reviewer: str, proposal_id: str, *, with_justification: bool = True) -> dict:
    return {
        "reviewer_bot_id": reviewer,
        "proposal_id": proposal_id,
        "scores": {"coverage": 4},
        "score_justification": {"coverage": "ok"} if with_justification else {},
        "hard_gate_results": {
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        "dissent_items": [],
    }


@pytest.mark.asyncio
async def test_http_review_validation_self_and_mismatch(tmp_path: Path) -> None:
    app, _leader, alice, bob, session_id, proposal_id = await _http_cross_reviewed(tmp_path)
    async with _client(app) as client:
        missing = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(bob, proposal_id, with_justification=False),
            headers={"X-Bot-Id": bob},
        )
        self_review = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(alice, proposal_id),
            headers={"X-Bot-Id": alice},
        )
        mismatch = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(bob, proposal_id),
            headers={"X-Bot-Id": alice},
        )
        valid = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(bob, proposal_id),
            headers={"X-Bot-Id": bob},
        )
    assert missing.status_code == 400
    assert missing.json()["error_category"] == "validation_error"
    assert self_review.status_code == 409
    assert self_review.json()["error_category"] == "self_review_forbidden"
    assert mismatch.status_code == 403
    assert mismatch.json()["error_category"] == "forbidden"
    assert valid.status_code == 201, valid.text
    assert valid.json()["reviewer_bot_id"] == bob
    async with app.state.workbench.db_session() as session:
        count = (
            await session.execute(select(func.count()).select_from(DiscussionReviewRow))
        ).scalar_one()
    assert count == 1