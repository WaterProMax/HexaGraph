"""Control routes for the multi-bot discussion driver (run/pause/resume/terminate)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.discussion import driver
from app.discussion.session_store import DiscussionSessionStore, SessionNotFound

router = APIRouter()


class ResumeBody(BaseModel):
    skip_bot_ids: list[str] = Field(default_factory=list)


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error_category": category, "detail": detail}
    )


def _actor(request: Request) -> tuple[str | None, JSONResponse | None]:
    actor = (request.headers.get("X-Bot-Id") or "").strip()
    if not actor:
        return None, _json_error(
            400, "validation_error", "X-Bot-Id header is required"
        )
    return actor, None


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _leader_session(
    request: Request,
) -> tuple[str | None, Any | None, JSONResponse | None]:
    actor, error = _actor(request)
    if error is not None:
        return None, None, error
    bench = request.app.state.workbench
    session_id = request.path_params["session_id"]
    async with bench.db_session() as session:
        try:
            record = await DiscussionSessionStore(session).get(session_id)
        except SessionNotFound:
            return actor, None, _json_error(
                404, "session_not_found", f"session not found: {session_id}"
            )
    if actor != record.leader_bot_id:
        return actor, record, _json_error(
            403, "forbidden", "only the session leader can control this session"
        )
    return actor, record, None


@router.post("/discussion-sessions/{session_id}/run")
async def run_discussion(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    _actor_id, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    if record.status in driver.TERMINAL_STATUSES:
        return _json_error(409, "invalid_status", record.status)
    if record.status == "converged_pending_human" and record.decision_package is not None:
        return _json_error(409, "invalid_status", record.status)
    if record.paused:
        updated = await driver.resume_session(bench, session_id)
        return {
            "running": driver.is_running(bench, session_id),
            "session": updated.model_dump(),
        }
    await driver.run_session(bench, session_id)
    return {"running": driver.is_running(bench, session_id), "session": record.model_dump()}


@router.post("/discussion-sessions/{session_id}/pause")
async def pause_discussion(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    _actor_id, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    if record.status in driver.TERMINAL_STATUSES:
        return _json_error(409, "invalid_status", record.status)
    updated = await driver.pause_session(bench, session_id)
    return updated.model_dump()


@router.post("/discussion-sessions/{session_id}/resume")
async def resume_discussion(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    _actor_id, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    if record.status in driver.TERMINAL_STATUSES:
        return _json_error(409, "invalid_status", record.status)
    raw = await request.body()
    body: dict[str, Any] = {}
    if raw:
        payload = await _body(request)
        if payload is None:
            return _json_error(
                400, "validation_error", "request body must be a JSON object"
            )
        try:
            body = ResumeBody.model_validate(payload).model_dump()
        except ValidationError as exc:
            return _json_error(400, "validation_error", str(exc))
    updated = await driver.resume_session(
        bench, session_id, body.get("skip_bot_ids") or []
    )
    return updated.model_dump()


@router.post("/discussion-sessions/{session_id}/terminate")
async def terminate_discussion(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    _actor_id, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    payload = await _body(request)
    if payload is None:
        return _json_error(
            400, "validation_error", "request body must be a JSON object"
        )
    if payload.get("confirm") is not True:
        return _json_error(400, "validation_error", "confirm must be true")
    if record.status in {"approved", "rejected"}:
        return _json_error(409, "invalid_status", record.status)
    updated = await driver.terminate_session(bench, session_id)
    return updated.model_dump()


__all__ = ["router"]