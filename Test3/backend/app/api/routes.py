from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.errors import AgentOutputError, IllegalTransition, ImportInProgress, RevisionConflict, ValidationFailed
from app.events.bus import BUS
from app.schemas.design_input import DesignRunCreate
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


def wb(request: Request) -> Workbench:
    return request.app.state.workbench


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
        return await bench.create_design_run(project_id, body.text, body.source, body.title)
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
                except RevisionConflict as exc:
                    raise HTTPException(409, str(exc)) from exc
                except (IllegalTransition, ValidationFailed) as exc:
                    raise HTTPException(400, str(exc)) from exc
    raise HTTPException(404, "task not found")


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, request: Request) -> dict[str, Any]:
    return _run_view(wb(request).set_run_control(_run(request, run_id), "pause"))


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Request) -> dict[str, Any]:
    return _run_view(wb(request).set_run_control(_run(request, run_id), "resume"))


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
    return await wb(request).submit_cr(
        _run(request, run_id),
        body.get("description", ""),
        body.get("codes") or [],
        **flags,
    )


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
    return await wb(request).import_feedback(_run(request, run_id), body.get("rows") or [], key)


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
    from app.settings import get_settings
    import os
    
    if not os.getenv("DASHSCOPE_API_KEY") and not get_settings().dashscope_api_key:
        raise HTTPException(status_code=400, detail="DASHSCOPE_API_KEY is not set. Cannot run live probe.")
    return {"ok": True, "note": "API key found. Use 'make check-models' to execute the live probe."}


@router.post("/runs/{run_id}/schedule")
async def schedule(run_id: str, request: Request) -> dict[str, Any]:
    started = await wb(request).schedule_once(_run(request, run_id))
    return {"started": started}


@router.post("/runs/{run_id}/accept")
async def accept_run(run_id: str, request: Request) -> dict[str, Any]:
    run = _run(request, run_id)
    if "spec" not in run.artifacts:
        raise HTTPException(409, "SPEC not ready; run has no spec artifact yet")
    try:
        return await wb(request).accept(run)
    except (IllegalTransition, ValidationFailed) as exc:
        raise HTTPException(400, str(exc)) from exc


def _run(request: Request, run_id: str):
    run = wb(request).runs.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


def _run_view(run) -> dict[str, Any]:
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
        "provenance": run.artifacts.get("provenance") or {},
    }