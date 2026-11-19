from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.errors import (
    AgentOutputError,
    DeepSeekRetired,
    GrantRejected,
    IllegalTransition,
    ImportInProgress,
    RevisionConflict,
    ValidationFailed,
)
from app.events.bus import BUS
from app.execution.run_profile import run_approved_baseline_hashes, run_execution_profile
from app.schemas.design_input import DesignRunCreate
from app.schemas.execution_grant import ExecutionGrant, ExecutionGrantCreate
from app.services.runtime import Workbench

router = APIRouter()

SSE_HEARTBEAT_SECONDS = 15.0


class CreateProject(BaseModel):
    name: str
    profile: str = "python-pytest"


class CreateRun(BaseModel):
    idea: str


class GateResolve(BaseModel):
    decision: str
    payload: dict[str, Any] = {}
    expected_revision: int | None = None


class ControlBody(BaseModel):
    expected_revision: int
    reason: str = ""
    payload: dict[str, Any] = {}


class ConfirmBody(BaseModel):
    confirm: bool = False


class ScheduleRequest(BaseModel):
    task_codes: list[str] | None = None


class EnableExecutionProfileBody(BaseModel):
    execution_profile: Literal["granted_v1"]
    approved_baseline_hashes: dict[str, str]
    approved_plan_hash: str = ""
    allowed_tool_refs: list[str] = []


def wb(request: Request) -> Workbench:
    return request.app.state.workbench


def _retired(exc: DeepSeekRetired) -> HTTPException:
    """Controlled 410: the retired entry never started a request or changed state."""
    return HTTPException(
        status_code=410,
        detail={
            "category": "deepseek_retired",
            "summary": exc.message,
            "message": exc.message,
        },
    )


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    bench = getattr(request.app.state, "workbench", None)
    mode = getattr(bench, "schedule_mode", None) if bench is not None else None
    return {"status": "ok", "schedule_mode": mode if mode in {"auto", "manual"} else "manual"}


@router.post("/projects")
async def create_project(body: CreateProject, request: Request) -> dict[str, Any]:
    return wb(request).create_project(body.name, body.profile)


@router.get("/projects")
async def list_projects(request: Request) -> list[dict[str, Any]]:
    return list(wb(request).projects.values())


@router.post("/projects/{project_id}/runs")
async def create_run(project_id: str, body: CreateRun, request: Request) -> dict[str, Any]:
    bench = wb(request)
    if project_id not in bench.projects:
        raise HTTPException(404, "project not found")
    run = bench.create_run(project_id, body.idea)
    try:
        started = await bench.start_idea(run)
    except (AgentOutputError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"run": _run_view(run), "result": started}


@router.post("/projects/{project_id}/design-runs")
async def create_design_run(project_id: str, body: DesignRunCreate, request: Request) -> dict[str, Any]:
    """从设计规格原文创建运行：整理、检查并停在 DESIGN 确认关卡，不生成任务。"""
    bench = wb(request)
    if project_id not in bench.projects:
        raise HTTPException(404, "project not found")
    try:
        return await bench.create_design_run(project_id, body.text, body.source, body.title, body.provider)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc
    except ImportInProgress as exc:
        raise HTTPException(
            status_code=409,
            detail={"category": exc.category, "summary": exc.message, "run_id": exc.run_id},
        ) from exc
    except ValidationFailed as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs")
async def list_runs(request: Request) -> list[dict[str, Any]]:
    return [_run_view(r) for r in wb(request).runs.values()]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    return _run_view(_run(request, run_id))


@router.get("/runs/{run_id}/stages")
async def stages(run_id: str, request: Request) -> dict[str, Any]:
    run = _run(request, run_id)
    return {"current": run.engine.current, "history": run.engine.history}


@router.get("/runs/{run_id}/artifacts")
async def artifacts(run_id: str, request: Request) -> dict[str, Any]:
    return _run(request, run_id).artifacts


@router.get("/runs/{run_id}/discussion")
async def discussion(run_id: str, request: Request) -> dict[str, Any]:
    run = _run(request, run_id)
    return {
        "questions": run.artifacts.get("questions", []),
        "merge": run.artifacts.get("merge_rows", []),
        "utterances": run.artifacts.get("utterances", []),
        "issues": run.artifacts.get("issues", []),
    }


