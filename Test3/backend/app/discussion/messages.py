"""Append-only message timeline for one discussion session.

Messages are persisted first and then pushed to live subscribers, mirroring
``app.events.bus.EventBus``.  ``seq`` is allocated inside a per-session lock by
reading ``MAX(seq)`` from SQLite, so a process restart or a second bench can
never reuse a sequence number.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import DiscussionMessageRow

MESSAGE_KINDS = ("system", "proposal", "review", "leader", "user")


def message_item(row: DiscussionMessageRow) -> dict[str, Any]:
    return {
        "session_id": row.session_id,
        "seq": row.seq,
        "kind": row.kind,
        "bot_id": row.bot_id,
        "round": row.round,
        "payload": row.payload or {},
        "created_at": row.created_at,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MessageLog:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[DiscussionMessageRow]]] = defaultdict(list)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _next_seq(self, session: AsyncSession, session_id: str) -> int:
        value = (
            await session.execute(
                select(func.max(DiscussionMessageRow.seq)).where(
                    DiscussionMessageRow.session_id == session_id
                )
            )
        ).scalar_one_or_none()
        return int(value or 0) + 1

    async def append(
        self,
        session: AsyncSession,
        session_id: str,
        kind: str,
        *,
        bot_id: str | None = None,
        round_no: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> DiscussionMessageRow:
        if kind not in MESSAGE_KINDS:
            raise ValueError(f"unknown message kind: {kind}")
        async with self._locks[session_id]:
            row = DiscussionMessageRow(
                session_id=session_id,
                seq=await self._next_seq(session, session_id),
                kind=kind,
                bot_id=bot_id,
                round=round_no,
                payload=payload or {},
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            for queue in list(self._subs.get(session_id, [])):
                await queue.put(row)
            return row

    async def after(
        self, session: AsyncSession, session_id: str, after_seq: int = 0
    ) -> list[DiscussionMessageRow]:
        stmt = (
            select(DiscussionMessageRow)
            .where(
                DiscussionMessageRow.session_id == session_id,
                DiscussionMessageRow.seq > max(int(after_seq), 0),
            )
            .order_by(DiscussionMessageRow.seq)
        )
        return list((await session.execute(stmt)).scalars())

    def subscribe(self, session_id: str) -> asyncio.Queue[DiscussionMessageRow]:
        queue: asyncio.Queue[DiscussionMessageRow] = asyncio.Queue()
        self._subs[session_id].append(queue)
        return queue

    def unsubscribe(
        self, session_id: str, queue: asyncio.Queue[DiscussionMessageRow]
    ) -> None:
        subs = self._subs.get(session_id, [])
        if queue in subs:
            subs.remove(queue)

    async def stream(
        self, session: AsyncSession, session_id: str, after_seq: int = 0
    ) -> AsyncIterator[DiscussionMessageRow]:
        for row in await self.after(session, session_id, after_seq):
            yield row
        queue = self.subscribe(session_id)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(session_id, queue)


LOG = MessageLog()

__all__ = ["LOG", "MESSAGE_KINDS", "MessageLog", "message_item"]
