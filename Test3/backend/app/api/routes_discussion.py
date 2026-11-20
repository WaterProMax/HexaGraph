from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.discussion.converge import build_round_state, should_converge
from app.discussion.cross_review import (
    DuplicateReview,
    ProposalNotFound,
    SelfReviewForbidden,
    submit_review,
)
from app.discussion.decision import (
    InvalidDecision,
    RunNotFound,
    resolve_decision,
    submit_decision,
)
from app.discussion.models import DiscussionBudget, ReviewBallot
from app.discussion.proposals import (
    BudgetExhausted,
    DuplicateProposal,
    list_proposals,
    start_round,
    submit_proposal,
)
from app.discussion.session_store import (
    DiscussionSessionStore,
    Forbidden,
    InvalidStatus,
    NotParticipant,
    SessionNotFound,
    retry_locked,
)
from app.leader.steward import (
    DiscussionSteward,
    InvalidParticipant,
    LeaderNotInProject,
    ProjectNotFound,
)

router = APIRouter()


class CreateSessionBody(BaseModel):
    leader_bot_id: str
    participant_bot_ids: list[str]
    requirement_snapshot: str | dict
    budget: DiscussionBudget | None = None


class GroupBody(BaseModel):
    participant_bot_ids: list[str] | None = None


class StartRoundBody(BaseModel):
    round: int | None = None


class ProposalBody(BaseModel):
    author_bot_id: str
    body_md: str


class ConvergeBody(BaseModel):
    tokens_used: int = 0
    elapsed_seconds: int = 0
    dissent_items: list[str] = []


class SubmitDecisionBody(BaseModel):
    body_md: str
    dissent_items: list[str] = []


class ResolveBody(BaseModel):
    decision: str
    comment: str | None = None
    run_id: str | None = None


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


def _actor(request: Request) -> tuple[str | None, JSONResponse | None]:
    actor = (request.headers.get("X-Bot-Id") or "").strip()
    if not actor:
        return None, _json_error(400, "validation_error", "X-Bot-Id header is required")
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