@router.get("/runs/{run_id}/todos")
async def todos(run_id: str, request: Request) -> list[dict[str, Any]]:
    return wb(request).todos(_run(request, run_id))


@router.post("/gates/{gate_id}/resolve")
async def resolve_gate(gate_id: str, body: GateResolve, request: Request) -> dict[str, Any]:
    bench = wb(request)
    run = next((r for r in bench.runs.values() if any(g["id"] == gate_id for g in r.gates)), None)
    if not run:
        raise HTTPException(404, "gate not found")
    try:
        return await bench.resolve_gate(run, gate_id, body.decision, body.payload, expected_revision=body.expected_revision)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (AgentOutputError, RuntimeError, ValidationFailed) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{run_id}/tasks")
async def tasks(run_id: str, request: Request) -> list[dict[str, Any]]:
    return list(_run(request, run_id).tasks.values())


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, request: Request) -> dict[str, Any]:
    for run in wb(request).runs.values():
        for task in run.tasks.values():
            if task["id"] == task_id or task["code"] == task_id:
                return task
    raise HTTPException(404, "task not found")


@router.post("/tasks/{task_id}/{action}")
async def task_control(task_id: str, action: str, body: ControlBody, request: Request) -> dict[str, Any]:
    bench = wb(request)
    for run in bench.runs.values():
        for code, task in run.tasks.items():
            if task["id"] == task_id or code == task_id:
                try:
                    return await bench.control_task(
                        run, code, action, body.expected_revision, body.reason, payload=body.payload
                    )
                except DeepSeekRetired as exc:
                    raise _retired(exc) from exc
                except RevisionConflict as exc:
                    raise HTTPException(409, str(exc)) from exc
                except GrantRejected as exc:
                    return _json_error(exc.status_code, exc.category, exc.message)
                except (IllegalTransition, ValidationFailed) as exc:
                    raise HTTPException(400, str(exc)) from exc
    raise HTTPException(404, "task not found")


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, request: Request) -> dict[str, Any]:
    return _run_view(wb(request).set_run_control(_run(request, run_id), "pause"))


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _run_view(wb(request).set_run_control(_run(request, run_id), "resume"))
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc


@router.post("/runs/{run_id}/terminate")
async def terminate_run(run_id: str, body: ConfirmBody, request: Request) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(400, "终止运行需二次确认")
    try:
        return _run_view(wb(request).set_run_control(_run(request, run_id), "terminate", confirm=True))
    except ValidationFailed as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{run_id}/budget")
async def budget(run_id: str, request: Request) -> dict[str, Any]:
    return wb(request).budget(_run(request, run_id))


