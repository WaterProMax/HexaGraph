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
    ("needs_human", "force_pass"): "done",
    ("pending", "cancel"): "cancelled",
    ("ready", "cancel"): "cancelled",
    ("running", "cancel"): "cancelled",
    ("verifying", "cancel"): "cancelled",
    ("failed", "cancel"): "cancelled",
    ("blocked", "cancel"): "cancelled",
    ("needs_human", "cancel"): "cancelled",
    ("done", "change_impact"): "stale",
    ("stale", "change_approved"): "ready",
    ("ready", "human_pause"): "pending",
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
