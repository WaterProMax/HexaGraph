from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.discussion.models import DiscussionBudget
from app.discussion.session_store import Forbidden, InvalidStatus, SessionNotFound
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
    requirement_snapshot: dict
    budget: DiscussionBudget | None = None


class GroupBody(BaseModel):
    participant_bot_ids: list[str] | None = None


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