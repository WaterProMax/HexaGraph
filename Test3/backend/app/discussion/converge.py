"""Deterministic convergence decision for a P4 discussion round.

The decision uses hard-gate booleans, the per-proposal score spread, dissent
records, round counts and budget usage.  It is a pure function of
``DiscussionRoundState``; ballots never pick a winner, the spread only has to
fall within ``DiscussionBudget.score_gap_threshold``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.cross_review import proposal_spread
from app.discussion.models import (
    DiscussionRoundState,
    DiscussionSession,
    ReviewBallot,
)
from app.storage.models import DiscussionProposalRow, DiscussionReviewRow

REQUIRED_HARD_GATES = ("coverage", "conflicts_closed_or_recorded", "evidence_complete")
REQUIRED_HARD_GATE_COUNT = len(REQUIRED_HARD_GATES)


def _gate_summary(reviews_by_proposal: dict[str, list[ReviewBallot]]) -> dict[str, bool]:
    if not reviews_by_proposal or any(
        not reviews for reviews in reviews_by_proposal.values()
    ):
        return {gate: False for gate in REQUIRED_HARD_GATES}
    all_reviews = [
        review for reviews in reviews_by_proposal.values() for review in reviews
    ]
    return {
        gate: all(review.hard_gate_results.get(gate, False) for review in all_reviews)
        for gate in REQUIRED_HARD_GATES
    }


async def _round_proposals_reviews(
    session: AsyncSession, session_id: str, round_no: int
) -> tuple[list[DiscussionProposalRow], dict[str, list[ReviewBallot]]]:
    proposals = list(
        (
            await session.execute(
                select(DiscussionProposalRow)
                .where(
                    DiscussionProposalRow.session_id == session_id,
                    DiscussionProposalRow.round == round_no,
                )
                .order_by(DiscussionProposalRow.proposal_id)
            )
        ).scalars()
    )
    proposal_ids = [proposal.proposal_id for proposal in proposals]
    reviews: dict[str, list[ReviewBallot]] = {
        proposal_id: [] for proposal_id in proposal_ids
    }
    if proposal_ids:
        rows = list(
            (
                await session.execute(
                    select(DiscussionReviewRow)
                    .where(
                        DiscussionReviewRow.session_id == session_id,
                        DiscussionReviewRow.proposal_id.in_(proposal_ids),
                    )
                    .order_by(
                        DiscussionReviewRow.proposal_id,
                        DiscussionReviewRow.reviewer_bot_id,
                    )
                )
            ).scalars()
        )
        for row in rows:
            reviews.setdefault(row.proposal_id, []).append(
                ReviewBallot.model_validate(row.payload)
            )
    return proposals, reviews


async def current_round_gate_summary(
    session: AsyncSession, record: DiscussionSession
) -> dict[str, bool]:
    _proposals, reviews = await _round_proposals_reviews(
        session, record.session_id, record.current_round
    )
    return _gate_summary(reviews)


async def build_round_state(
    session: AsyncSession,
    record: DiscussionSession,
    *,
    tokens_used: int = 0,
    elapsed_seconds: int = 0,
    extra_dissent: list[str] | None = None,
) -> DiscussionRoundState:
    counts: list[int] = []
    spread: float | None = None
    for round_no in range(1, record.current_round + 1):
        proposals, reviews = await _round_proposals_reviews(
            session, record.session_id, round_no
        )
        summary = _gate_summary(reviews)
        counts.append(sum(summary.values()) if proposals else 0)
        if round_no == record.current_round:
            spread = proposal_spread(
                [ballot for ballots in reviews.values() for ballot in ballots],
                [proposal.proposal_id for proposal in proposals],
            )
    review_rows = list(
        (
            await session.execute(
                select(DiscussionReviewRow)
                .where(DiscussionReviewRow.session_id == record.session_id)
                .order_by(
                    DiscussionReviewRow.proposal_id,
                    DiscussionReviewRow.reviewer_bot_id,
                )
            )
        ).scalars()
    )
    dissent: list[str] = []
    for row in review_rows:
        dissent.extend(ReviewBallot.model_validate(row.payload).dissent_items)
    dissent.extend(extra_dissent or [])
    latest = counts[-1] if counts else 0
    return DiscussionRoundState(
        current_round=record.current_round,
        budget=record.budget,
        tokens_used=int(tokens_used),
        elapsed_seconds=int(elapsed_seconds),
        hard_gate_pass_counts=counts,
        dissent_items=list(dict.fromkeys(dissent)),
        all_required_hard_gates_pass=latest == REQUIRED_HARD_GATE_COUNT,
        score_spread=spread,
    )


def _spread_text(spread: float | None, threshold: float) -> str:
    if spread is None:
        return f"score spread unavailable (threshold {threshold:g})"
    relation = "within" if spread <= threshold else "above"
    return f"score spread {spread:g} {relation} threshold {threshold:g}"


def _converge_with_score_gap(
    state: DiscussionRoundState, threshold: float
) -> tuple[str, str]:
    """Threshold mode: unmet conditions get another round instead of dissent override."""
    dissent = list(dict.fromkeys(state.dissent_items))
    dissent_text = f"; dissent: {' | '.join(dissent)}" if dissent else ""
    latest = state.hard_gate_pass_counts[-1] if state.hard_gate_pass_counts else 0
    unmet = max(0, REQUIRED_HARD_GATE_COUNT - latest)
    spread_text = _spread_text(state.score_spread, threshold)
    spread_within = state.score_spread is not None and state.score_spread <= threshold
    if state.all_required_hard_gates_pass and spread_within:
        return (
            "submit_human",
            f"all required hard gates passed; {spread_text}" + dissent_text,
        )
    if state.current_round >= state.budget.max_rounds:
        return (
            "submit_human",
            f"round limit reached at round {state.current_round}; "
            f"unmet hard gates: {unmet}; {spread_text}" + dissent_text,
        )
    counts = state.hard_gate_pass_counts
    if len(counts) >= 2 and counts[-1] <= counts[-2]:
        return (
            "no_improvement",
            f"hard gate pass count did not improve: {counts[-2]} -> {counts[-1]}; "
            f"{spread_text}" + dissent_text,
        )
    return (
        "revise",
        f"convergence conditions not met: {unmet} unmet hard gate(s); "
        f"{spread_text}" + dissent_text,
    )


def should_converge(state: DiscussionRoundState) -> tuple[str, str]:
    budget = state.budget
    if budget.max_tokens is not None and state.tokens_used >= budget.max_tokens:
        return (
            "budget_exhausted",
            f"token budget reached: {state.tokens_used}/{budget.max_tokens}",
        )
    if (
        budget.max_wallclock_seconds is not None
        and state.elapsed_seconds >= budget.max_wallclock_seconds
    ):
        return (
            "budget_exhausted",
            f"wallclock budget reached: {state.elapsed_seconds}/{budget.max_wallclock_seconds}",
        )
    if budget.score_gap_threshold is not None:
        return _converge_with_score_gap(state, budget.score_gap_threshold)
    dissent = list(dict.fromkeys(state.dissent_items))
    dissent_text = f"; dissent: {' | '.join(dissent)}" if dissent else ""
    latest = state.hard_gate_pass_counts[-1] if state.hard_gate_pass_counts else 0
    unmet = max(0, REQUIRED_HARD_GATE_COUNT - latest)
    if state.all_required_hard_gates_pass:
        return "submit_human", "all required hard gates passed" + dissent_text
    if unmet > 0 and len(dissent) >= unmet:
        return (
            "submit_human",
            f"{unmet} unmet hard gate(s) recorded in dissent" + dissent_text,
        )
    if state.current_round >= budget.max_rounds:
        return (
            "submit_human",
            f"round limit reached at round {state.current_round}" + dissent_text,
        )
    counts = state.hard_gate_pass_counts
    if len(counts) >= 2 and counts[-1] <= counts[-2]:
        return (
            "no_improvement",
            f"hard gate pass count did not improve: {counts[-2]} -> {counts[-1]}"
            + dissent_text,
        )
    return "revise", f"hard gates still unmet: {unmet}" + dissent_text


__all__ = [
    "REQUIRED_HARD_GATES",
    "build_round_state",
    "current_round_gate_summary",
    "should_converge",
]