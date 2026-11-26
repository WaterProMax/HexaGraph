"""HTTP routes for task/role scoped manual memory (M subsystem).

``X-Bot-Id`` is a local identity declaration, never strong authentication: the
service still resolves project membership/leadership from SQLite.  The router is
registered by the integration owner; this module only defines paths and the
JSON error envelope shared with the other memory routes.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.memory.task_context import (
    TaskMemoryConflict,
    TaskMemoryForbidden,
    TaskMemoryNotFound,
    delete_task_role_manual,
    read_task_role_memory,
    save_task_role_manual,
)
from app.schemas.task_agent_memory import TASK_ROLES, TaskRoleMemoryUpdate

router = APIRouter()

_HEADER = "X-Bot-Id"


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


def _actor(request: Request) -> tuple[str | None, JSONResponse | None]:
    actor = (request.headers.get(_HEADER) or "").strip()
    if not actor:
        return None, _json_error(400, "validation_error", f"{_HEADER} header is required")
    return actor, None


def _role_error(role: str) -> JSONResponse | None:
    if role not in TASK_ROLES:
        return _json_error(422, "validation_error", "role must be 'coder' or 'tester'")
    return None


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _service_error(exc: Exception) -> JSONResponse:
    """Map domain exceptions onto the shared ``{error_category, detail}`` shape."""

    if isinstance(exc, TaskMemoryNotFound):
        return _json_error(404, "task_memory_not_found", str(exc))
    if isinstance(exc, TaskMemoryForbidden):
        return _json_error(403, "forbidden", str(exc))
    if isinstance(exc, TaskMemoryConflict):
        if exc.code == "run_busy":
            # The run batch holds the per-run write lock (model calls included);
            # fail fast and retryable instead of blocking the HTTP request for
            # the whole batch.
            return _json_error(409, "run_busy", "run_busy")
        if exc.code in {"revision_conflict", "role_mismatch"}:
            return _json_error(409, exc.code, str(exc))
        return _json_error(422, "validation_error", exc.code)
    raise exc


@router.get("/runs/{run_id}/tasks/{task_code}/role-memory/{role}")
async def get_task_role_memory(run_id: str, task_code: str, role: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    role_error = _role_error(role)
    if role_error is not None:
        return role_error
    try:
        return await read_task_role_memory(bench, actor or "", run_id, task_code, role)
    except (TaskMemoryNotFound, TaskMemoryForbidden, TaskMemoryConflict) as exc:
        return _service_error(exc)


@router.put("/runs/{run_id}/tasks/{task_code}/role-memory/{role}")
async def put_task_role_memory(run_id: str, task_code: str, role: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    role_error = _role_error(role)
    if role_error is not None:
        return role_error
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = TaskRoleMemoryUpdate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(422, "validation_error", str(exc))
    try:
        return await save_task_role_manual(
            bench,
            actor or "",
            run_id,
            task_code,
            role,
            body.expected_revision,
            body.manual_text,
        )
    except (TaskMemoryNotFound, TaskMemoryForbidden, TaskMemoryConflict) as exc:
        return _service_error(exc)


@router.delete("/runs/{run_id}/tasks/{task_code}/role-memory/{role}")
async def delete_task_role_memory(
    run_id: str,
    task_code: str,
    role: str,
    request: Request,
    expected_revision: str | None = None,
) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    role_error = _role_error(role)
    if role_error is not None:
        return role_error
    if expected_revision is None:
        return _json_error(422, "validation_error", "expected_revision query parameter is required")
    try:
        expected = int(expected_revision)
    except ValueError:
        return _json_error(422, "validation_error", "expected_revision must be an integer")
    if expected < 0:
        return _json_error(422, "validation_error", "expected_revision must be >= 0")
    try:
        return await delete_task_role_manual(
            bench, actor or "", run_id, task_code, role, expected
        )
    except (TaskMemoryNotFound, TaskMemoryForbidden, TaskMemoryConflict) as exc:
        return _service_error(exc)


__all__ = ["router"]