from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IllegalTransition
from app.events.bus import EventBus
from app.orchestrator.states import next_task_state
from app.storage.models import TaskRow


def apply_transition(task: Any, event: str, *, reason: str = "", extra: dict[str, Any] | None = None) -> str:
    """Sole writer of task.state. Memory dicts and TaskRow both go through here."""
    del reason, extra
    if isinstance(task, dict):
        nxt = next_task_state(task["state"], event)
        task["state"] = nxt
        task["revision"] = int(task.get("revision") or 1) + 1
        return nxt
    nxt = next_task_state(task.state, event)
    task.state = nxt
    task.revision += 1
    return nxt


def restore_task_state(task: dict[str, Any], state: str) -> None:
    """Replay-only assignment used when rebuilding from the event log."""
    task["state"] = state


async def transition(
    session: AsyncSession,
    task: TaskRow,
    event: str,
    *,
    reason: str,
    actor: str,
    bus: EventBus,
    extra: dict[str, Any] | None = None,
) -> TaskRow:
    prev = task.state
    try:
        nxt = apply_transition(task, event, reason=reason, extra=extra)
    except IllegalTransition:
        await bus.emit(
            session,
            task.run_id,
            "orchestrator.illegal_transition",
            task.code,
            {"from": prev, "event": event, "reason": reason},
            actor,
        )
        raise
    await bus.emit(
        session,
        task.run_id,
        "task.state_changed",
        task.code,
        {"code": task.code, "from": prev, "to": nxt, "event": event, "reason": reason, **(extra or {})},
        actor,
    )
    await session.flush()
    return task
