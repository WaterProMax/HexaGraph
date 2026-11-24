"""Pure, read-only workflow projection.

The projection never writes and never becomes a second authority: it is derived
from the existing discussion record, the run snapshot, its gates and (optionally)
grants.  If the sources disagree about project/session binding, the projection
fails closed to ``blocked`` instead of silently rewriting history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from app.workflow.stages import (
    ACCEPTANCE_GATE_KIND,
    DISCUSSION_BLOCKED,
    PLAN_GATE_KIND,
    discussion_stage,
)

_ACTIVE_TASK_STATES = {"running", "verifying"}
_FINISHED_TASK_STATES = {"done", "skipped", "cancelled"}
_DEAD_TASK_STATES = {"failed", "needs_human", "blocked", "stale", "upstream_bad"}


@dataclass
class WorkflowProjection:
    stage: str
    status: str
    project_id: str = ""
    session_id: str | None = None
    run_id: str | None = None
    spec_approved: bool = False
    plan_approved: bool = False
    blocked: list[dict[str, str]] = field(default_factory=list)
    baseline_hashes: dict[str, str] = field(default_factory=dict)
    model_mode: str = "not_run"
    execution_mode: str = "not_run"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _blocked(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _last_gate(run: Any, kind: str) -> dict[str, Any] | None:
    for gate in reversed(list(getattr(run, "gates", None) or [])):
        if gate.get("kind") == kind:
            return gate
    return None


def _task_states(run: Any) -> list[str]:
    tasks = getattr(run, "tasks", None) or {}
    return [str((task or {}).get("state") or "") for task in tasks.values()]


def _hashes(run: Any) -> dict[str, str]:
    try:
        from app.execution.run_profile import run_approved_baseline_hashes

        return dict(run_approved_baseline_hashes(run))
    except Exception:  # noqa: BLE001 - projection must stay read-only and total
        raw = getattr(run, "approved_baseline_hashes", None)
        return {str(key): str(value) for key, value in (raw or {}).items()}


def _spec_approved(discussion: Any, run: Any, plan_gate: dict[str, Any] | None) -> bool:
    if discussion is not None and getattr(discussion, "status", "") == "approved":
        return True
    hashes = _hashes(run) if run is not None else {}
    if "SPEC" in hashes:
        return True
    return bool(plan_gate)


def _run_stage(run: Any, *, blocked: list[dict[str, str]]) -> str:
    plan_gate = _last_gate(run, PLAN_GATE_KIND)
    acceptance_gate = _last_gate(run, ACCEPTANCE_GATE_KIND)
    hashes = _hashes(run)
    plan_approved = "PLAN" in hashes or bool(plan_gate and plan_gate.get("status") == "approved")
    tasks = getattr(run, "tasks", None) or {}
    states = _task_states(run)

    if str(getattr(run, "status", "")) == "done":
        return "accepted"
    if bool(getattr(run, "paused", False)):
        blocked.append(_blocked("run_paused", "run is paused; no new execution is dispatched"))
        return "blocked"
    if str(getattr(run, "status", "")) == "terminated":
        blocked.append(_blocked("run_terminated", "run was terminated"))
        return "blocked"
    if acceptance_gate is not None:
        if acceptance_gate.get("status") == "pending":
            return "verifying"
        if acceptance_gate.get("status") == "rejected":
            blocked.append(_blocked("acceptance_rejected", "acceptance was rejected"))
            return "blocked"
    if plan_gate is not None:
        if plan_gate.get("status") == "pending":
            return "plan_pending"
        if plan_gate.get("status") == "rejected":
            blocked.append(_blocked("plan_rejected", "PLAN gate was rejected"))
            return "blocked"
    plan = getattr(run, "artifacts", {}).get("plan")
    if not isinstance(plan, dict) or not plan:
        # No plan yet: still designing/planning.
        if _last_gate(run, "SPEC基线确认") is not None:
            return "spec_pending"
        return "planning"
    if any(state in _ACTIVE_TASK_STATES for state in states):
        return "executing"
    if any(state in _DEAD_TASK_STATES for state in states):
        return "executing"
    if states and all(state in _FINISHED_TASK_STATES for state in states):
        return "verifying"
    if tasks:
        # Tasks exist but have not started.  A granted run still needs an active
        # grant; a simulated legacy run may proceed without one.
        if plan_approved:
            return "authorization_pending"
        return "plan_approved"
    if plan_approved:
        return "plan_approved"
    return "plan_pending"


def _cross_project(discussion: Any, run: Any) -> str | None:
    if discussion is None or run is None:
        return None
    discussion_project = str(getattr(discussion, "project_id", "") or "")
    run_project = str(getattr(run, "project_id", "") or "")
    if discussion_project and run_project and discussion_project != run_project:
        return f"session project {discussion_project} != run project {run_project}"
    linked = (getattr(run, "artifacts", None) or {}).get("discussion_session_id")
    if linked and str(linked) != str(getattr(discussion, "session_id", "")):
        return f"run is linked to session {linked}, not {getattr(discussion, 'session_id', '')}"
    return None


def project_workflow_projection(
    *,
    discussion: Any | None = None,
    run: Any | None = None,
    grants: Iterable[Any] | None = None,
    model_mode: str = "not_run",
    execution_mode: str = "not_run",
    evidence: dict[str, Any] | None = None,
) -> WorkflowProjection:
    blocked: list[dict[str, str]] = []
    project_id = str(
        getattr(run, "project_id", "") or getattr(discussion, "project_id", "") or ""
    )
    session_id = (
        str(getattr(discussion, "session_id", "") or "")
        or (getattr(run, "artifacts", None) or {}).get("discussion_session_id")
        or None
    )
    run_id = str(getattr(run, "id", "") or "") or None
    status = str(
        getattr(run, "status", "") or getattr(discussion, "status", "") or ""
    )
    hashes = _hashes(run) if run is not None else {}

    mismatch = _cross_project(discussion, run)
    if mismatch:
        blocked.append(_blocked("cross_project_mismatch", mismatch))
        return WorkflowProjection(
            stage="blocked",
            status=status,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            baseline_hashes=hashes,
            blocked=blocked,
            model_mode=model_mode,
            execution_mode=execution_mode,
            evidence=evidence or {},
        )

    needs_reconciliation = bool(
        run is not None
        and (
            (getattr(run, "artifacts", None) or {}).get("workflow_needs_reconciliation")
            or any(bool((task or {}).get("needs_reconciliation")) for task in (getattr(run, "tasks", None) or {}).values())
        )
    )
    invalidation = (
        (getattr(run, "artifacts", None) or {}).get("workflow_invalidations") if run is not None else None
    )

    plan_gate = _last_gate(run, PLAN_GATE_KIND) if run is not None else None
    spec_approved = _spec_approved(discussion, run, plan_gate)
    plan_approved = "PLAN" in hashes or bool(plan_gate and plan_gate.get("status") == "approved")

    if discussion is not None and run is None:
        stage = discussion_stage(getattr(discussion, "status", ""))
        code = DISCUSSION_BLOCKED.get(str(getattr(discussion, "status", "")))
        if code:
            blocked.append(_blocked(code, f"discussion session is {getattr(discussion, 'status', '')}"))
    elif run is not None:
        stage = _run_stage(run, blocked=blocked)
        if discussion is not None and stage in {"discussing", "spec_pending"} and not plan_gate:
            stage = discussion_stage(getattr(discussion, "status", ""))
    else:
        stage = "discussing"

    if needs_reconciliation and stage not in {"accepted", "blocked"}:
        stage = "needs_reconciliation"
        blocked.append(
            _blocked("needs_reconciliation", "restored run has execution without complete evidence")
        )
    if invalidation and stage not in {"accepted", "blocked"}:
        stage = "invalidated"
        blocked.append(_blocked("baseline_stale", "approved baseline changed; re-approval required"))

    return WorkflowProjection(
        stage=stage,
        status=status,
        project_id=project_id,
        session_id=session_id,
        run_id=run_id,
        spec_approved=spec_approved,
        plan_approved=plan_approved,
        blocked=blocked,
        baseline_hashes=hashes,
        model_mode=model_mode,
        execution_mode=execution_mode,
        evidence=evidence or {},
    )


def find_run_for_session(runs: Iterable[Any] | dict[str, Any], session_id: str) -> Any | None:
    candidates = runs.values() if isinstance(runs, dict) else runs
    for run in candidates:
        if str((getattr(run, "artifacts", None) or {}).get("discussion_session_id") or "") == str(session_id):
            return run
    return None


__all__ = ["WorkflowProjection", "find_run_for_session", "project_workflow_projection"]