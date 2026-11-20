from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.schemas.skill_definition import SkillCreate
from app.skills.registry import SkillNotFound, SkillRegistry, SkillVersionExists

router = APIRouter()


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@router.post("/skills", status_code=201)
async def create_skill(request: Request) -> JSONResponse:
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = SkillCreate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            skill = await SkillRegistry(session).create(body)
            await session.commit()
        except SkillVersionExists:
            await session.rollback()
            return _json_error(
                409,
                "skill_version_exists",
                f"skill {body.skill_id}@{body.version} already exists",
            )
    return JSONResponse(status_code=201, content=skill.model_dump())


@router.get("/skills")
async def list_skills(request: Request) -> dict[str, Any]:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        items = await SkillRegistry(session).list_all()
    return {"items": [item.model_dump() for item in items]}


@router.get("/skills/{skill_id}/versions")
async def list_skill_versions(skill_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            items = await SkillRegistry(session).list_versions(skill_id)
        except SkillNotFound:
            return _json_error(404, "skill_not_found", f"skill not found: {skill_id}")
    return {"items": [item.model_dump() for item in items]}