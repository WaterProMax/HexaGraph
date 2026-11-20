"""Read-only message timeline and SSE stream for a discussion session."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.discussion.messages import LOG, message_item
from app.discussion.session_store import DiscussionSessionStore, SessionNotFound
from app.storage.models import DiscussionMessageRow

router = APIRouter()

HEARTBEAT_SECONDS = 15.0
HEARTBEAT_FRAME = ": ping\n\n"


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


def _parse_seq(value: str | int | None) -> int:
    try:
        return max(int(str(value).strip() or "0"), 0)
    except (TypeError, ValueError):
        return 0


def _frame(row: DiscussionMessageRow) -> str:
    data = json.dumps(message_item(row), ensure_ascii=False, default=str)
    return f"id: {row.seq}\nevent: message\ndata: {data}\n\n"


def _resolve_actor(header_bot: str | None, query_bot: str | None) -> str | None:
    return (header_bot or "").strip() or (query_bot or "").strip() or None


async def _authorize(bench, session_id: str, actor: str | None) -> JSONResponse | None:
    if actor is None:
        return _json_error(400, "validation_error", "X-Bot-Id header is required")
    async with bench.db_session() as session:
        try:
            record = await DiscussionSessionStore(session).get(session_id)
        except SessionNotFound:
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
    if actor not in record.participant_bot_ids and actor != record.leader_bot_id:
        return _json_error(403, "not_participant", "actor is not a participant of this session")
    return None


async def event_stream(
    bench, session_id: str, after_seq: int = 0
) -> AsyncIterator[str]:
    """Ping, replay history, then live messages; heartbeats while idle.

    Subscribe before replaying so a message appended between the two cannot be
    lost; the ``seq`` cursor deduplicates anything delivered twice.
    """
    queue = LOG.subscribe(session_id)
    last = max(int(after_seq), 0)
    try:
        yield HEARTBEAT_FRAME
        async with bench.db_session() as session:
            replay = await LOG.after(session, session_id, last)
        for row in replay:
            if row.seq > last:
                last = row.seq
                yield _frame(row)
        while True:
            try:
                row = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            if row.seq <= last:
                continue
            last = row.seq
            yield _frame(row)
    finally:
        LOG.unsubscribe(session_id, queue)


@router.get("/discussion-sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    request: Request,
    after: str = "0",
    header_bot: str | None = Header(default=None, alias="X-Bot-Id"),
) -> Any:
    bench = request.app.state.workbench
    error = await _authorize(bench, session_id, _resolve_actor(header_bot, None))
    if error is not None:
        return error
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, _parse_seq(after))
    return {"items": [message_item(row) for row in rows]}


@router.get("/discussion-sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    bot_id: str | None = None,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    header_bot: str | None = Header(default=None, alias="X-Bot-Id"),
) -> Any:
    bench = request.app.state.workbench
    actor = _resolve_actor(header_bot, bot_id)
    error = await _authorize(bench, session_id, actor)
    if error is not None:
        return error
    return StreamingResponse(
        event_stream(bench, session_id, _parse_seq(last_event_id)),
        media_type="text/event-stream",
    )


__all__ = [
    "HEARTBEAT_FRAME",
    "HEARTBEAT_SECONDS",
    "event_stream",
    "router",
    "session_events",
    "list_messages",
]