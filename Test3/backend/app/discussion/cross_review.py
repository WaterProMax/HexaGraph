"""Cross review for P4 discussions: no self review.

Ballot scores never decide a proposal on their own; they are only summarised
per proposal so convergence can compare the spread against a threshold.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.models import (
    DiscussionGenerationToken,
    DiscussionSession,
    ReviewBallot,
)
from app.discussion.proposals import open_cross_review as _open_cross_review
from app.discussion.session_store import (
    DiscussionSessionStore,
    InvalidStatus,
    NotParticipant,
    assert_generation_current,
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
    session: AsyncSession,
    session_id: str,
    ballot: ReviewBallot,
    generation: DiscussionGenerationToken | None = None,
) -> dict:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if generation is not None:
        # Stale ballots never land in a newer round/epoch or a stopped session.
        assert_generation_current(record, generation)
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
    session_id: str,
    ballot: ReviewBallot,
    *,
    session: AsyncSession,
    generation: DiscussionGenerationToken | None = None,
) -> dict:
    return await retry_locked(
        session,
        lambda: _submit_once(session, session_id, ballot, generation=generation),
    )


def score_spread(ballots: list[ReviewBallot]) -> float:
    """Statistics only; never used by submit_review or convergence decisions."""
    if not ballots:
        return 0.0
    totals = [sum(ballot.scores.values()) for ballot in ballots]
    return float(max(totals) - min(totals))


def proposal_totals(ballots: list[ReviewBallot]) -> dict[str, float]:
    """Average total score per proposal; proposals without ballots are omitted."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for ballot in ballots:
        total = float(sum(ballot.scores.values()))
        sums[ballot.proposal_id] = sums.get(ballot.proposal_id, 0.0) + total
        counts[ballot.proposal_id] = counts.get(ballot.proposal_id, 0) + 1
    return {
        proposal_id: sums[proposal_id] / counts[proposal_id] for proposal_id in sums
    }


def proposal_spread(
    ballots: list[ReviewBallot], proposal_ids: list[str] | None = None
) -> float | None:
    """Max minus min average total across scored proposals.

    Only proposals that appear in ``proposal_ids`` (when given) and have at
    least one ballot are compared.  Fewer than two scored proposals means the
    spread is undefined.
    """
    if proposal_ids is None:
        totals = proposal_totals(ballots)
    else:
        wanted = set(proposal_ids)
        totals = proposal_totals(
            [ballot for ballot in ballots if ballot.proposal_id in wanted]
        )
    if len(totals) < 2:
        return None
    values = list(totals.values())
    return float(max(values) - min(values))


async def open_cross_review(
    session_id: str, *, session: AsyncSession
) -> DiscussionSession:
    return await _open_cross_review(session_id, session=session)


__all__ = [
    "DuplicateReview",
    "ProposalNotFound",
    "SelfReviewForbidden",
    "open_cross_review",
    "proposal_spread",
    "proposal_totals",
    "score_spread",
    "submit_review",
]