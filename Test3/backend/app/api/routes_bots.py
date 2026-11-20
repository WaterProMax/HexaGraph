from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.bots.registry import (
    BotAlreadyArchived,
    BotArchived,
    BotNameConflict,
    BotNotFound,
    BotRegistry,
)
from app.llm.bot_secrets import BotSecretStore
from app.llm.catalog import is_known_provider
from app.schemas.bot import BotCreate, BotPatch

router = APIRouter()

_VALID_STATUS = {"active", "archived"}


def _secret_store(request: Request) -> BotSecretStore | None:
    data_dir = getattr(request.app.state.workbench, "data_dir", None)
    return BotSecretStore(data_dir) if data_dir is not None else None


def _key_value(secret: Any) -> str | None:
    """Plain key from a write-only SecretStr; None when not supplied."""
    return None if secret is None else secret.get_secret_value().strip()


def _flagged(request: Request, bot: Any, ids: set[str] | None = None) -> dict[str, Any]:
    """Bot dict plus a read-only ``has_api_key`` flag; the key itself never leaves the store."""
    store = _secret_store(request)
    if ids is None:
        ids = store.ids() if store is not None else set()
    return {**bot.model_dump(), "has_api_key": bot.bot_id in ids}


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@router.post("/bots", status_code=201)
async def create_bot(request: Request) -> JSONResponse:
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = BotCreate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    api_key = _key_value(body.api_key)
    store = _secret_store(request)
    if api_key:
        if not is_known_provider(body.provider_ref):
            return _json_error(400, "validation_error", f"unknown provider: {body.provider_ref}")
        if store is None:
            return _json_error(500, "config_error", "server has no data directory for API keys")
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            bot = await BotRegistry(session).create(body)
            await session.commit()
        except BotNameConflict:
            await session.rollback()
            return _json_error(
                409, "bot_name_conflict", f"display_name already exists: {body.display_name}"
            )
    if api_key and store is not None:
        store.set(bot.bot_id, api_key)
    return JSONResponse(status_code=201, content=_flagged(request, bot))


@router.get("/bots")
async def list_bots(request: Request, status: str | None = None) -> Any:
    if status is not None and status not in _VALID_STATUS:
        return _json_error(
            400, "validation_error", "status must be one of: active, archived"
        )
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        items = await BotRegistry(session).list_all(status)
    store = _secret_store(request)
    ids = store.ids() if store is not None else set()
    return {"items": [_flagged(request, item, ids) for item in items]}


@router.get("/bots/{bot_id}")
async def get_bot(bot_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            bot = await BotRegistry(session).get(bot_id)
        except BotNotFound:
            return _json_error(404, "bot_not_found", f"bot not found: {bot_id}")
    return _flagged(request, bot)


@router.patch("/bots/{bot_id}")
async def patch_bot(bot_id: str, request: Request) -> Any:
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        patch = BotPatch.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    api_key = _key_value(patch.api_key)
    store = _secret_store(request)
    if api_key and store is None:
        return _json_error(500, "config_error", "server has no data directory for API keys")
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        registry = BotRegistry(session)
        try:
            if api_key:
                current = await registry.get(bot_id)
                if not is_known_provider(patch.provider_ref or current.provider_ref):
                    return _json_error(400, "validation_error", "unknown provider")
            bot = await registry.update(bot_id, patch)
            pin = await registry.latest_pin(bot_id)
            await session.commit()
        except BotNotFound:
            await session.rollback()
            return _json_error(404, "bot_not_found", f"bot not found: {bot_id}")
        except BotArchived:
            await session.rollback()
            return _json_error(409, "bot_archived", "archived bot cannot change its pin")
        except BotNameConflict:
            await session.rollback()
            return _json_error(409, "bot_name_conflict", "display_name already exists")
        except ValidationError as exc:
            await session.rollback()
            return _json_error(400, "validation_error", str(exc))
    if store is not None and api_key is not None:
        if api_key:
            store.set(bot_id, api_key)
        else:
            store.delete(bot_id)
    content = _flagged(request, bot)
    content["pin_revision"] = pin["revision"]
    return JSONResponse(status_code=200, content=content)


@router.post("/bots/{bot_id}/archive")
async def archive_bot(bot_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    async with bench.db_session() as session:
        try:
            bot = await BotRegistry(session).archive(bot_id)
            await session.commit()
        except BotNotFound:
            await session.rollback()
            return _json_error(404, "bot_not_found", f"bot not found: {bot_id}")
        except BotAlreadyArchived:
            await session.rollback()
            return _json_error(409, "bot_already_archived", f"bot already archived: {bot_id}")
    store = _secret_store(request)
    if store is not None:
        store.delete(bot.bot_id)
    return {"bot_id": bot.bot_id, "status": bot.status}