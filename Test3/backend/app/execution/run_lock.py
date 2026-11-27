"""Per-run write lock shared by the scheduler and task execution (P5).

A run's write paths (schedule loop, ``execute_task``, acceptance/defect writes)
must serialize against each other.  ``asyncio.gather`` inside the schedule loop
creates child tasks, so a plain non-reentrant ``asyncio.Lock`` acquired by both
layers would deadlock.  ``write_scope`` therefore marks the run as held in a
context variable: nested work started from the same logical operation re-enters
instead of blocking, while any other writer waits on the same underlying lock.

This is deliberately one lock per run — not a second parallel lock — so
``schedule`` and ``execute`` cannot deadlock against each other.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

_HELD: ContextVar[frozenset[str]] = ContextVar("test3_run_write_scopes", default=frozenset())


class RunLockBusy(RuntimeError):
    """Bounded acquisition failed: another logical operation holds the run.

    Callers that must answer quickly (e.g. the task-memory HTTP write while the
    scheduler is executing tasks with model calls under the same lock) pass
    ``busy_timeout`` and translate this into a retryable conflict instead of
    blocking for the whole batch.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run is busy: {run_id}")
        self.run_id = run_id


class RunLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, int] = {}

    def lock_for(self, run_id: str) -> asyncio.Lock:
        lock = self._locks.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[run_id] = lock
        return lock

    def holders(self, run_id: str) -> int:
        return int(self._holders.get(run_id, 0))

    @asynccontextmanager
    async def write_scope(
        self,
        run_id: str,
        *,
        busy_timeout: float | None = None,
    ) -> AsyncIterator[RunLockRegistry]:
        """Serialize writers for one run.

        ``busy_timeout`` is opt-in: when the lock is held by another logical
        operation, wait at most that many seconds and then raise
        ``RunLockBusy`` instead of blocking indefinitely.  Re-entrant use from
        the same logical operation never waits and ignores the timeout.
        """
        held = _HELD.get()
        if run_id in held:
            yield self
            return
        lock = self.lock_for(run_id)
        if busy_timeout is None:
            await lock.acquire()
        else:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=busy_timeout)
            except asyncio.TimeoutError as exc:
                raise RunLockBusy(run_id) from exc
        self._holders[run_id] = self.holders(run_id) + 1
        token = _HELD.set(held | {run_id})
        try:
            yield self
        finally:
            _HELD.reset(token)
            self._holders[run_id] = max(0, self.holders(run_id) - 1)
            lock.release()


__all__ = ["RunLockBusy", "RunLockRegistry"]