"""Honest mode/evidence labels for runs and acceptance results.

Model source and execution/verification are independent dimensions; a scripted
acceptance must never be presented as a real test, and a real model that only
generated code must not be presented as a real execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.llm.providers import ReplayProvider, ScriptedProvider
from app.workflow.stages import ACCEPTANCE_GATE_KIND

_EVIDENCE_LEVELS = ("not_run", "scripted", "real_model", "real_execution")

_EXECUTED_TASK_STATES = {
    "running",
    "verifying",
    "done",
    "failed",
    "needs_human",
    "blocked",
    "skipped",
    "cancelled",
}


def _provider(bench: Any) -> Any:
    return getattr(getattr(bench, "gateway", None), "provider", None)


def model_mode_for(bench: Any, run: Any | None = None) -> str:
    provider = _provider(bench)
    calls = int(((getattr(run, "artifacts", None) or {}).get("model_calls") or 0)) if run is not None else 0
    inferred = bool((getattr(run, "artifacts", None) or {}).get("plan")) if run is not None else False
    if isinstance(provider, (ScriptedProvider, ReplayProvider)):
        return "scripted" if calls or inferred else "not_called"
    return "real" if calls or inferred else "not_called"


def execution_mode_for(bench: Any, run: Any) -> str:
    tasks = getattr(run, "tasks", None) or {}
    kinds: set[str] = set()
    has_attempt = False
    for task in tasks.values():
        task = task or {}
        if task.get("attempt"):
            has_attempt = True
        for item in task.get("evidence") or []:
            if isinstance(item, dict) and item.get("kind"):
                kinds.add(str(item["kind"]))
    if not kinds and not has_attempt:
        return "not_run"
    real_kinds = kinds - {"simulated"}
    if getattr(bench, "simulated_executor", None) is not None:
        return "simulated"
    if kinds and not real_kinds:
        return "simulated"
    return "real"


def _acceptance_gate(run: Any) -> dict[str, Any] | None:
    for gate in reversed(list(getattr(run, "gates", None) or [])):
        if gate.get("kind") == ACCEPTANCE_GATE_KIND:
            return gate
    return None


def verification_status_for(run: Any) -> str:
    gate = _acceptance_gate(run)
    if gate is None:
        return "unknown" if getattr(run, "artifacts", {}).get("acceptance") else "not_run"
    status = str(gate.get("status") or "")
    if status == "pending":
        return "unknown"
    if status == "rejected":
        return "failed"
    payload = gate.get("payload") or {}
    if bool(payload.get("pass")):
        return "passed"
    # A failed acceptance approved with a written reason is a human override,
    # never a test pass.
    return "overridden"


def verification_label_for(level: str, status: str = "") -> str:
    if status == "overridden":
        return "人工覆盖（原验收未通过）"
    if level == "real_execution":
        return "真实执行验收"
    if level == "scripted":
        return "脚本/模拟验收"
    if level == "real_model":
        return "仅真实模型生成，未真实执行"
    return "尚未运行"


def evidence_for_run(bench: Any, run: Any) -> dict[str, Any]:
    model_mode = model_mode_for(bench, run)
    execution_mode = execution_mode_for(bench, run)
    verification_status = verification_status_for(run)
    if verification_status == "overridden":
        level = "real_execution" if execution_mode == "real" else (
            "scripted" if execution_mode == "simulated" else "not_run"
        )
    elif execution_mode == "real" and verification_status in {"passed", "failed"}:
        level = "real_execution"
    elif model_mode == "real":
        level = "real_model"
    elif model_mode == "scripted" and (
        (getattr(run, "artifacts", {}).get("plan"))
        or getattr(run, "tasks", None)
        or verification_status != "not_run"
    ):
        level = "scripted"
    else:
        level = "not_run"
    if level not in _EVIDENCE_LEVELS:
        level = "not_run"
    gate = _acceptance_gate(run)
    return {
        "level": level,
        "model_mode": model_mode,
        "execution_mode": execution_mode,
        "verification_status": verification_status,
        "verification_label": verification_label_for(level, verification_status),
        "verification": {
            "status": verification_status,
            "tool": "pytest",
            "command": "",
            "exit_code": None,
            "artifact_ref": (gate or {}).get("id") or "",
        },
        "source": f"run:{getattr(run, 'id', '')}",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "project_id": str(getattr(run, "project_id", "") or ""),
        "run_id": str(getattr(run, "id", "") or ""),
    }


__all__ = [
    "evidence_for_run",
    "execution_mode_for",
    "model_mode_for",
    "verification_label_for",
    "verification_status_for",
]