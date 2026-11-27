from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.memory.store import (
    MemoryNotFound,
    MemoryStore,
    MemoryVersionConflict,
    SecretInBody,
)
from app.schemas.memory import MemoryCreate, MemorySource
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import MemoryRecordRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "memory.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


def _memory(**overrides) -> MemoryCreate:
    data = {
        "owner_bot_id": "bot-1",
        "project_id": None,
        "visibility": "private",
        "sources": [MemorySource(kind="doc", ref="notes.md", sha="abc123")],
        "body": {"text": "old"},
        "title": "note",
        "run_id": None,
    }
    data.update(overrides)
    return MemoryCreate(**data)


@pytest.mark.asyncio
async def test_create_private_memory_starts_at_version_one_pending(factory) -> None:
    async with factory() as session:
        record = await MemoryStore(session).create(_memory())
        await session.commit()
    assert record.mem_id
    assert record.version == 1
    assert record.status == "pending"
    assert record.visibility == "private"
    assert record.owner_bot_id == "bot-1"
    assert record.project_id is None and record.run_id is None


@pytest.mark.asyncio
async def test_append_version_keeps_old_body_and_get_returns_latest(factory) -> None:
    async with factory() as session:
        store = MemoryStore(session)
        created = await store.create(_memory())
        await session.commit()
    async with factory() as session:
        store = MemoryStore(session)
        second = await store.append_version(
            created.mem_id,
            1,
            body={"text": "new"},
            sources=[MemorySource(kind="doc", ref="notes.md", sha="def456")],
            title="note v2",
        )
        await session.commit()
    assert second.version == 2
    assert second.status == "pending"
    async with factory() as session:
        store = MemoryStore(session)
        latest = await store.get(created.mem_id)
        first = await store.get(created.mem_id, 1)
        all_versions = await store.list(
            owner_bot_id="bot-1", visibility="private", latest_only=False
        )
        latest_only = await store.list(owner_bot_id="bot-1", visibility="private")
    assert latest.version == 2 and latest.body == {"text": "new"}
    assert first.version == 1 and first.body == {"text": "old"}
    assert [item.version for item in all_versions] == [1, 2]
    assert [item.version for item in latest_only] == [2]


@pytest.mark.asyncio
async def test_expected_version_mismatch_is_conflict(factory) -> None:
    async with factory() as session:
        store = MemoryStore(session)
        created = await store.create(_memory())
        await store.append_version(created.mem_id, 1, body={"text": "v2"})
        await session.commit()
    async with factory() as session:
        with pytest.raises(MemoryVersionConflict):
            await MemoryStore(session).append_version(
                created.mem_id, 1, body={"text": "stale"}
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_missing_memory_raises(factory) -> None:
    async with factory() as session:
        with pytest.raises(MemoryNotFound):
            await MemoryStore(session).get("no-such")


@pytest.mark.asyncio
async def test_secret_in_body_is_rejected_without_a_row(factory) -> None:
    async with factory() as session:
        with pytest.raises(SecretInBody):
            await MemoryStore(session).create(_memory(body={"api_key": "sk-leak"}))
        await session.rollback()
    async with factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(MemoryRecordRow))
        ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_secret_scan_is_nested_case_insensitive_and_spares_token_budget(factory) -> None:
    async with factory() as session:
        with pytest.raises(SecretInBody):
            await MemoryStore(session).create(
                _memory(body={"nested": [{"Access_Token": "value"}]})
            )
        await session.rollback()
    async with factory() as session:
        with pytest.raises(SecretInBody):
            await MemoryStore(session).create(_memory(body={"items": ["sk-live"]}))
        await session.rollback()
    async with factory() as session:
        record = await MemoryStore(session).create(_memory(body={"token_budget": 1000}))
        await session.commit()
    assert record.body == {"token_budget": 1000}


@pytest.mark.asyncio
async def test_append_secret_is_rejected_and_keeps_version_line(factory) -> None:
    async with factory() as session:
        created = await MemoryStore(session).create(_memory())
        await session.commit()
    async with factory() as session:
        store = MemoryStore(session)
        with pytest.raises(SecretInBody):
            await store.append_version(created.mem_id, 1, body={"password": "pw"})
        await session.rollback()
    async with factory() as session:
        store = MemoryStore(session)
        assert (await store.get(created.mem_id)).version == 1


@pytest.mark.asyncio
async def test_direct_sql_cannot_change_old_body(factory) -> None:
    async with factory() as session:
        created = await MemoryStore(session).create(_memory(body={"text": "old"}))
        await session.commit()
    async with factory() as session:
        with pytest.raises(DBAPIError) as caught:
            await session.execute(
                text(
                    "UPDATE memory_records "
                    "SET payload = json_set(payload, '$.body', json('{\"text\":\"new\"}')) "
                    "WHERE mem_id = :mem_id AND version = 1"
                ),
                {"mem_id": created.mem_id},
            )
            await session.commit()
        assert "memory body is immutable" in str(caught.value)
        await session.rollback()
    async with factory() as session:
        assert (await MemoryStore(session).get(created.mem_id, 1)).body == {"text": "old"}


@pytest.mark.asyncio
async def test_concurrent_append_has_one_winner_and_no_duplicate_version(factory) -> None:
    async with factory() as session:
        created = await MemoryStore(session).create(_memory())
        await session.commit()

    async def append(text_value: str) -> str:
        async with factory() as session:
            try:
                await MemoryStore(session).append_version(
                    created.mem_id, 1, body={"text": text_value}
                )
                await session.commit()
                return "ok"
            except MemoryVersionConflict:
                await session.rollback()
                return "conflict"
            except Exception as exc:  # surfaced by the assertion below
                await session.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(append("a"), append("b"))
    assert sorted(results) == ["conflict", "ok"]
    async with factory() as session:
        versions = list(
            (
                await session.execute(
                    select(MemoryRecordRow.version)
                    .where(MemoryRecordRow.mem_id == created.mem_id)
                    .order_by(MemoryRecordRow.version)
                )
            ).scalars()
        )
    assert versions == [1, 2]