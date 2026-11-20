from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.bots.registry import BotNotFound, BotRegistry
from app.memory.access import MemoryAccessService, MemoryForbidden, is_project_member
from app.memory.organizer import contains_secret, organize_note
from app.memory.promotion import MemoryPromotionService, VisibilityNotProject
from app.memory.store import (
    MemoryNotFound,
    MemoryStore,
    MemoryVersionConflict,
    SecretInBody,
)
from app.schemas.memory import MemoryCreate, MemorySource

router = APIRouter()

_VALID_VISIBILITY = {"private", "project", "run"}


class PublishBody(BaseModel):
    expected_version: int


class SupersedeBody(BaseModel):
    expected_version: int
    body: dict
    sources: list[MemorySource]


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _free_note(body: MemoryCreate) -> str | None:
    """The raw text of a UI-typed private note, else None (structured bodies stay untouched)."""
    if body.visibility != "private" or set(body.body) != {"text"}:
        return None
    if not any(src.kind == "note" for src in body.sources):
        return None
    text = body.body["text"]
    return text.strip() if isinstance(text, str) and text.strip() else None


async def _actor(request: Request, session) -> tuple[str | None, JSONResponse | None]:
    actor = (request.headers.get("X-Bot-Id") or "").strip()
    if not actor:
        return None, _json_error(400, "validation_error", "X-Bot-Id header is required")
    try:
        await BotRegistry(session).get(actor)
    except BotNotFound:
        return None, _json_error(404, "bot_not_found", f"bot not found: {actor}")
    return actor, None


@router.post("/memory/records", status_code=201)
async def create_memory(request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        actor, error = await _actor(request, session)
        if error is not None:
            return error
        payload = await _body(request)
        if payload is None:
            return _json_error(400, "validation_error", "request body must be a JSON object")
        try:
            body = MemoryCreate.model_validate(payload)
        except ValidationError as exc:
            return _json_error(400, "validation_error", str(exc))
        try:
            owner = await BotRegistry(session).get(body.owner_bot_id)
        except BotNotFound:
            return _json_error(404, "bot_not_found", f"bot not found: {body.owner_bot_id}")
        if body.visibility == "project" and body.project_id not in bench.projects:
            return _json_error(
                404, "project_not_found", f"project not found: {body.project_id}"
            )
        raw_note = _free_note(body)
        if raw_note is not None and actor == body.owner_bot_id:
            if contains_secret(raw_note):
                return _json_error(400, "secret_in_body", "secret-like value in note")
            organized = await organize_note(bench.gateway, owner, raw_note)
            if organized is not None:
                body = body.model_copy(
                    update={
                        "title": organized["title"] or body.title,
                        "body": {"text": organized["text"]},
                    }
                )
        try:
            record = await MemoryAccessService(MemoryStore(session)).create(actor, body)
            await session.commit()
        except MemoryForbidden as exc:
            await session.rollback()
            return _json_error(403, "memory_forbidden", str(exc))
        except SecretInBody as exc:
            await session.rollback()
            return _json_error(400, "secret_in_body", str(exc))
    return JSONResponse(status_code=201, content=record.model_dump())


@router.get("/memory/records")
async def list_memory(
    request: Request,
    owner_bot_id: str | None = None,
    project_id: str | None = None,
    visibility: str | None = None,
) -> Any:
    bench = request.app.state.workbench
    if visibility is not None and visibility not in _VALID_VISIBILITY:
        return _json_error(400, "validation_error", "invalid visibility")
    async with bench.db_session() as session:
        actor, error = await _actor(request, session)
        if error is not None:
            return error
        if project_id is not None and project_id not in bench.projects:
            return _json_error(404, "project_not_found", f"project not found: {project_id}")
        if owner_bot_id is not None and visibility == "private" and owner_bot_id != actor:
            return _json_error(403, "memory_forbidden", "cannot list another bot's private memory")
        if project_id is not None and not await is_project_member(session, project_id, actor):
            return _json_error(403, "memory_forbidden", "actor is not a project member")
        items = await MemoryAccessService(MemoryStore(session)).list_visible(
            actor,
            owner_bot_id=owner_bot_id,
            project_id=project_id,
            visibility=visibility,
        )
    return {"items": [item.model_dump() for item in items]}


@router.get("/memory/records/{mem_id}")
async def get_memory(mem_id: str, request: Request, version: str | None = None) -> Any:
    bench = request.app.state.workbench
    parsed_version: int | None = None
    if version is not None:
        try:
            parsed_version = int(version)
        except ValueError:
            return _json_error(400, "validation_error", "version must be an integer")
    async with bench.db_session() as session:
        actor, error = await _actor(request, session)
        if error is not None:
            return error
        try:
            record = await MemoryAccessService(MemoryStore(session)).get(
                actor, mem_id, parsed_version
            )
        except MemoryNotFound:
            return _json_error(404, "memory_not_found", f"memory not found: {mem_id}")
        except MemoryForbidden as exc:
            return _json_error(403, "memory_forbidden", str(exc))
    return record.model_dump()


@router.post("/memory/records/{mem_id}/publish")
async def publish_memory(mem_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        actor, error = await _actor(request, session)
        if error is not None:
            return error
        payload = await _body(request)
        if payload is None:
            return _json_error(400, "validation_error", "request body must be a JSON object")
        try:
            body = PublishBody.model_validate(payload)
        except ValidationError as exc:
            return _json_error(400, "validation_error", str(exc))
        try:
            record = await MemoryPromotionService(MemoryStore(session)).publish(
                mem_id, body.expected_version, actor=actor
            )
            await session.commit()
        except MemoryNotFound:
            await session.rollback()
            return _json_error(404, "memory_not_found", f"memory not found: {mem_id}")
        except VisibilityNotProject as exc:
            await session.rollback()
            return _json_error(400, "visibility_not_project", str(exc))
        except MemoryForbidden as exc:
            await session.rollback()
            return _json_error(403, "memory_forbidden", str(exc))
        except MemoryVersionConflict as exc:
            await session.rollback()
            return _json_error(409, "memory_version_conflict", str(exc))
    return record.model_dump()


@router.post("/memory/records/{mem_id}/supersede")
async def supersede_memory(mem_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        actor, error = await _actor(request, session)
        if error is not None:
            return error
        payload = await _body(request)
        if payload is None:
            return _json_error(400, "validation_error", "request body must be a JSON object")
        try:
            body = SupersedeBody.model_validate(payload)
        except ValidationError as exc:
            return _json_error(400, "validation_error", str(exc))
        try:
            record = await MemoryPromotionService(MemoryStore(session)).supersede(
                mem_id,
                body.expected_version,
                body=body.body,
                sources=body.sources,
                actor=actor,
            )
            await session.commit()
        except MemoryNotFound:
            await session.rollback()
            return _json_error(404, "memory_not_found", f"memory not found: {mem_id}")
        except VisibilityNotProject as exc:
            await session.rollback()
            return _json_error(400, "visibility_not_project", str(exc))
        except MemoryForbidden as exc:
            await session.rollback()
            return _json_error(403, "memory_forbidden", str(exc))
        except MemoryVersionConflict as exc:
            await session.rollback()
            return _json_error(409, "memory_version_conflict", str(exc))
        except SecretInBody as exc:
            await session.rollback()
            return _json_error(400, "secret_in_body", str(exc))
    return record.model_dump()