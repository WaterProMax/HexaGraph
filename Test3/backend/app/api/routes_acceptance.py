"""Module acceptance and defect HTTP routes (P5, contracts C.5.7)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.execution.acceptance import (
    AcceptanceValidation,
    DefectCreate,
    list_acceptances,
    list_defects,
)

router = APIRouter()


class ModuleAcceptanceBody(BaseModel):
    module_id: str
    task_codes: list[str] = []
    status: str
    evidence_uris: list[str] = []
    reviewer: str = ""
    comment: str = ""
    model_self_review: bool = False


class DefectBody(BaseModel):
    task_code: str
    module_id: str
    related_requirement_id: str | None = None
    evidence_uris: list[str] = []
    detail: str


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


@router.post("/runs/{run_id}/module-acceptances", status_code=201)
async def create_module_acceptance(run_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    run = bench.runs.get(run_id)
    if run is None:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = ModuleAcceptanceBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    if body.model_self_review:
        # Model self review is never acceptance evidence.
        return _json_error(400, "validation_error", "model_self_review is not valid acceptance evidence")
    if body.reviewer and body.reviewer != actor:
        return _json_error(403, "forbidden", "reviewer must match X-Bot-Id")
    if body.status not in {"pending", "accepted", "rejected"}:
        return _json_error(400, "validation_error", f"unknown acceptance status: {body.status}")
    try:
        acceptance = await bench.record_module_acceptance(
            run,
            {
                "module_id": body.module_id,
                "task_codes": body.task_codes,
                "status": body.status,
                "evidence_uris": body.evidence_uris,
                "reviewer": body.reviewer or actor,
                "comment": body.comment,
            },
            actor=actor,
        )
    except AcceptanceValidation as exc:
        return _json_error(400, "validation_error", str(exc))
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    from app.workflow.evidence import evidence_for_run

    return JSONResponse(
        status_code=201,
        content={
            **acceptance.model_dump(),
            "decision": acceptance.status,
            "evidence_uris": acceptance.evidence_uris,
            "run_evidence": evidence_for_run(bench, run),
        },
    )


@router.post("/runs/{run_id}/defects", status_code=201)
async def create_defect(run_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    run = bench.runs.get(run_id)
    if run is None:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    payload = await _body(request)
    if payload is None:
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        data = DefectCreate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    try:
        defect = await bench.record_defect(run, data.model_dump(), actor=actor)
    except AcceptanceValidation as exc:
        return _json_error(400, "validation_error", str(exc))
    from app.workflow.evidence import evidence_for_run

    return JSONResponse(
        status_code=201,
        content={
            **defect.model_dump(),
            "decision": defect.status,
            "evidence_uris": defect.evidence_uris,
            "run_evidence": evidence_for_run(bench, run),
        },
    )


__all__ = ["router"]

@router.get("/runs/{run_id}/defects")
async def get_defects(run_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    if run_id not in bench.runs:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    async with bench.db_session() as session:
        items = await list_defects(session, run_id)
    from app.workflow.evidence import evidence_for_run

    return {
        "items": [item.model_dump() for item in items],
        "run_evidence": evidence_for_run(bench, bench.runs[run_id]),
    }


@router.get("/runs/{run_id}/module-acceptances")
async def get_module_acceptances(run_id: str, request: Request) -> Any:
    bench = request.app.state.workbench
    actor, error = _actor(request)
    if error is not None:
        return error
    if run_id not in bench.runs:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    async with bench.db_session() as session:
        items = await list_acceptances(session, run_id)
    from app.workflow.evidence import evidence_for_run

    return {
        "items": [item.model_dump() for item in items],
        "run_evidence": evidence_for_run(bench, bench.runs[run_id]),
    }
