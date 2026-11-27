"""Server-side phase admission.

Every mutating workflow entry calls :func:`assert_phase_admission` before it
acts.  The checks reuse existing statuses/errors; legacy fixture runs that never
had a PLAN gate stay compatible, while the discussion mainline cannot skip the
human-approved spec / PLAN.
"""

from __future__ import annotations

from typing import Any

from app.errors import Test3Error
from app.workflow.stages import DESIGN_GATE_KIND, PLAN_GATE_KIND


class WorkflowRejected(Test3Error):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        status_code: int = 409,
        blocked_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.blocked_reason = blocked_reason or category


def _last_gate(run: Any, kind: str) -> dict[str, Any] | None:
    for gate in reversed(list(getattr(run, "gates", None) or [])):
        if gate.get("kind") == kind:
            return gate
    return None


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


def assert_phase_admission(
    action: str,
    *,
    discussion: Any | None = None,
    run: Any | None = None,
) -> None:
    mismatch = _cross_project(discussion, run)
    if mismatch:
        raise WorkflowRejected(
            mismatch,
            category="cross_project_mismatch",
            blocked_reason="cross_project_mismatch",
        )

    if action in {"design", "plan"}:
        if discussion is None:
            raise WorkflowRejected(
                "discussion session is required",
                category="invalid_status",
                blocked_reason="spec_not_approved",
            )
        if getattr(discussion, "status", "") != "approved" or getattr(
            discussion, "decision_package", None
        ) is None:
            raise WorkflowRejected(
                "需先确认需求规格",
                category="invalid_status",
                blocked_reason="spec_not_approved",
            )
        if action == "design":
            return
        # plan：DESIGN 基线必须先经人工确认（第 5 步），才能进入任务拆解（第 6 步）。
        if run is None:
            raise WorkflowRejected(
                "需先完成设计规格整理与确认",
                category="design_not_approved",
                blocked_reason="design_not_approved",
            )
        if (getattr(run, "artifacts", None) or {}).get("plan"):
            # 已有计划的运行重复调用 /plan 是幂等读取，不再重复校验关卡。
            return
        design_gate = _last_gate(run, DESIGN_GATE_KIND)
        hashes = getattr(run, "approved_baseline_hashes", None) or {}
        if "DESIGN" in hashes or (design_gate and design_gate.get("status") == "approved"):
            return
        raise WorkflowRejected(
            "需先确认设计规格基线",
            category="design_not_approved",
            blocked_reason="design_not_approved",
        )

    if action in {"confirm_plan", "schedule", "execute", "accept"} and run is None:
        raise WorkflowRejected(
            "run is required",
            category="run_not_found",
            status_code=404,
            blocked_reason="run_missing",
        )

    if action == "confirm_plan":
        gate = _last_gate(run, PLAN_GATE_KIND)
        if gate is None:
            raise WorkflowRejected(
                "PLAN gate does not exist",
                category="invalid_status",
                blocked_reason="plan_gate_missing",
            )
        if gate.get("status") != "pending":
            raise WorkflowRejected(
                "关卡已裁决，不能重复推进",
                category="invalid_status",
                blocked_reason="plan_gate_closed",
            )
        return

    if action in {"schedule", "execute", "accept"}:
        gate = _last_gate(run, PLAN_GATE_KIND)
        if gate is not None and gate.get("status") == "pending":
            raise WorkflowRejected(
                "PLAN 基线尚未确认，不能执行任务",
                category="invalid_status",
                blocked_reason="plan_not_approved",
            )
        if gate is not None and gate.get("status") == "rejected":
            raise WorkflowRejected(
                "PLAN 基线已被驳回，不能执行任务",
                category="invalid_status",
                blocked_reason="plan_rejected",
            )
        return

    raise ValueError(f"unknown workflow action: {action}")


__all__ = ["WorkflowRejected", "assert_phase_admission"]