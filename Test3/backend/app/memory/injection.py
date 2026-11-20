"""Build the memory slot injected into ``call_agent`` prompts.

The slot is fail-closed: only the actor's own private/run memories, plus
published memories of projects the actor belongs to, are eligible.  Any item
that still looks like it contains a secret is dropped before serialization.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.access import is_project_member
from app.memory.store import MemoryStore, SecretInBody, assert_no_secrets
from app.schemas.memory import MemoryRecord
from app.settings import get_settings
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database


@asynccontextmanager
async def _session_scope(session: AsyncSession | None, db_path: Path | None):
    if session is not None:
        yield session
        return
    path = Path(db_path) if db_path is not None else get_settings().data_dir() / "test3.db"
    upgrade_database(path)
    engine = make_engine(sqlite_url(path))
    factory = session_factory(engine)
    try:
        async with factory() as owned:
            yield owned
    finally:
        await engine.dispose()


def _item(record: MemoryRecord) -> dict:
    return {
        "mem_id": record.mem_id,
        "version": record.version,
        "visibility": record.visibility,
        "title": record.title,
        "body": record.body,
    }


def _safe_item(record: MemoryRecord) -> dict | None:
    try:
        assert_no_secrets({"title": record.title, "body": record.body})
    except SecretInBody:
        return None
    item = _item(record)
    if "sk-" in json.dumps(item, ensure_ascii=False):
        return None
    return item


async def build_memory_slot(
    actor_bot_id: str,
    *,
    project_id: str | None,
    run_id: str | None,
    session: AsyncSession | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    async with _session_scope(session, db_path) as active:
        store = MemoryStore(active)
        candidates: list[MemoryRecord] = []
        candidates.extend(
            await store.list(owner_bot_id=actor_bot_id, visibility="private")
        )
        if project_id and await is_project_member(active, project_id, actor_bot_id):
            project_records = await store.list(
                project_id=project_id, visibility="project"
            )
            candidates.extend(
                record for record in project_records if record.status == "published"
            )
        if run_id:
            run_records = await store.list(owner_bot_id=actor_bot_id, visibility="run")
            candidates.extend(
                record for record in run_records if record.run_id == run_id
            )
        deduped: dict[str, dict] = {}
        for record in candidates:
            item = _safe_item(record)
            if item is not None and record.mem_id not in deduped:
                deduped[record.mem_id] = item
        return [deduped[mem_id] for mem_id in sorted(deduped, key=lambda mid: (deduped[mid]["visibility"], mid))]


__all__ = ["build_memory_slot"]