from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.bots.registry import BotRegistry
from app.discussion.converge import build_round_state, should_converge
from app.discussion.cross_review import submit_review
from app.discussion.decision import (
    CANONICAL_FIELDS,
    decision_package_digest,
    resolve_decision,
    submit_decision,
)
from app.discussion.models import ReviewBallot
from app.discussion.proposals import start_round, submit_proposal
from app.discussion.session_store import DiscussionSessionStore, Forbidden, InvalidStatus
from app.execution.baseline import hash_artifact
from app.execution.run_state_store import read_run_execution_state
from app.leader.steward import DiscussionSteward
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


@pytest.fixture
async def bench(tmp_path: Path):
    workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    yield workbench
    await workbench.close()


def _bot(name: str) -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref="dashscope",
        model="qwen-plus",
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
    )


def _ballot(reviewer: str, proposal_id: str, *, dissent: list[str] | None = None) -> ReviewBallot:
    return ReviewBallot(
        reviewer_bot_id=reviewer,
        proposal_id=proposal_id,
        scores={"coverage": 4},
        score_justification={"coverage": "ok"},
        hard_gate_results={
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        dissent_items=list(dissent or []),
    )


async def _converged(bench):
    project_id = bench.create_project("P1")["id"]
    async with bench.db_session() as session:
        leader = await BotRegistry(session).create(_bot("Leader"))
        alice = await BotRegistry(session).create(_bot("Alice"))
        bob = await BotRegistry(session).create(_bot("Bob"))
        await session.commit()
    async with bench.db_session() as session:
        membership = MembershipService(session, project_exists=lambda _pid: True)
        await membership.add(project_id, MembershipCreate(bot_id=leader.bot_id, role_in_project="dev", is_leader=True))
        await membership.add(project_id, MembershipCreate(bot_id=alice.bot_id, role_in_project="dev"))
        await membership.add(project_id, MembershipCreate(bot_id=bob.bot_id, role_in_project="dev"))
        await session.commit()
    async with bench.db_session() as session:
        record = await DiscussionSteward(session, project_exists=lambda _pid: True).create_session(
            project_id, leader.bot_id, [alice.bot_id, bob.bot_id], "requirement"
        )
        await session.commit()
    async with bench.db_session() as session:
        await DiscussionSteward(session, project_exists=lambda _pid: True).group(
            record.session_id, actor_bot_id=leader.bot_id, participant_bot_ids=[alice.bot_id, bob.bot_id]
        )
        await session.commit()
    async with bench.db_session() as session:
        await start_round(record.session_id, actor_bot_id=leader.bot_id, session=session)
        await session.commit()
    async with bench.db_session() as session:
        alice_proposal = await submit_proposal(record.session_id, alice.bot_id, "Alice-plan", session=session)
        bob_proposal = await submit_proposal(record.session_id, bob.bot_id, "Bob-plan", session=session)
        await session.commit()
    async with bench.db_session() as session:
        await submit_review(
            record.session_id,
            _ballot(bob.bot_id, alice_proposal["proposal_id"], dissent=["风险X"]),
            session=session,
        )
        await submit_review(
            record.session_id,
            _ballot(alice.bot_id, bob_proposal["proposal_id"]),
            session=session,
        )
        await session.commit()
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        stored = await store.get(record.session_id)
        state = await build_round_state(session, stored)
        action, _reason = should_converge(state)
        assert action == "submit_human"
        await store.save(stored.model_copy(update={"status": "converged_pending_human"}))
        await session.commit()
    return project_id, leader.bot_id, alice.bot_id, bob.bot_id, record.session_id


async def _package(bench, session_id: str, leader: str):
    async with bench.db_session() as session:
        package = await submit_decision(
            session_id, "# decision", ["风险X"], actor_bot_id=leader, session=session
        )
        await session.commit()
    return package


def _digest_fields(package) -> dict:
    data = package.model_dump()
    return {field: data[field] for field in CANONICAL_FIELDS}


def test_decision_package_digest_is_canonical_and_not_double_hashed() -> None:
    fields = {
        "session_id": "s1",
        "requirement_snapshot_hash": "r1",
        "proposal_ids": ["p1"],
        "dissent_items": ["风险X"],
        "hard_gate_summary": {"coverage": True},
        "body_md": "# body",
        "decision_id": "ignored",
        "sha256": "ignored",
    }
    digest = decision_package_digest(fields)
    assert len(digest) == 64
    assert digest == hash_artifact({field: fields[field] for field in CANONICAL_FIELDS})
    assert digest != hash_artifact(digest)


@pytest.mark.asyncio
async def test_submit_decision_records_dissent_and_digest(bench) -> None:
    _project, leader, _alice, _bob, session_id = await _converged(bench)
    package = await _package(bench, session_id, leader)
    assert "风险X" in package.dissent_items
    assert len(package.sha256) == 64
    assert package.sha256 == decision_package_digest(_digest_fields(package))
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.status == "converged_pending_human"
    assert stored.decision_package is not None
    assert stored.decision_package.sha256 == package.sha256


@pytest.mark.asyncio
async def test_non_leader_and_double_submit_are_rejected(bench) -> None:
    _project, leader, alice, _bob, session_id = await _converged(bench)
    async with bench.db_session() as session:
        with pytest.raises(Forbidden):
            await submit_decision(session_id, "body", [], actor_bot_id=alice, session=session)
        await session.rollback()
    await _package(bench, session_id, leader)
    async with bench.db_session() as session:
        with pytest.raises(InvalidStatus):
            await submit_decision(session_id, "again", [], actor_bot_id=leader, session=session)
        await session.rollback()


@pytest.mark.asyncio
async def test_non_leader_cannot_resolve(bench) -> None:
    _project, leader, alice, _bob, session_id = await _converged(bench)
    package = await _package(bench, session_id, leader)
    for decision in ("approved", "rejected"):
        async with bench.db_session() as session:
            with pytest.raises(Forbidden):
                await resolve_decision(
                    session_id, decision, actor_bot_id=alice, bench=bench, session=session
                )
            await session.rollback()
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.status == "converged_pending_human"
    assert stored.resolution_comment is None
    assert stored.decision_package == package


@pytest.mark.asyncio
async def test_non_leader_cannot_repeat_approval(bench) -> None:
    _project, leader, alice, _bob, session_id = await _converged(bench)
    await _package(bench, session_id, leader)
    async with bench.db_session() as session:
        approved = await resolve_decision(
            session_id, "approved", actor_bot_id=leader, bench=bench, session=session
        )
        await session.commit()
    assert approved.status == "approved"
    async with bench.db_session() as session:
        with pytest.raises(Forbidden):
            await resolve_decision(
                session_id, "approved", actor_bot_id=alice, bench=bench, session=session
            )
        await session.rollback()
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.status == "approved"
    assert stored.resolution_comment is None


@pytest.mark.asyncio
async def test_resolve_approved_sets_run_hash_without_scheduling(bench, monkeypatch: pytest.MonkeyPatch) -> None:
    project, leader, _alice, _bob, session_id = await _converged(bench)
    package = await _package(bench, session_id, leader)
    run = bench.create_run(project, "idea")

    async def boom(*args, **kwargs):
        raise AssertionError("approved decision must not schedule or execute")

    monkeypatch.setattr(bench, "schedule_once", boom)
    monkeypatch.setattr(bench, "execute_task", boom)
    async with bench.db_session() as session:
        resolved = await resolve_decision(
            session_id, "approved", run_id=run.id, actor_bot_id=leader, bench=bench, session=session
        )
        await session.commit()
    assert resolved.status == "approved"
    assert run.approved_baseline_hashes["DecisionPackage"] == package.sha256
    assert run.artifacts["approved_baseline_hashes"]["DecisionPackage"] == package.sha256
    assert run.execution_profile == "legacy"
    assert bench.execution_safety_ready is False


@pytest.mark.asyncio
async def test_resolve_approved_merges_existing_run_state(bench) -> None:
    project, leader, _alice, _bob, session_id = await _converged(bench)
    package = await _package(bench, session_id, leader)
    run = bench.create_run(project, "idea")
    await bench.persist_run_execution_state(
        run.id,
        "legacy",
        {"SPEC": "old"},
        approved_plan_hash="plan",
        allowed_tool_refs=["python -m pytest"],
    )
    async with bench.db_session() as session:
        await resolve_decision(
            session_id, "approved", run_id=run.id, actor_bot_id=leader, bench=bench, session=session
        )
        await session.commit()
    state = read_run_execution_state(bench.db_path, run.id)
    assert state is not None
    assert state.execution_profile == "legacy"
    assert state.approved_baseline_hashes["SPEC"] == "old"
    assert state.approved_baseline_hashes["DecisionPackage"] == package.sha256
    assert state.approved_plan_hash == "plan"
    assert state.allowed_tool_refs == ("python -m pytest",)


@pytest.mark.asyncio
async def test_resolve_rejected_does_not_write_hash(bench) -> None:
    project, leader, _alice, _bob, session_id = await _converged(bench)
    _package_value = await _package(bench, session_id, leader)
    run = bench.create_run(project, "idea")
    async with bench.db_session() as session:
        resolved = await resolve_decision(
            session_id, "rejected", run_id=run.id, actor_bot_id=leader, bench=bench, session=session
        )
        await session.commit()
    assert resolved.status == "rejected"
    assert "DecisionPackage" not in run.approved_baseline_hashes


@pytest.mark.asyncio
async def test_resolve_before_converged_is_invalid(bench) -> None:
    project, leader, alice, bob, session_id = await _converged(bench)
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        record = await store.get(session_id)
        await store.save(record.model_copy(update={"status": "cross_review", "decision_package": None}))
        await session.commit()
    async with bench.db_session() as session:
        with pytest.raises(InvalidStatus):
            await resolve_decision(
                session_id, "approved", actor_bot_id=leader, bench=bench, session=session
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_resolve_approved_persists_comment(bench) -> None:
    _project, leader, _alice, _bob, session_id = await _converged(bench)
    await _package(bench, session_id, leader)
    async with bench.db_session() as session:
        resolved = await resolve_decision(
            session_id,
            "approved",
            "同意，按此规格拆解",
            actor_bot_id=leader,
            bench=bench,
            session=session,
        )
        await session.commit()
    assert resolved.status == "approved"
    assert resolved.resolution_comment == "同意，按此规格拆解"
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.resolution_comment == "同意，按此规格拆解"


@pytest.mark.asyncio
async def test_resolve_rejected_persists_comment(bench) -> None:
    _project, leader, _alice, _bob, session_id = await _converged(bench)
    await _package(bench, session_id, leader)
    async with bench.db_session() as session:
        resolved = await resolve_decision(
            session_id,
            "rejected",
            "缺少离线场景的验收标准",
            actor_bot_id=leader,
            bench=bench,
            session=session,
        )
        await session.commit()
    assert resolved.status == "rejected"
    assert resolved.resolution_comment == "缺少离线场景的验收标准"
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.resolution_comment == "缺少离线场景的验收标准"


@pytest.mark.asyncio
async def test_concurrent_approvals_are_idempotent(bench) -> None:
    project, leader, _alice, _bob, session_id = await _converged(bench)
    package = await _package(bench, session_id, leader)
    run = bench.create_run(project, "idea")

    async def approve():
        async with bench.db_session() as session:
            record = await resolve_decision(
                session_id, "approved", run_id=run.id, actor_bot_id=leader, bench=bench, session=session
            )
            await session.commit()
            return record

    first, second = await asyncio.gather(approve(), approve())
    assert first.status == "approved"
    assert second.status == "approved"
    assert run.approved_baseline_hashes["DecisionPackage"] == package.sha256