@router.patch("/runs/{run_id}/limits")
async def patch_limits(run_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return wb(request).patch_limits(_run(request, run_id), body)
    except ValidationFailed as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{run_id}/trace")
async def trace(run_id: str, request: Request) -> list[dict[str, str]]:
    return _run(request, run_id).trace.matrix()


@router.get("/runs/{run_id}/trace/impact")
async def trace_impact(run_id: str, codes: str, request: Request) -> dict[str, Any]:
    return _run(request, run_id).trace.impact(codes.split(","))


@router.post("/runs/{run_id}/crs")
async def submit_cr(run_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
    flags = {k: v for k, v in body.items() if k not in {"description", "codes"}}
    try:
        return await wb(request).submit_cr(
            _run(request, run_id),
            body.get("description", ""),
            body.get("codes") or [],
            **flags,
        )
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc


@router.get("/runs/{run_id}/crs")
async def list_crs(run_id: str, request: Request) -> list[dict[str, Any]]:
    return _run(request, run_id).crs


@router.post("/crs/{code}/decision")
async def cr_decision(code: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
    bench = wb(request)
    run = next((r for r in bench.runs.values() if any(c["code"] == code for c in r.crs)), None)
    if run is None:
        raise HTTPException(404, "change request not found")
    body["code"] = code
    try:
        return await bench.decide_cr(run, body)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (IllegalTransition, ValidationFailed) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/runs/{run_id}/feedback/import")
async def import_feedback(run_id: str, body: dict[str, Any], request: Request) -> list[dict[str, Any]]:
    from app.settings import get_settings

    key = get_settings().feedback_hash_key
    if not key:
        raise HTTPException(400, "FEEDBACK_HASH_KEY required")
    try:
        return await wb(request).import_feedback(_run(request, run_id), body.get("rows") or [], key)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc


@router.get("/runs/{run_id}/feedback")
async def list_feedback(run_id: str, request: Request) -> dict[str, Any]:
    run = _run(request, run_id)
    return {"raw": run.raw_feedback, "items": run.feedback}


@router.get("/runs/{run_id}/events/history")
async def event_history(run_id: str, after: int = 0, request: Request = None) -> list[dict[str, Any]]:
    run = _run(request, run_id)
    return [e for e in run.events if e["seq"] > after]


@router.get("/runs/{run_id}/events")
async def event_sse(run_id: str, request: Request, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    run = _run(request, run_id)
    after = _parse_last_event_id(last_event_id)

    async def gen():
        # 先订阅再扫描，避免回放与订阅之间的事件丢失；以 seq 游标去重并保序。
        queue = BUS.subscribe(run_id)
        last = after

        def pending() -> list[str]:
            nonlocal last
            frames = []
            for event in list(run.events):
                if event["seq"] > last:
                    last = event["seq"]
                    frames.append(f"id: {event['seq']}\nevent: message\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
            return frames

        try:
            for frame in pending():
                yield frame
            yield ": ping\n\n"
            deadline = time.monotonic() + SSE_HEARTBEAT_SECONDS
            while True:
                try:
                    await asyncio.wait_for(queue.get(), max(deadline - time.monotonic(), 0))
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    deadline = time.monotonic() + SSE_HEARTBEAT_SECONDS
                    continue
                while not queue.empty():
                    queue.get_nowait()
                for frame in pending():
                    yield frame
        finally:
            BUS.unsubscribe(run_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _parse_last_event_id(value: str | None) -> int:
    try:
        return max(int((value or "0").strip() or 0), 0)
    except ValueError:
        return 0


@router.get("/config/models")
async def get_models(request: Request) -> dict[str, Any]:
    return wb(request).models.model_dump()


@router.put("/config/models")
async def put_models(body: dict[str, Any], request: Request) -> dict[str, Any]:
    from app.settings import ModelsFile

    new_models = ModelsFile.model_validate(body)
    # 更新 Workbench
    wb(request).models = new_models
    # 【修改点】关键：同步更新 Gateway，确保 PUT 后的配置立即生效
    wb(request).gateway.models = new_models
    return {"ok": True}


@router.post("/config/models/test")
async def test_models() -> dict[str, Any]:
    # 【修改点】不再返回假成功，真实检查密钥
    import os

    from app.settings import get_settings
    
    if not os.getenv("DASHSCOPE_API_KEY") and not get_settings().dashscope_api_key:
        raise HTTPException(status_code=400, detail="DASHSCOPE_API_KEY is not set. Cannot run live probe.")
    return {"ok": True, "note": "API key found. Use 'make check-models' to execute the live probe."}


def _json_error(status_code: int, category: str, detail: str) -> JSONResponse:
    """contracts C.5 error body: {"error_category": ..., "detail": ...}."""
    return JSONResponse(status_code=status_code, content={"error_category": category, "detail": detail})


@router.post("/runs/{run_id}/execution-grants", status_code=201)
async def create_execution_grant(run_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json_error(400, "validation_error", "request body must be a JSON object")
    if not isinstance(payload, dict):
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = ExecutionGrantCreate.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    bench = wb(request)
    run = bench.runs.get(run_id)
    if run is None:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    # execution_profile is server-owned. A legacy run cannot opt into grants via
    # this endpoint, and there is no route that downgrades granted_v1 to legacy.
    if run_execution_profile(run) != "granted_v1":
        return _json_error(403, "profile_not_granted_v1", "run is not granted_v1")
    if body.approved_baseline_hashes != run_approved_baseline_hashes(run):
        return _json_error(409, "baseline_stale", "approved_baseline_hashes do not match the run baseline")
    grant = ExecutionGrant(
        grant_id=str(uuid.uuid4()),
        run_id=run_id,
        status="active",
        created_at=datetime.now(timezone.utc).isoformat(),
        **body.model_dump(),
    )
    await bench.add_grant(grant)
    return JSONResponse(status_code=201, content=grant.model_dump())


@router.get("/runs/{run_id}/execution-grants")
async def list_execution_grants(run_id: str, request: Request) -> Any:
    bench = wb(request)
    if run_id not in bench.runs:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    grants = await bench.grants_for_run(run_id)
    return {"items": [grant.model_dump() for grant in grants]}


@router.post("/runs/{run_id}/execution-profile")
async def enable_execution_profile(run_id: str, request: Request) -> JSONResponse:
    """Server-owned enable path: granted_v1 only, never a legacy downgrade."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json_error(400, "validation_error", "request body must be a JSON object")
    if not isinstance(payload, dict):
        return _json_error(400, "validation_error", "request body must be a JSON object")
    try:
        body = EnableExecutionProfileBody.model_validate(payload)
    except ValidationError as exc:
        return _json_error(400, "validation_error", str(exc))
    bench = wb(request)
    run = bench.runs.get(run_id)
    if run is None:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    try:
        result = await bench.enable_granted_execution(
            run_id,
            body.approved_baseline_hashes,
            approved_plan_hash=body.approved_plan_hash,
            allowed_tool_refs=body.allowed_tool_refs,
        )
    except ValidationFailed as exc:
        message = str(exc)
        if "baseline" in message:
            return _json_error(409, "baseline_stale", message)
        return _json_error(400, "validation_error", message)
    return JSONResponse(status_code=200, content=result)


@router.get("/runs/{run_id}/execution-profile")
async def get_execution_profile(run_id: str, request: Request) -> Any:
    bench = wb(request)
    run = bench.runs.get(run_id)
    if run is None:
        return _json_error(404, "run_not_found", f"run not found: {run_id}")
    return {
        "run_id": run_id,
        "execution_profile": run_execution_profile(run),
        "approved_baseline_hashes": run_approved_baseline_hashes(run),
        "execution_safety_ready": bool(getattr(bench, "execution_safety_ready", False)),
    }


@router.post("/runs/{run_id}/schedule")
async def schedule(run_id: str, request: Request, body: ScheduleRequest | None = None) -> Any:
    run = _run(request, run_id)
    requested = None if body is None or body.task_codes is None else set(body.task_codes)
    try:
        started = await wb(request).schedule_once(run, task_codes=requested)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc
    except GrantRejected as exc:
        return _json_error(exc.status_code, exc.category, exc.message)
    return {"started": started}


@router.post("/runs/{run_id}/accept")
async def accept_run(run_id: str, request: Request) -> dict[str, Any]:
    run = _run(request, run_id)
    if "spec" not in run.artifacts:
        raise HTTPException(409, "SPEC not ready; run has no spec artifact yet")
    try:
        return await wb(request).accept(run)
    except DeepSeekRetired as exc:
        raise _retired(exc) from exc
    except GrantRejected as exc:
        return _json_error(exc.status_code, exc.category, exc.message)
    except (IllegalTransition, ValidationFailed) as exc:
        raise HTTPException(400, str(exc)) from exc


def _run(request: Request, run_id: str):
    run = wb(request).runs.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


def _run_view(run) -> dict[str, Any]:
    provenance = run.artifacts.get("provenance") or {}
    retired = provenance.get("mode") == "deepseek"
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "stage": run.engine.current,
        "revision": run.revision,
        "paused": run.paused,
        "idea": run.idea,
        "gates": run.gates,
        "event_count": len(run.events),
        "origin": "design_spec" if run.artifacts.get("design_input") else "idea",
        "provenance": provenance,
        # Read-only compatibility for snapshots captured by the retired DeepSeek
        # entry. ``provenance.mode`` is returned unchanged; this flag only marks it.
        "read_only": retired,
        "retired_mode": "deepseek" if retired else "",
        "retired_message": (
            "DeepSeek 专用入口已下线，该历史运行仅支持只读查看，不支持继续调用。" if retired else ""
        ),
    }