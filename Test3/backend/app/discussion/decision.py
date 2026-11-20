"""DecisionPackage creation and the human specification gate."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.converge import current_round_gate_summary
from app.discussion.models import DecisionPackage, DiscussionSession, ReviewBallot
from app.discussion.session_store import (
    DiscussionSessionStore,
    Forbidden,
    InvalidStatus,
    retry_locked,
)
from app.execution.baseline import hash_artifact
from app.execution.run_profile import store_approved_baseline_hash
from app.execution.run_state_store import read_run_execution_state
from app.storage.models import DiscussionProposalRow, DiscussionReviewRow

CANONICAL_FIELDS = (
    "session_id",
    "requirement_snapshot_hash",
    "proposal_ids",
    "dissent_items",
    "hard_gate_summary",
    "body_md",
)


class InvalidDecision(Exception):
    pass


class RunNotFound(Exception):
    pass


def decision_package_digest(fields: dict) -> str:
    canonical = {field: fields[field] for field in CANONICAL_FIELDS}
    return hash_artifact(canonical)


async def _submit_once(
    session: AsyncSession,
    session_id: str,
    body_md: str,
    dissent_items: list[str],
    actor_bot_id: str,
) -> DecisionPackage:
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if actor_bot_id != record.leader_bot_id:
        raise Forbidden("only the session leader can submit a decision")
    if record.status != "converged_pending_human":
        raise InvalidStatus(record.status)
    if record.decision_package is not None:
        raise InvalidStatus("decision package already exists")
    proposal_rows = list(
        (
            await session.execute(
                select(DiscussionProposalRow)
                .where(DiscussionProposalRow.session_id == session_id)
                .order_by(
                    DiscussionProposalRow.round,
                    DiscussionProposalRow.author_bot_id,
                )
            )
        ).scalars()
    )
    review_rows = list(
        (
            await session.execute(
                select(DiscussionReviewRow)
                .where(DiscussionReviewRow.session_id == session_id)
                .order_by(
                    DiscussionReviewRow.proposal_id,
                    DiscussionReviewRow.reviewer_bot_id,
                )
            )
        ).scalars()
    )
    review_dissent: list[str] = []
    for row in review_rows:
        review_dissent.extend(
            ReviewBallot.model_validate(row.payload).dissent_items
        )
    combined_dissent = list(dict.fromkeys([*dissent_items, *review_dissent]))
    hard_gate_summary = await current_round_gate_summary(session, record)
    package = {
        "decision_id": str(uuid.uuid4()),
        "session_id": session_id,
        "requirement_snapshot_hash": record.requirement_snapshot_hash,
        "proposal_ids": [row.proposal_id for row in proposal_rows],
        "dissent_items": combined_dissent,
        "hard_gate_summary": hard_gate_summary,
        "body_md": body_md,
    }
    package["sha256"] = decision_package_digest(package)
    package_obj = DecisionPackage.model_validate(package)
    updated = record.model_copy(update={"decision_package": package_obj})
    await store.save(updated)
    return package_obj


async def submit_decision(
    session_id: str,
    body_md: str,
    dissent_items: list[str],
    *,
    actor_bot_id: str,
    session: AsyncSession,
) -> DecisionPackage:
    return await retry_locked(
        session,
        lambda: _submit_once(
            session, session_id, body_md, dissent_items, actor_bot_id
        ),
    )


def _resolve_lock(bench) -> asyncio.Lock:
    lock = getattr(bench, "_discussion_resolve_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(bench, "_discussion_resolve_lock", lock)
    return lock


async def resolve_decision(
    session_id: str,
    decision: str,
    comment: str | None = None,
    *,
    run_id: str | None = None,
    actor_bot_id: str,
    bench,
    session: AsyncSession,
) -> DiscussionSession:
    async with _resolve_lock(bench):
        return await _resolve_once(
            session_id,
            decision,
            comment=comment,
            run_id=run_id,
            actor_bot_id=actor_bot_id,
            bench=bench,
            session=session,
        )


async def _resolve_once(
    session_id: str,
    decision: str,
    *,
    comment: str | None,
    run_id: str | None,
    actor_bot_id: str,
    bench,
    session: AsyncSession,
) -> DiscussionSession:
    if decision not in {"approved", "rejected"}:
        raise InvalidDecision(decision)
    store = DiscussionSessionStore(session)
    record = await store.get(session_id)
    if actor_bot_id != record.leader_bot_id:
        raise Forbidden("only the session leader can resolve a decision")
    if record.status == "approved" and decision == "approved":
        return record
    if record.status != "converged_pending_human" or record.decision_package is None:
        raise InvalidStatus(record.status)
    package = record.decision_package
    run = None
    if decision == "approved" and run_id is not None:
        run = bench.runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
    # Release the read transaction before persist_run_execution_state writes on
    # another connection; the in-process lock keeps approvals serialized.
    await session.rollback()
    if decision == "approved" and run_id is not None and run is not None:
        digest = package.sha256
        existing = read_run_execution_state(bench.db_path, run_id)
        if existing is not None:
            merged = {**existing.approved_baseline_hashes, "DecisionPackage": digest}
            await bench.persist_run_execution_state(
                run_id,
                existing.execution_profile,
                merged,
                approved_plan_hash=existing.approved_plan_hash,
                allowed_tool_refs=list(existing.allowed_tool_refs),
            )
        else:
            store_approved_baseline_hash(run, "DecisionPackage", digest)
    record = await store.get_locked(session_id)
    if record.status == "approved" and decision == "approved":
        return record
    if record.status != "converged_pending_human":
        raise InvalidStatus(record.status)
    fields: dict = {"status": decision}
    if comment is not None:
        fields["resolution_comment"] = comment
    updated = record.model_copy(update=fields)
    await store.save(updated)
    return updated


__all__ = [
    "CANONICAL_FIELDS",
    "InvalidDecision",
    "RunNotFound",
    "decision_package_digest",
    "resolve_decision",
    "submit_decision",
]