"""SQLite authority for P4 discussion sessions.

The status column mirrors ``payload.status``.  Mutating flows call
``get_locked`` first, which takes SQLite's write lock before reading so
concurrent group/round operations serialize instead of interleaving.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.models import DiscussionGenerationToken, DiscussionSession
from app.storage.models import DiscussionSessionRow


class SessionNotFound(Exception):
    pass


class InvalidStatus(Exception):
    pass


class Forbidden(Exception):
    pass


class NotParticipant(Exception):
    pass


def _is_locked(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def manual_round_ended(record: DiscussionSession) -> bool:
    """True when the leader explicitly ended the current round by hand."""
    reason = record.round_end_reason
    return isinstance(reason, dict) and reason.get("kind") == "manual"


def check_control_revision(
    record: DiscussionSession, expected_revision: int | None
) -> None:
    """CAS guard shared by every control mutation.

    ``None`` keeps the pre-revision callers working; an explicit revision that
    no longer matches raises ``InvalidStatus`` so the HTTP layer answers 409.
    """
    if expected_revision is None:
        return
    if int(expected_revision) != int(record.control_revision):
        raise InvalidStatus("revision_conflict")


def assert_generation_current(
    record: DiscussionSession,
    generation: DiscussionGenerationToken | None,
) -> None:
    """Pure generation identity/control check for writes made under a lock.

    ``None`` keeps the public manual paths (which never started a model call)
    working.  A mismatch means the row belongs to an older round/epoch or the
    session stopped/paused/manual-ended/went terminal meanwhile, so the write
    must not be persisted.  Raises ``InvalidStatus`` (non-retryable) so callers
    can roll back and discard the generated value.
    """
    if generation is None:
        return
    if (
        generation.session_id != record.session_id
        or int(generation.round_no) != int(record.current_round)
        or int(generation.control_epoch) != int(record.control_epoch)
    ):
        raise InvalidStatus("stale_generation")
    if (
        record.paused
        or record.pause_requested
        or manual_round_ended(record)
        or record.status in {
            "approved",
            "rejected",
            "terminated",
            "budget_exhausted",
        }
    ):
        raise InvalidStatus("stale_generation")


async def retry_locked(session: AsyncSession, operation):
    for attempt in range(4):
        try:
            return await operation()
        except OperationalError as exc:
            await session.rollback()
            if not _is_locked(exc) or attempt == 3:
                raise
            await asyncio.sleep(0.02 * (attempt + 1))


def _to_session(row: DiscussionSessionRow) -> DiscussionSession:
    record = DiscussionSession.model_validate(row.payload)
    if record.status != row.status:
        record = record.model_copy(update={"status": row.status})
    return record


class DiscussionSessionStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: DiscussionSession) -> DiscussionSession:
        row = DiscussionSessionRow(
            session_id=record.session_id,
            project_id=record.project_id,
            status=record.status,
            payload=record.model_dump(),
        )
        self.session.add(row)
        await self.session.flush()
        return record

    async def get(self, session_id: str) -> DiscussionSession:
        row = await self.session.get(DiscussionSessionRow, session_id)
        if row is None:
            raise SessionNotFound(session_id)
        return _to_session(row)

    async def save(self, record: DiscussionSession) -> DiscussionSession:
        row = await self.session.get(DiscussionSessionRow, record.session_id)
        if row is None:
            raise SessionNotFound(record.session_id)
        row.status = record.status
        row.payload = record.model_dump()
        await self.session.flush()
        return record

    async def get_locked(self, session_id: str) -> DiscussionSession:
        result = await self.session.execute(
            text(
                "UPDATE discussion_sessions SET status = status "
                "WHERE session_id = :session_id"
            ),
            {"session_id": session_id},
        )
        if result.rowcount == 0:
            raise SessionNotFound(session_id)
        return await self.get(session_id)

    async def predecessors(self, record: DiscussionSession):
        previous_id = record.previous_session_id
        visited = {record.session_id}
        while previous_id and previous_id not in visited:
            visited.add(previous_id)
            try:
                previous = await self.get(previous_id)
            except SessionNotFound:
                return
            if previous.project_id != record.project_id:
                return
            yield previous
            previous_id = previous.previous_session_id

    async def list_all(self) -> list[DiscussionSession]:
        rows = list((await self.session.execute(select(DiscussionSessionRow))).scalars())
        records = [_to_session(row) for row in rows]
        return sorted(records, key=lambda record: (record.created_at, record.session_id))

    async def list_for_project(self, project_id: str) -> list[DiscussionSession]:
        stmt = (
            select(DiscussionSessionRow)
            .where(DiscussionSessionRow.project_id == project_id)
            .order_by(DiscussionSessionRow.session_id)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        records = [_to_session(row) for row in rows]
        return sorted(records, key=lambda record: (record.created_at, record.session_id))


__all__ = [
    "DiscussionSessionStore",
    "Forbidden",
    "InvalidStatus",
    "NotParticipant",
    "SessionNotFound",
    "assert_generation_current",
    "check_control_revision",
    "manual_round_ended",
    "retry_locked",
]
