"""Round lifecycle and blind proposals for P4 discussions.

The listed contract functions are module-level; each accepts a keyword-only
``session`` so callers (HTTP routes and unit tests) inject the active
``AsyncSession`` instead of relying on a hidden global database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.models import DiscussionGenerationToken, DiscussionSession
from app.discussion.session_store import (
    DiscussionSessionStore,
    Forbidden,
    InvalidStatus,
    NotParticipant,
    assert_generation_current,
    manual_round_ended,
    retry_locked,
)
from app.storage.models import DiscussionProposalRow


class BudgetExhausted(Exception):
    pass


class DuplicateProposal(Exception):
    pass


async def _round_rows(session: AsyncSession, session_id: str, round_no: int):
    stmt = (
        select(
            DiscussionProposalRow.author_bot_id,
            DiscussionProposalRow.sealed,
        )
        .where(
            DiscussionProposalRow.session_id == session_id,
            DiscussionProposalRow.round == round_no,
        )
        .order_by(DiscussionProposalRow.author_bot_id)
    )
    return (await session.execute(stmt)).all()


def _next_round(
    record: DiscussionSession,
    round_no: int | None,
    manual_revision: int | None = None,
) -> int:
    if record.status == "grouping":
        next_round = 1
    elif record.status in {"cross_review", "round_n_revise"}:
        next_round = record.current_round + 1
    elif record.status == "converged_pending_human":
        if record.decision_package is not None:
            raise InvalidStatus("decision package already exists")
        if manual_round_ended(record):
            # A manual end is a hard stop; only the explicit rounds/start route
            # (carrying the current control revision) may reopen the session.
            if manual_revision is None:
                raise InvalidStatus("manual_round_ended")
            if int(manual_revision) != int(record.control_revision):
                raise InvalidStatus("revision_conflict")
        next_round = record.current_round + 1
    elif record.status == "budget_exhausted":
        raise BudgetExhausted("discussion budget is exhausted")
    else:
        raise InvalidStatus(record.status)
    if round_no is not None and round_no != next_round:
        raise InvalidStatus(f"requested round {round_no}, expected {next_round}")
    return next_round


async def _start_once(
    session: AsyncSession,
    session_id: str,
    round_no: int | None,
    actor_bot_id: str,
    expected_revision: int | None = None,
) -> DiscussionSession:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if record.pause_requested:
        # A pending cooperative-pause intent wins over every round start,
        # automatic or manual.  ``paused=True`` is deliberately *not* rejected:
        # that is the finalized pause/manual-end state which ``rounds/start``
        # with the CAS revision is allowed to reopen.
        raise InvalidStatus("paused")
    if actor_bot_id != record.leader_bot_id:
        raise Forbidden("only the session leader can start a round")
    if expected_revision is not None and int(expected_revision) != int(record.control_revision):
        raise InvalidStatus("revision_conflict")
    next_round = _next_round(record, round_no, expected_revision)
    if manual_round_ended(record):
        # Covers the pathological crash window where the manual end intent is
        # persisted before the status flips to converged_pending_human.
        if expected_revision is None:
            raise InvalidStatus("manual_round_ended")
    if next_round > record.budget.max_rounds:
        await store.save(record.model_copy(update={"status": "budget_exhausted"}))
        raise BudgetExhausted("discussion budget is exhausted")
    fields: dict = {
        "status": "round1_independent" if next_round == 1 else "round_n_revise",
        "current_round": next_round,
        "control_revision": record.control_revision + 1,
        # A new round is a new generation: every token captured for the previous
        # round/epoch is stale and may no longer write.
        "control_epoch": record.control_epoch + 1,
    }
    if manual_round_ended(record):
        # Starting the next round is the only transition that clears a manual
        # end; the intervening pause/interventions remain in the message log.
        fields.update(
            {
                "round_end_reason": None,
                "paused": False,
                "pause_requested": False,
                "checkpoint": {},
            }
        )
    updated = record.model_copy(update=fields)
    await store.save(updated)
    return updated


async def start_round(
    session_id: str,
    round_no: int | None = None,
    *,
    actor_bot_id: str,
    session: AsyncSession,
    expected_revision: int | None = None,
) -> DiscussionSession:
    return await retry_locked(
        session,
        lambda: _start_once(
            session, session_id, round_no, actor_bot_id, expected_revision
        ),
    )


async def _submit_once(
    session: AsyncSession,
    session_id: str,
    author_bot_id: str,
    body_md: str,
    generation: DiscussionGenerationToken | None = None,
) -> dict:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if generation is not None:
        # Authoritative check inside the write transaction: a stale generation
        # (older round/epoch or a session that stopped meanwhile) never writes.
        assert_generation_current(record, generation)
    if record.status not in {"round1_independent", "round_n_revise"}:
        raise InvalidStatus(record.status)
    if author_bot_id not in record.participant_bot_ids:
        raise NotParticipant(author_bot_id)
    existing = await session.execute(
        select(DiscussionProposalRow).where(
            DiscussionProposalRow.session_id == session_id,
            DiscussionProposalRow.author_bot_id == author_bot_id,
            DiscussionProposalRow.round == record.current_round,
        )
    )
    if existing.scalars().first() is not None:
        raise DuplicateProposal(author_bot_id)
    proposal_id = str(uuid.uuid4())
    session.add(
        DiscussionProposalRow(
            proposal_id=proposal_id,
            session_id=session_id,
            author_bot_id=author_bot_id,
            round=record.current_round,
            sealed=1,
            body_md=body_md,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateProposal(author_bot_id) from exc
    await _unseal_once(session, session_id)
    sealed = (
        await session.execute(
            select(DiscussionProposalRow.sealed).where(
                DiscussionProposalRow.proposal_id == proposal_id
            )
        )
    ).scalar_one()
    return {"proposal_id": proposal_id, "sealed": bool(sealed)}


async def submit_proposal(
    session_id: str,
    author_bot_id: str,
    body_md: str,
    *,
    session: AsyncSession,
    generation: DiscussionGenerationToken | None = None,
) -> dict:
    return await retry_locked(
        session,
        lambda: _submit_once(
            session, session_id, author_bot_id, body_md, generation=generation
        ),
    )


async def _unseal_once(session: AsyncSession, session_id: str) -> bool:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if record.status not in {"round1_independent", "round_n_revise"}:
        return False
    rows = await _round_rows(session, session_id, record.current_round)
    authors = {row.author_bot_id for row in rows}
    if not set(record.participant_bot_ids) <= authors:
        return False
    await session.execute(
        update(DiscussionProposalRow)
        .where(
            DiscussionProposalRow.session_id == session_id,
            DiscussionProposalRow.round == record.current_round,
        )
        .values(sealed=0)
    )
    await session.flush()
    await _open_once(session, session_id)
    return True


async def unseal_if_complete(session_id: str, *, session: AsyncSession) -> bool:
    return await retry_locked(session, lambda: _unseal_once(session, session_id))


async def _open_once(session: AsyncSession, session_id: str) -> DiscussionSession:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if record.status == "cross_review":
        return record
    if record.status not in {"round1_independent", "round_n_revise"}:
        raise InvalidStatus(record.status)
    rows = await _round_rows(session, session_id, record.current_round)
    if not rows:
        raise InvalidStatus("no proposals for the current round")
    authors = {row.author_bot_id for row in rows}
    if not set(record.participant_bot_ids) <= authors:
        raise InvalidStatus("not every participant has submitted")
    if any(row.sealed != 0 for row in rows):
        raise InvalidStatus("proposals are still sealed")
    updated = record.model_copy(update={"status": "cross_review"})
    await store.save(updated)
    return updated


async def open_cross_review(session_id: str, *, session: AsyncSession) -> DiscussionSession:
    return await retry_locked(session, lambda: _open_once(session, session_id))


async def list_proposals(
    session_id: str, viewer_bot_id: str, *, session: AsyncSession, include_history: bool = False
) -> list[dict]:
    store = DiscussionSessionStore(session)
    record = await store.get(session_id)
    if viewer_bot_id != record.leader_bot_id and viewer_bot_id not in record.participant_bot_ids:
        raise NotParticipant(viewer_bot_id)
    if record.status not in {
        "round1_independent",
        "cross_review",
        "round_n_revise",
        "converged_pending_human",
        "approved",
        "rejected",
        "terminated",
        "budget_exhausted",
    }:
        raise InvalidStatus(record.status)
    stmt = (
        select(DiscussionProposalRow)
        .where(DiscussionProposalRow.session_id == session_id)
        .order_by(DiscussionProposalRow.round, DiscussionProposalRow.author_bot_id)
    )
    if not include_history:
        stmt = stmt.where(DiscussionProposalRow.round == record.current_round)
    rows = list((await session.execute(stmt)).scalars())
    items: list[dict] = []
    for row in rows:
        visible = row.sealed == 0 or viewer_bot_id == row.author_bot_id
        items.append(
            {
                "proposal_id": row.proposal_id,
                "author_bot_id": row.author_bot_id,
                "round": row.round,
                "sealed": bool(row.sealed),
                "body_md": row.body_md if visible else None,
            }
        )
    return items


__all__ = [
    "BudgetExhausted",
    "DuplicateProposal",
    "Forbidden",
    "InvalidStatus",
    "NotParticipant",
    "list_proposals",
    "open_cross_review",
    "start_round",
    "submit_proposal",
    "unseal_if_complete",
]
