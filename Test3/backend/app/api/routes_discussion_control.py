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
from app.discussion.session_store import (
    DiscussionSessionStore,
    InvalidStatus,
    SessionNotFound,
)
from app.errors import ValidationFailed, user_message_for_category
from app.leader.steward import DiscussionSteward, InvalidParticipant, LeaderNotInProject
from app.memory.organizer import contains_secret
from app.storage.models import ProjectMembershipRow
from app.workflow.admission import WorkflowRejected, assert_phase_admission

router = APIRouter()


class ResumeBody(BaseModel):
    skip_bot_ids: list[str] = Field(default_factory=list)
    expected_revision: int | None = None


class PauseBody(BaseModel):
    expected_revision: int | None = None
    reason: str = Field(default="", max_length=2000)


class SupplementBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class InterventionBody(BaseModel):
    expected_revision: int
    text: str = Field(min_length=1, max_length=2000)


class EndRoundBody(BaseModel):
    expected_revision: int
    reason: str = Field(default="", max_length=2000)
    confirm: bool = False


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


async def _optional_body(request: Request) -> dict[str, Any] | None:
    raw = await request.body()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
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
    if driver.is_manual_round_ended(record):
        # A manual end has no decision package and no auto-approval path; only
        # POST /rounds/start with the control revision may reopen it.
        return _json_error(409, "invalid_status", "manual_round_ended")
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
    payload = await _optional_body(request)
    if payload is None:
        return _json_error(
            400, "validation_error", "request body must be a JSON object"
        )
    try:
        body = PauseBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    try:
        requested = await driver.request_pause(
            bench,
            session_id,
            expected_revision=body.expected_revision,
            reason=body.reason,
        )
    except InvalidStatus as exc:
        return _json_error(409, "invalid_status", str(exc))
    if requested.decision_package is not None:
        # A decision package already exists, so no pause can happen.  Return the
        # current session immediately instead of waiting for an impossible stop.
        return requested.model_dump()
    # Bounded cooperative wait: the UI polls the returned snapshot when the
    # in-flight model call has not reached a safe checkpoint within the bound.
    updated = await driver.wait_until_paused(
        bench, session_id, timeout=driver.PAUSE_WAIT_SECONDS
    )
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
    try:
        updated = await driver.resume_session(
            bench,
            session_id,
            body.get("skip_bot_ids") or [],
            expected_revision=body.get("expected_revision"),
        )
    except InvalidStatus as exc:
        return _json_error(409, "invalid_status", str(exc))
    return updated.model_dump()


@router.post("/discussion-sessions/{session_id}/interventions")
async def add_discussion_intervention(session_id: str, request: Request) -> Any:
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None and actor is not None
    payload = await _body(request)
    if payload is None:
        return _json_error(
            400, "validation_error", "request body must be a JSON object"
        )
    try:
        body = InterventionBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    text = body.text.strip()
    if not 1 <= len(text) <= 2000:
        return _json_error(400, "validation_error", "请填写 1-2000 字的介入内容")
    if contains_secret(text):
        return _json_error(400, "secret_in_body", "请删除介入内容中的密钥后重试")
    if record.status in driver.TERMINAL_STATUSES:
        return _json_error(409, "invalid_status", record.status)
    bench = request.app.state.workbench
    try:
        updated = await driver.add_intervention(
            bench,
            session_id,
            expected_revision=body.expected_revision,
            text=text,
            actor=actor,
        )
    except InvalidStatus as exc:
        if str(exc) == "secret_in_body":
            return _json_error(400, "secret_in_body", "请删除介入内容中的密钥后重试")
        return _json_error(409, "invalid_status", str(exc))
    return updated.model_dump()


@router.post("/discussion-sessions/{session_id}/end-round")
async def end_discussion_round(session_id: str, request: Request) -> Any:
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None and actor is not None
    payload = await _body(request)
    if payload is None:
        return _json_error(
            400, "validation_error", "request body must be a JSON object"
        )
    try:
        body = EndRoundBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    if body.confirm is not True:
        return _json_error(400, "validation_error", "confirm must be true")
    if record.status in driver.TERMINAL_STATUSES:
        return _json_error(409, "invalid_status", record.status)
    bench = request.app.state.workbench
    try:
        updated = await driver.end_round(
            bench,
            session_id,
            expected_revision=body.expected_revision,
            actor=actor,
            reason=body.reason,
        )
    except InvalidStatus as exc:
        return _json_error(409, "invalid_status", str(exc))
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


@router.post("/discussion-sessions/{session_id}/design")
async def design_discussion(session_id: str, request: Request) -> Any:
    """SPEC 批准后进入第 5 步：整理 SPEC → 架构师写 DESIGN → 检查 + 双评审 → DESIGN 关卡。"""
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    bench = request.app.state.workbench
    try:
        assert_phase_admission("design", discussion=record)
    except WorkflowRejected as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_category": exc.category,
                "detail": exc.message,
                "workflow": bench.workflow_projection(None, discussion=record),
            },
        )
    if record.status != "approved" or record.decision_package is None:
        return _json_error(409, "invalid_status", "需先确认需求规格")
    async with bench.db_session() as session:
        member = await session.get(ProjectMembershipRow, (record.project_id, actor))
        if member is None or not member.is_leader:
            return _json_error(403, "forbidden", "只有项目 Leader 可以整理设计规格")
    try:
        run_id = await planning.prepare_design_run(bench, record)
    except BotNotFound:
        return _json_error(409, "leader_not_found", "找不到负责规划的 Leader")
    except driver.BotFailed as exc:
        return _json_error(502, exc.category, user_message_for_category(exc.category))
    except ValidationFailed as exc:
        return _json_error(422, "design_validation_failed", str(exc))
    return {"run_id": run_id}


@router.post("/discussion-sessions/{session_id}/plan")
async def plan_discussion(session_id: str, request: Request) -> Any:
    actor, record, error = await _leader_session(request)
    if error is not None:
        return error
    assert record is not None
    bench = request.app.state.workbench
    from app.workflow.projection import find_run_for_session

    run = find_run_for_session(bench.runs, record.session_id)
    try:
        assert_phase_admission("plan", discussion=record, run=run)
    except WorkflowRejected as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_category": exc.category,
                "detail": exc.message,
                "workflow": bench.workflow_projection(run, discussion=record),
            },
        )
    if record.status != "approved" or record.decision_package is None:
        return _json_error(409, "invalid_status", "需先确认需求规格")
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
