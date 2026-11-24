"""Internal workflow stages for the discussion → plan → execute → accept line.

These are **internal** names.  Public ``discussion.status`` / ``run.status`` keep
their existing values; :mod:`app.workflow.projection` maps one onto the other so
old clients keep working.
"""

from __future__ import annotations

from typing import Literal

WorkflowStage = Literal[
    "discussing",
    "spec_pending",
    "spec_approved",
    "planning",
    "plan_pending",
    "plan_approved",
    "authorization_pending",
    "executing",
    "verifying",
    "accepted",
    "blocked",
    "invalidated",
    "needs_reconciliation",
]

STAGE_ORDER: tuple[str, ...] = (
    "discussing",
    "spec_pending",
    "spec_approved",
    "planning",
    "plan_pending",
    "plan_approved",
    "authorization_pending",
    "executing",
    "verifying",
    "accepted",
)

DISCUSSION_STAGE: dict[str, str] = {
    "draft": "discussing",
    "grouping": "discussing",
    "round1_independent": "discussing",
    "cross_review": "discussing",
    "round_n_revise": "discussing",
    "converged_pending_human": "spec_pending",
    "approved": "spec_approved",
    "rejected": "blocked",
    "terminated": "blocked",
    "budget_exhausted": "blocked",
}

DISCUSSION_BLOCKED: dict[str, str] = {
    "rejected": "discussion_rejected",
    "terminated": "discussion_terminated",
    "budget_exhausted": "discussion_budget_exhausted",
}

PLAN_GATE_KIND = "PLAN基线确认"
ACCEPTANCE_GATE_KIND = "验收确认"


def discussion_stage(status: str) -> str:
    return DISCUSSION_STAGE.get(str(status or ""), "discussing")


__all__ = [
    "ACCEPTANCE_GATE_KIND",
    "DISCUSSION_BLOCKED",
    "DISCUSSION_STAGE",
    "PLAN_GATE_KIND",
    "STAGE_ORDER",
    "WorkflowStage",
    "discussion_stage",
]