from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestrator.states import next_task_state
from app.storage.models import EventRow
from app.storage.repos import EventRepo


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[EventRow]]] = defaultdict(list)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._seq: dict[str, int] = defaultdict(int)
        self._local: dict[str, list[EventRow]] = defaultdict(list)

    async def emit(
        self,
        session: AsyncSession,
        run_id: str,
        kind: str,
        subject: str = "",
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> EventRow:
        async with self._locks[run_id]:
            if self._seq[run_id] == 0:
                current = await EventRepo(session).next_seq(run_id)
                self._seq[run_id] = max(current - 1, 0)
            self._seq[run_id] += 1
            seq = self._seq[run_id]
            row = EventRow(
                run_id=run_id,
                seq=seq,
                kind=kind,
                subject=subject,
                actor=actor,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
            )
            session.add(row)
            await session.flush()
            self._local[run_id].append(row)
            for queue in list(self._subs.get(run_id, [])):
                await queue.put(row)
            return row

    def emit_sync(
        self,
        run_id: str,
        kind: str,
        subject: str = "",
        payload: dict[str, Any] | None = None,
        actor: str = "system",
        seq: int | None = None,
    ) -> EventRow:
        if seq is None:
            self._seq[run_id] += 1
            seq = self._seq[run_id]
        else:
            self._seq[run_id] = max(self._seq[run_id], seq)
        row = EventRow(
            run_id=run_id,
            seq=seq,
            kind=kind,
            subject=subject,
            actor=actor,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        self._local[run_id].append(row)
        for queue in list(self._subs.get(run_id, [])):
            queue.put_nowait(row)
        return row

    def subscribe(self, run_id: str) -> asyncio.Queue[EventRow]:
        queue: asyncio.Queue[EventRow] = asyncio.Queue()
        self._subs[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[EventRow]) -> None:
        subs = self._subs.get(run_id, [])
        if queue in subs:
            subs.remove(queue)

    async def replay(self, session: AsyncSession, run_id: str, after: int = 0) -> list[EventRow]:
        return await EventRepo(session).after(run_id, after)

    async def stream(self, session: AsyncSession, run_id: str, after: int = 0) -> AsyncIterator[EventRow]:
        for row in await self.replay(session, run_id, after):
            yield row
        queue = self.subscribe(run_id)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(run_id, queue)


def rebuild_task_states(events: list[EventRow], tasks: dict[str, str]) -> dict[str, str]:
    states = dict(tasks)
    for event in events:
        if event.kind != "task.state_changed":
            continue
        payload = json.loads(event.payload_json)
        code = payload.get("code") or event.subject
        ev = payload.get("event")
        if code and ev:
            try:
                states[code] = next_task_state(states.get(code, payload.get("from") or "pending"), ev)
            except Exception:  # noqa: BLE001
                states[code] = payload.get("to", states.get(code, "pending"))
    return states


BUS = EventBus()
