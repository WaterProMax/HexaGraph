from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.schemas.skill_definition import SkillCreate
from app.settings import get_settings
from app.skills.github_import import SkillImportError, fetch_skill
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


@router.post("/skills/import")
async def import_skill(request: Request) -> JSONResponse:
    """Register a skill from a public GitHub repo; version = commit sha, no tool grants."""
    payload = await _body(request)
    url = payload.get("url") if payload else None
    if not isinstance(url, str) or not url.strip():
        return _json_error(400, "validation_error", "url is required")
    transport = getattr(request.app.state, "skill_import_transport", None)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=8.0),
        follow_redirects=False,
        trust_env=bool(get_settings().test3_http_trust_env),
        transport=transport,
    ) as client:
        try:
            body = await fetch_skill(url, client)
        except SkillImportError as exc:
            return _json_error(exc.status_code, exc.category, exc.detail)
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        registry = SkillRegistry(session)
        try:
            skill = await registry.create(body)
            await session.commit()
            status = 201
        except SkillVersionExists:
            # Same commit imported before: the stored definition is immutable, reuse it.
            await session.rollback()
            existing = await registry.list_versions(body.skill_id)
            skill = next(item for item in existing if item.version == body.version)
            status = 200
    return JSONResponse(status_code=status, content=skill.model_dump())


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