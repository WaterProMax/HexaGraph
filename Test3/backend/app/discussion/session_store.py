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

from app.discussion.models import DiscussionSession
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
    "retry_locked",
]