"""Cross review for P4 discussions: no self review, no score-based truth."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.models import DiscussionSession, ReviewBallot
from app.discussion.proposals import open_cross_review as _open_cross_review
from app.discussion.session_store import (
    DiscussionSessionStore,
    InvalidStatus,
    NotParticipant,
    retry_locked,
)
from app.storage.models import DiscussionProposalRow, DiscussionReviewRow


class ProposalNotFound(Exception):
    pass


class SelfReviewForbidden(Exception):
    pass


class DuplicateReview(Exception):
    pass


async def _submit_once(
    session: AsyncSession, session_id: str, ballot: ReviewBallot
) -> dict:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if record.status != "cross_review":
        raise InvalidStatus(record.status)
    if ballot.reviewer_bot_id not in record.participant_bot_ids:
        raise NotParticipant(ballot.reviewer_bot_id)
    proposal = await session.get(DiscussionProposalRow, ballot.proposal_id)
    if proposal is None or proposal.session_id != session_id:
        raise ProposalNotFound(ballot.proposal_id)
    if ballot.reviewer_bot_id == proposal.author_bot_id:
        raise SelfReviewForbidden(ballot.proposal_id)
    existing = await session.execute(
        select(DiscussionReviewRow).where(
            DiscussionReviewRow.session_id == session_id,
            DiscussionReviewRow.reviewer_bot_id == ballot.reviewer_bot_id,
            DiscussionReviewRow.proposal_id == ballot.proposal_id,
        )
    )
    if existing.scalars().first() is not None:
        raise DuplicateReview(ballot.proposal_id)
    review_id = str(uuid.uuid4())
    session.add(
        DiscussionReviewRow(
            review_id=review_id,
            session_id=session_id,
            reviewer_bot_id=ballot.reviewer_bot_id,
            proposal_id=ballot.proposal_id,
            payload=ballot.model_dump(),
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateReview(ballot.proposal_id) from exc
    return {
        "review_id": review_id,
        "session_id": session_id,
        "reviewer_bot_id": ballot.reviewer_bot_id,
        "proposal_id": ballot.proposal_id,
        "scores": ballot.scores,
        "score_justification": ballot.score_justification,
        "hard_gate_results": ballot.hard_gate_results,
        "dissent_items": ballot.dissent_items,
    }


async def submit_review(
    session_id: str, ballot: ReviewBallot, *, session: AsyncSession
) -> dict:
    return await retry_locked(
        session, lambda: _submit_once(session, session_id, ballot)
    )


def score_spread(ballots: list[ReviewBallot]) -> float:
    """Statistics only; never used by submit_review or convergence decisions."""
    if not ballots:
        return 0.0
    totals = [sum(ballot.scores.values()) for ballot in ballots]
    return float(max(totals) - min(totals))


async def open_cross_review(
    session_id: str, *, session: AsyncSession
) -> DiscussionSession:
    return await _open_cross_review(session_id, session=session)


__all__ = [
    "DuplicateReview",
    "ProposalNotFound",
    "SelfReviewForbidden",
    "open_cross_review",
    "score_spread",
    "submit_review",
]