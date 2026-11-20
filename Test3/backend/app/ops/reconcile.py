"""Process-local reconciliation between SQLite and the in-memory runtime (P7).

SQLite is the single write authority for the new domains; the legacy run
snapshots/JSONL keep serving legacy runs.  ``reconcile`` therefore only fixes
*bookkeeping drift* that a crash can leave behind:

* it counts active execution grants so a restart can prove the authority is
  intact;
* it realigns a memory record's indexed ``status`` column with the status inside
  its payload (the payload/body is never rewritten);
* it never deletes rows, never downgrades a ``published`` memory to ``pending``
  and never touches the user's JSONL files.

Running it twice is a no-op: the second pass reports zero fixes and the same
active-grant count.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import ExecutionGrantRow, MemoryRecordRow


@dataclass
class ReconcileReport:
    grants_active: int = 0
    memory_orphans_fixed: int = 0
    notes: list[str] = field(default_factory=list)


def _is_locked(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


async def _retry_locked(operation, attempts: int = 5):
    delay = 0.02
    for attempt in range(attempts):
        try:
            return await operation()
        except OperationalError as exc:
            if not _is_locked(exc) or attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2


def _payload_status(payload: object) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("status")
        return str(value) if isinstance(value, str) and value else None
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, dict):
            value = decoded.get("status")
            return str(value) if isinstance(value, str) and value else None
    return None


def _payload_run_id(payload: object) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("run_id")
        return str(value) if value else None
    return None


async def reconcile(db_session: AsyncSession, *, run_id: str | None = None) -> ReconcileReport:
    """Return what was checked and which drift was fixed (never deletes)."""
    report = ReconcileReport()

    async def _count_grants() -> int:
        stmt = select(ExecutionGrantRow).where(ExecutionGrantRow.status == "active")
        if run_id is not None:
            stmt = stmt.where(ExecutionGrantRow.run_id == run_id)
        rows = (await db_session.execute(stmt)).scalars().all()
        return len(rows)

    report.grants_active = await _retry_locked(_count_grants)

    async def _fix_memory() -> int:
        rows = (await db_session.execute(select(MemoryRecordRow))).scalars().all()
        fixed = 0
        for row in rows:
            payload = row.payload
            if run_id is not None and _payload_run_id(payload) not in (None, run_id):
                continue
            expected = _payload_status(payload)
            if expected is None:
                report.notes.append(f"memory_payload_status_missing:{row.mem_id}:{row.version}")
                continue
            if row.status == expected:
                continue
            # Only the indexed column is aligned; payload/body stay untouched.
            result = await db_session.execute(
                update(MemoryRecordRow)
                .where(
                    MemoryRecordRow.mem_id == row.mem_id,
                    MemoryRecordRow.version == row.version,
                    MemoryRecordRow.status != expected,
                )
                .values(status=expected)
            )
            fixed += int(result.rowcount or 0)
        return fixed

    report.memory_orphans_fixed = await _retry_locked(_fix_memory)
    if report.memory_orphans_fixed:
        await _retry_locked(db_session.commit)
        report.notes.append(f"memory_status_realigned:{report.memory_orphans_fixed}")
    return report


__all__ = ["ReconcileReport", "reconcile"]
