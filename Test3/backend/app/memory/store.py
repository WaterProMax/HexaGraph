"""SQLite authority for versioned memory records.

A record is identified by ``(mem_id, version)``.  Versions append; the old
body is immutable and enforced by a SQLite trigger in migration 0008.  The
``memory_records.status`` column mirrors ``payload.status``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.memory import MemoryCreate, MemoryRecord, MemorySource
from app.storage.models import MemoryRecordRow

_SECRET_FIELD_NAMES = {"api_key", "password", "secret", "token", "access_token"}


class SecretInBody(Exception):
    pass


class MemoryVersionConflict(Exception):
    pass


class MemoryNotFound(Exception):
    pass


def _is_secret_field(name: str) -> bool:
    lowered = name.lower()
    if lowered == "token_budget":
        return False
    return lowered in _SECRET_FIELD_NAMES or lowered.endswith("_api_key")


def assert_no_secrets(value: Any) -> None:
    """Reject secret-like field names and ``sk-`` values anywhere in ``value``."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and _is_secret_field(key):
                raise SecretInBody(f"secret-like field: {key}")
            assert_no_secrets(child)
    elif isinstance(value, list):
        for item in value:
            assert_no_secrets(item)
    elif isinstance(value, str) and value.startswith("sk-"):
        raise SecretInBody("secret-like value")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sources(values: list[MemorySource] | list[dict[str, Any]]) -> list[MemorySource]:
    return [MemorySource.model_validate(item) for item in values]


def _is_locked(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


class MemoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: MemoryCreate) -> MemoryRecord:
        assert_no_secrets(data.body)
        record = MemoryRecord(
            mem_id=str(uuid.uuid4()),
            owner_bot_id=data.owner_bot_id,
            project_id=data.project_id,
            visibility=data.visibility,
            version=1,
            status="pending",
            sources=_sources(data.sources),
            body=dict(data.body),
            title=data.title,
            run_id=data.run_id,
        )
        self.session.add(_row(record))
        await self.session.flush()
        return record

    async def get(self, mem_id: str, version: int | None = None) -> MemoryRecord:
        if version is None:
            stmt = (
                select(MemoryRecordRow)
                .where(MemoryRecordRow.mem_id == mem_id)
                .order_by(MemoryRecordRow.version.desc())
                .limit(1)
            )
            row = (await self.session.execute(stmt)).scalars().first()
        else:
            row = await self.session.get(MemoryRecordRow, (mem_id, version))
        if row is None:
            raise MemoryNotFound(f"{mem_id}@{version if version is not None else 'latest'}")
        return MemoryRecord.model_validate(row.payload)

    async def list(
        self,
        *,
        owner_bot_id: str | None = None,
        project_id: str | None = None,
        visibility: str | None = None,
        latest_only: bool = True,
    ) -> list[MemoryRecord]:
        stmt = select(MemoryRecordRow)
        if owner_bot_id is not None:
            stmt = stmt.where(MemoryRecordRow.owner_bot_id == owner_bot_id)
        if project_id is not None:
            stmt = stmt.where(MemoryRecordRow.project_id == project_id)
        if visibility is not None:
            stmt = stmt.where(MemoryRecordRow.visibility == visibility)
        stmt = stmt.order_by(MemoryRecordRow.mem_id, MemoryRecordRow.version)
        rows = list((await self.session.execute(stmt)).scalars())
        if latest_only:
            latest: dict[str, MemoryRecordRow] = {}
            for row in rows:
                latest[row.mem_id] = row
            rows = [latest[mem_id] for mem_id in sorted(latest)]
        return [MemoryRecord.model_validate(row.payload) for row in rows]

    async def append_version(
        self, mem_id: str, expected_version: int, **fields: Any
    ) -> MemoryRecord:
        return await self._retry(
            lambda: self._append_once(mem_id, expected_version, fields)
        )

    async def _append_once(
        self, mem_id: str, expected_version: int, fields: dict[str, Any]
    ) -> MemoryRecord:
        latest = await self._locked_latest(mem_id)
        if latest.version != expected_version:
            raise MemoryVersionConflict(
                f"expected version {expected_version}, latest is {latest.version}"
            )
        body = dict(fields.get("body", latest.body))
        assert_no_secrets(body)
        sources = _sources(fields.get("sources", latest.sources))
        record = MemoryRecord(
            mem_id=mem_id,
            owner_bot_id=latest.owner_bot_id,
            project_id=latest.project_id,
            visibility=latest.visibility,
            version=latest.version + 1,
            status="pending",
            sources=sources,
            body=body,
            title=fields.get("title", latest.title),
            run_id=latest.run_id,
        )
        self.session.add(_row(record))
        await self.session.flush()
        return record

    async def _locked_latest(self, mem_id: str) -> MemoryRecord:
        result = await self.session.execute(
            text("UPDATE memory_records SET status = status WHERE mem_id = :mem_id"),
            {"mem_id": mem_id},
        )
        if result.rowcount == 0:
            raise MemoryNotFound(mem_id)
        stmt = (
            select(MemoryRecordRow)
            .where(MemoryRecordRow.mem_id == mem_id)
            .order_by(MemoryRecordRow.version.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            raise MemoryNotFound(mem_id)
        return MemoryRecord.model_validate(row.payload)

    async def _retry(self, operation):
        for attempt in range(4):
            try:
                return await operation()
            except OperationalError as exc:
                await self.session.rollback()
                if not _is_locked(exc) or attempt == 3:
                    raise
                await asyncio.sleep(0.02 * (attempt + 1))


def _row(record: MemoryRecord) -> MemoryRecordRow:
    return MemoryRecordRow(
        mem_id=record.mem_id,
        version=record.version,
        owner_bot_id=record.owner_bot_id,
        project_id=record.project_id,
        visibility=record.visibility,
        status=record.status,
        payload=record.model_dump(),
    )


__all__ = [
    "MemoryNotFound",
    "MemoryStore",
    "MemoryVersionConflict",
    "SecretInBody",
    "assert_no_secrets",
    "now_iso",
]