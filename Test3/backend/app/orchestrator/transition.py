from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IllegalTransition
from app.events.bus import EventBus
from app.orchestrator.states import next_task_state
from app.storage.models import TaskRow


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
    try:
        nxt = next_task_state(task.state, event)
    except IllegalTransition:
        await bus.emit(
            session,
            task.run_id,
            "orchestrator.illegal_transition",
            task.code,
            {"from": task.state, "event": event, "reason": reason},
            actor,
        )
        raise
    prev = task.state
    task.state = nxt
    task.revision += 1
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
