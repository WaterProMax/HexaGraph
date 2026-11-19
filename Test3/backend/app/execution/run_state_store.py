"""SQLite authority for run execution state (P1-REV-04 / F-02).

GRANTED runs must never be downgraded to legacy just because a JSON snapshot is
missing or corrupt.  The profile and approved baseline hashes are persisted in
``run_execution_state``; snapshots remain a compatibility copy only.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import RunExecutionStateRow

PROFILE_LEGACY = "legacy"
PROFILE_GRANTED = "granted_v1"
PROFILE_UNSPECIFIED = "unspecified"
PROFILE_CONFLICT = "conflict"

_VALID_PROFILES = {PROFILE_LEGACY, PROFILE_GRANTED}


@dataclass(frozen=True)
class RunExecutionState:
    run_id: str
    execution_profile: str
    approved_baseline_hashes: dict[str, str]
    approved_plan_hash: str = ""
    allowed_tool_refs: tuple[str, ...] = ()

    def as_row(self) -> RunExecutionStateRow:
        return RunExecutionStateRow(
            run_id=self.run_id,
            execution_profile=self.execution_profile,
            approved_baseline_hashes=json.dumps(self.approved_baseline_hashes, ensure_ascii=False),
            approved_plan_hash=self.approved_plan_hash,
            allowed_tool_refs=json.dumps(list(self.allowed_tool_refs), ensure_ascii=False),
        )


def _decode_hashes(raw: Any) -> dict[str, str]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("approved_baseline_hashes is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("approved_baseline_hashes must be an object")
    return {str(key): str(item) for key, item in value.items()}


def read_run_execution_state(db_path: Path, run_id: str) -> RunExecutionState | None:
    """Read the authoritative row without creating or migrating the database.

    The restore path runs in ``__init__`` (sync), so it uses a short read-only
    sqlite3 connection instead of the async engine.  A malformed row is reported
    as an explicit conflict so callers fail closed rather than guessing legacy.
    """
    if not db_path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return RunExecutionState(run_id, PROFILE_CONFLICT, {})
    try:
        row = connection.execute(
            "select execution_profile, approved_baseline_hashes, approved_plan_hash, allowed_tool_refs "
            "from run_execution_state where run_id = ?",
            (run_id,),
        ).fetchone()
    except sqlite3.Error:
        # Table absent (pre-F-02 database) means no authoritative state yet.
        return None
    finally:
        connection.close()
    if row is None:
        return None
    profile = str(row[0] or "")
    if profile not in _VALID_PROFILES:
        return RunExecutionState(run_id, PROFILE_CONFLICT, {})
    try:
        hashes = _decode_hashes(row[1])
        allowed_raw = json.loads(row[3] or "[]")
        allowed = tuple(str(item) for item in allowed_raw) if isinstance(allowed_raw, list) else ()
    except (ValueError, json.JSONDecodeError):
        return RunExecutionState(run_id, PROFILE_CONFLICT, {})
    return RunExecutionState(
        run_id=run_id,
        execution_profile=profile,
        approved_baseline_hashes=hashes,
        approved_plan_hash=str(row[2] or ""),
        allowed_tool_refs=allowed,
    )


class RunExecutionStateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, run_id: str) -> RunExecutionState | None:
        row = await self.session.get(RunExecutionStateRow, run_id)
        if row is None:
            return None
        try:
            hashes = _decode_hashes(row.approved_baseline_hashes)
            allowed_raw = json.loads(row.allowed_tool_refs or "[]")
        except (ValueError, json.JSONDecodeError):
            return RunExecutionState(run_id, PROFILE_CONFLICT, {})
        profile = row.execution_profile if row.execution_profile in _VALID_PROFILES else PROFILE_CONFLICT
        return RunExecutionState(
            run_id=run_id,
            execution_profile=profile,
            approved_baseline_hashes=hashes,
            approved_plan_hash=row.approved_plan_hash or "",
            allowed_tool_refs=tuple(str(item) for item in allowed_raw) if isinstance(allowed_raw, list) else (),
        )

    async def upsert(self, state: RunExecutionState) -> None:
        if state.execution_profile not in _VALID_PROFILES:
            raise ValueError(f"unknown execution profile: {state.execution_profile}")
        row = await self.session.get(RunExecutionStateRow, state.run_id)
        if row is None:
            self.session.add(state.as_row())
        else:
            row.execution_profile = state.execution_profile
            row.approved_baseline_hashes = json.dumps(state.approved_baseline_hashes, ensure_ascii=False)
            row.approved_plan_hash = state.approved_plan_hash
            row.allowed_tool_refs = json.dumps(list(state.allowed_tool_refs), ensure_ascii=False)
        await self.session.flush()


__all__ = [
    "PROFILE_CONFLICT",
    "PROFILE_GRANTED",
    "PROFILE_LEGACY",
    "PROFILE_UNSPECIFIED",
    "RunExecutionState",
    "RunExecutionStateRepo",
    "read_run_execution_state",
]
