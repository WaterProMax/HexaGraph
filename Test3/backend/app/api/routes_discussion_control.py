"""Control routes for the multi-bot discussion driver (run/pause/resume/terminate)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.bots.registry import BotNotFound
from app.discussion import driver, planning
from app.discussion.decision import _resolve_lock
from app.discussion.messages import LOG
from app.discussion.session_store import DiscussionSessionStore, SessionNotFound
from app.errors import ValidationFailed, user_message_for_category
from app.leader.steward import DiscussionSteward, InvalidParticipant, LeaderNotInProject
from app.memory.organizer import contains_secret
from app.storage.models import ProjectMembershipRow

router = APIRouter()


class ResumeBody(BaseModel):
    skip_bot_ids: list[str] = Field(default_factory=list)


class SupplementBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


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


@router.post("/discussion-sessions/{session_id}/supplement", status_code=201)
async def supplement_discussion(session_id: str, body: SupplementBody, request: Request) -> Any:
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    text = body.text.strip()
    if not text:
        return _json_error(400, "validation_error", "请填写补充信息")
    if contains_secret(text):
        return _json_error(400, "secret_in_body", "请删除补充信息中的密钥后重试")
    bench = request.app.state.workbench
    # The original snapshot and approvals stay immutable. A linked session
    # evaluates the new snapshot from the beginning using the same rules.
    async with _resolve_lock(bench), bench.db_session() as session:
        store = DiscussionSessionStore(session)
        record = await store.get_locked(session_id)
        if record.status in driver.TERMINAL_STATUSES:
            return _json_error(409, "invalid_status", record.status)
        requirements = f"{record.requirement_text}\n\n用户补充（以较新的说明为准）\n{text}"
        try:
            updated = await DiscussionSteward(session).create_session(
                record.project_id, actor, record.participant_bot_ids, requirements, record.budget,
                requirement_text=requirements, previous_session_id=session_id,
            )
        except (InvalidParticipant, LeaderNotInProject):
            return _json_error(409, "membership_changed", "项目成员已变更，请检查讨论团队")
        await store.save(record.model_copy(update={"status": "terminated", "paused": False}))
        await LOG.append(session, updated.session_id, "user", payload={"text": text, "event": "supplement"})
        await session.commit()
    await driver.terminate_session(bench, session_id)
    await driver.run_session(bench, updated.session_id)
    return updated.model_dump()


@router.post("/discussion-sessions/{session_id}/plan")
async def plan_discussion(session_id: str, request: Request) -> Any:
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    if record.status != "approved" or record.decision_package is None:
        return _json_error(409, "invalid_status", "需先确认需求规格")
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        member = await session.get(ProjectMembershipRow, (record.project_id, actor))
        if member is None or not member.is_leader:
            return _json_error(403, "forbidden", "只有项目 Leader 可以生成任务计划")
    try:
        run_id = await planning.prepare_run(bench, record)
    except BotNotFound:
        return _json_error(409, "leader_not_found", "找不到负责规划的 Leader")
    except driver.BotFailed as exc:
        return _json_error(502, exc.category, user_message_for_category(exc.category))
    except ValidationFailed as exc:
        return _json_error(422, "plan_validation_failed", str(exc))
    return {"run_id": run_id}


__all__ = ["router"]