@router.post("/projects/{project_id}/discussion-sessions", status_code=201)
async def create_session(project_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = CreateSessionBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    if project_id not in bench.projects:
        return _json_error(404, "project_not_found", f"project not found: {project_id}")
    if body.leader_bot_id != actor:
        return _json_error(403, "forbidden", "leader_bot_id must match X-Bot-Id")
    async with bench.db_session() as session:
        steward = DiscussionSteward(session, project_exists=lambda pid: pid in bench.projects)
        try:
            record = await steward.create_session(
                project_id,
                body.leader_bot_id,
                body.participant_bot_ids,
                body.requirement_snapshot,
                body.budget,
            )
            await session.commit()
        except ProjectNotFound:
            await session.rollback()
            return _json_error(404, "project_not_found", f"project not found: {project_id}")
        except LeaderNotInProject:
            await session.rollback()
            return _json_error(
                409, "leader_not_in_project", "leader_bot_id is not the project leader"
            )
        except InvalidParticipant as exc:
            await session.rollback()
            return _json_error(400, "validation_error", str(exc))
    return JSONResponse(status_code=201, content=record.model_dump())


@router.post("/discussion-sessions/{session_id}/group")
async def group_session(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _optional_body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = GroupBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        steward = DiscussionSteward(session, project_exists=lambda pid: pid in bench.projects)
        try:
            record = await steward.group(
                session_id,
                actor_bot_id=actor,
                participant_bot_ids=body.participant_bot_ids,
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except Forbidden as exc:
            await session.rollback()
            return _json_error(403, "forbidden", str(exc))
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
        except InvalidParticipant as exc:
            await session.rollback()
            return _json_error(400, "validation_error", str(exc))
    return record.model_dump()

@router.post("/discussion-sessions/{session_id}/rounds/start")
async def start_session_round(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _optional_body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = StartRoundBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        try:
            record = await start_round(
                session_id, body.round, actor_bot_id=actor, session=session
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except Forbidden as exc:
            await session.rollback()
            return _json_error(403, "forbidden", str(exc))
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
        except BudgetExhausted as exc:
            await session.commit()
            return _json_error(409, "budget_exhausted", str(exc))
    return record.model_dump()


@router.post("/discussion-sessions/{session_id}/proposals", status_code=201)
async def create_proposal(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = ProposalBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    if body.author_bot_id != actor:
        return _json_error(403, "forbidden", "author_bot_id must match X-Bot-Id")
    async with bench.db_session() as session:
        try:
            result = await submit_proposal(
                session_id, body.author_bot_id, body.body_md, session=session
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except Forbidden as exc:
            await session.rollback()
            return _json_error(403, "forbidden", str(exc))
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
        except NotParticipant as exc:
            await session.rollback()
            return _json_error(403, "not_participant", str(exc))
        except DuplicateProposal as exc:
            await session.rollback()
            return _json_error(409, "duplicate_proposal", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/discussion-sessions/{session_id}/proposals")
async def get_proposals(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    async with bench.db_session() as session:
        try:
            items = await list_proposals(session_id, actor, session=session)
        except SessionNotFound:
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except NotParticipant as exc:
            return _json_error(403, "not_participant", str(exc))
        except InvalidStatus as exc:
            return _json_error(409, "invalid_status", str(exc))
    return {"items": items}


@router.post("/discussion-sessions/{session_id}/reviews", status_code=201)
async def create_review(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        ballot = ReviewBallot.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    if ballot.reviewer_bot_id != actor:
        return _json_error(403, "forbidden", "reviewer_bot_id must match X-Bot-Id")
    async with bench.db_session() as session:
        try:
            result = await submit_review(session_id, ballot, session=session)
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
        except NotParticipant as exc:
            await session.rollback()
            return _json_error(403, "not_participant", str(exc))
        except ProposalNotFound as exc:
            await session.rollback()
            return _json_error(404, "proposal_not_found", str(exc))
        except SelfReviewForbidden as exc:
            await session.rollback()
            return _json_error(409, "self_review_forbidden", str(exc))
        except DuplicateReview as exc:
            await session.rollback()
            return _json_error(409, "duplicate_review", str(exc))
    return JSONResponse(status_code=201, content=result)


_CONVERGE_STATUS = {
    "budget_exhausted": "budget_exhausted",
    "submit_human": "converged_pending_human",
    "no_improvement": "converged_pending_human",
    "revise": "round_n_revise",
}


async def _converge_once(session, session_id: str, actor: str, body: ConvergeBody):
    store = DiscussionSessionStore(session)
    record = await store.get_locked(session_id)
    if actor != record.leader_bot_id and actor not in record.participant_bot_ids:
        raise Forbidden("only the leader or a participant can converge")
    if record.status != "cross_review":
        raise InvalidStatus(record.status)
    state = await build_round_state(
        session,
        record,
        tokens_used=body.tokens_used,
        elapsed_seconds=body.elapsed_seconds,
        extra_dissent=body.dissent_items,
    )
    action, reason = should_converge(state)
    updated = record.model_copy(update={"status": _CONVERGE_STATUS[action]})
    await store.save(updated)
    return action, reason, updated, state.dissent_items


@router.post("/discussion-sessions/{session_id}/converge")
async def converge_session(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _optional_body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = ConvergeBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        try:
            action, reason, record, dissent_items = await retry_locked(
                session,
                lambda: _converge_once(session, session_id, actor, body),
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except Forbidden as exc:
            await session.rollback()
            return _json_error(403, "forbidden", str(exc))
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
    return {
        "action": action,
        "reason": reason,
        "session": record.model_dump(),
        "dissent_items": dissent_items,
    }


@router.post("/discussion-sessions/{session_id}/submit-decision", status_code=201)
async def submit_session_decision(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = SubmitDecisionBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        try:
            package = await submit_decision(
                session_id,
                body.body_md,
                body.dissent_items,
                actor_bot_id=actor,
                session=session,
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except Forbidden as exc:
            await session.rollback()
            return _json_error(403, "forbidden", str(exc))
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
    return JSONResponse(status_code=201, content=package.model_dump())


@router.post("/discussion-sessions/{session_id}/resolve")
async def resolve_session_decision(session_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = ResolveBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        try:
            record = await resolve_decision(
                session_id,
                body.decision,
                body.comment,
                run_id=body.run_id,
                actor_bot_id=actor,
                bench=bench,
                session=session,
            )
            await session.commit()
        except SessionNotFound:
            await session.rollback()
            return _json_error(404, "session_not_found", f"session not found: {session_id}")
        except InvalidStatus as exc:
            await session.rollback()
            return _json_error(409, "invalid_status", str(exc))
        except InvalidDecision as exc:
            await session.rollback()
            return _json_error(400, "validation_error", str(exc))
        except RunNotFound as exc:
            await session.rollback()
            return _json_error(404, "run_not_found", str(exc))
    return record.model_dump()
