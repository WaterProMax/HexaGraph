from __future__ import annotations

from app.errors import IllegalTransition, ValidationFailed

# Design.md 16.3 availability
CONTROL_TABLE = {
    "pause": {"pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"},
    "resume": {"pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"},
    "retry": {"needs_human", "failed"},
    "skip": {"pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"},
    "takeover": {"pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"},
    "force-pass": {"needs_human", "failed"},
    "patch": {"pending", "ready", "needs_human"},
}

TERMINAL = {"done", "skipped", "cancelled"}


def control_allowed(action: str, state: str) -> bool:
    if action == "submit-takeover":
        return state not in TERMINAL
    return state in CONTROL_TABLE.get(action, set())


def require_control(action: str, state: str, *, reason: str | None = None) -> None:
    if not control_allowed(action, state):
        raise IllegalTransition(f"{action} not allowed in {state}")
    if action in {"force-pass", "skip"} and not (reason or "").strip():
        raise ValidationFailed("强制通过/跳过必须写理由")
