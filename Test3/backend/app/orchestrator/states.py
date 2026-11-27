from __future__ import annotations

from app.errors import IllegalTransition

TASK_STATES = (
    "pending",
    "ready",
    "running",
    "verifying",
    "done",
    "failed",
    "needs_human",
    "blocked",
    "skipped",
    "cancelled",
    "stale",
)

# Architecture.md 9.1
TASK_TRANSITIONS: dict[tuple[str, str], str] = {
    ("pending", "deps_met"): "ready",
    ("ready", "scheduled"): "running",
    ("running", "code_finished"): "verifying",
    ("verifying", "defect_repair"): "running",
    ("verifying", "accepted"): "done",
    ("verifying", "env_or_conflict"): "failed",
    ("running", "env_fail"): "failed",
    ("failed", "retry"): "running",
    ("failed", "over_limit"): "needs_human",
    ("running", "budget_or_stuck"): "needs_human",
    ("verifying", "repair_exceeded"): "needs_human",
    ("pending", "upstream_bad"): "blocked",
    ("blocked", "upstream_ok"): "pending",
    ("needs_human", "human_retry"): "running",
    ("needs_human", "human_skip"): "skipped",
    ("pending", "human_skip"): "skipped",
    ("ready", "human_skip"): "skipped",
    ("running", "human_skip"): "skipped",
    ("verifying", "human_skip"): "skipped",
    ("failed", "human_skip"): "skipped",
    ("blocked", "human_skip"): "skipped",
    ("needs_human", "force_pass"): "done",
    ("failed", "force_pass"): "done",
    # P5: a rejected module acceptance / defect returns the task to a repairable
    # state.  ``failed`` is already retryable ("failed" + "retry" -> "running");
    # force-pass is not opened by this edge.
    ("done", "defect_found"): "failed",
    ("verifying", "defect_found"): "failed",
    ("failed", "defect_found"): "failed",
    ("pending", "cancel"): "cancelled",
    ("ready", "cancel"): "cancelled",
    ("running", "cancel"): "cancelled",
    ("verifying", "cancel"): "cancelled",
    ("failed", "cancel"): "cancelled",
    ("blocked", "cancel"): "cancelled",
    ("needs_human", "cancel"): "cancelled",
    ("stale", "cancel"): "cancelled",
    ("done", "change_impact"): "stale",
    ("stale", "change_approved"): "ready",
    ("verifying", "merge_conflict"): "blocked",
    ("running", "merge_conflict"): "blocked",
    ("blocked", "conflict_resolved"): "ready",
    ("blocked", "conflict_failed"): "needs_human",
    ("running", "task_issue"): "needs_human",
    ("verifying", "task_issue"): "needs_human",
    ("ready", "task_issue"): "needs_human",
    ("running", "repair_exceeded"): "needs_human",
    ("ready", "human_pause"): "pending",
    # Card 3: explicit human reconciliation after a crash. Never automatic.
    ("running", "reconcile_accepted"): "done",
    ("verifying", "reconcile_accepted"): "done",
    ("ready", "reconcile_accepted"): "done",
    ("running", "reconcile_failed"): "failed",
    ("verifying", "reconcile_failed"): "failed",
    ("ready", "reconcile_failed"): "failed",
    ("running", "interrupted"): "ready",
    ("verifying", "interrupted"): "ready",
}

TASK_EVENTS = tuple(sorted({event for _, event in TASK_TRANSITIONS}))


def can_transition(state: str, event: str) -> bool:
    return (state, event) in TASK_TRANSITIONS


def next_task_state(state: str, event: str) -> str:
    key = (state, event)
    if key not in TASK_TRANSITIONS:
        raise IllegalTransition(f"illegal task transition: {state} + {event}")
    return TASK_TRANSITIONS[key]
