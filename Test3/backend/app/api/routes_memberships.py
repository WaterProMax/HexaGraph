from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.bots.registry import BotArchived, BotNotFound
from app.projects.membership import (
    LeaderAlreadySet,
    MembershipCreate,
    MembershipExists,
    MembershipNotFound,
    MembershipService,
    ProjectNotFound,
)

router = APIRouter()


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _service(bench, session) -> MembershipService:
    return MembershipService(session, project_exists=lambda project_id: project_id in bench.projects)


@router.post("/projects/{project_id}/memberships", status_code=201)
async def add_membership(project_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    if project_id not in bench.projects:
        return _json_error(404, "project_not_found", f"project not found: {project_id}")
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = MembershipCreate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    async with bench.db_session() as session:
        try:
            membership = await _service(bench, session).add(project_id, body)
            await session.commit()
        except ProjectNotFound:
            await session.rollback()
            return _json_error(404, "project_not_found", f"project not found: {project_id}")
        except BotNotFound:
            await session.rollback()
            return _json_error(404, "bot_not_found", f"bot not found: {body.bot_id}")
        except BotArchived:
            await session.rollback()
            return _json_error(403, "bot_archived", f"bot is archived: {body.bot_id}")
        except MembershipExists:
            await session.rollback()
            return _json_error(409, "membership_exists", "bot is already a member")
        except LeaderAlreadySet:
            await session.rollback()
            return _json_error(409, "leader_already_set", "project already has a leader")
    return JSONResponse(status_code=201, content=membership.model_dump())


@router.get("/projects/{project_id}/memberships")
async def list_memberships(project_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    if project_id not in bench.projects:
        return _json_error(404, "project_not_found", f"project not found: {project_id}")
    async with bench.db_session() as session:
        try:
            items = await _service(bench, session).list(project_id)
        except ProjectNotFound:
            return _json_error(404, "project_not_found", f"project not found: {project_id}")
    return {"items": [item.model_dump() for item in items]}


@router.delete("/projects/{project_id}/memberships/{bot_id}")
async def remove_membership(project_id: str, bot_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            await MembershipService(session).remove(project_id, bot_id)
            await session.commit()
        except MembershipNotFound:
            await session.rollback()
            return _json_error(
                404, "membership_not_found", f"membership not found: {project_id}/{bot_id}"
            )
    return Response(status_code=204)