"""0012: ``discussion_messages`` upgrade/downgrade on a tmp_path database.

The migration only adds the append-only message timeline; existing tables from
0011 must survive both directions.  The round-trip test goes through
``upgrade_database()`` so the same entry point production uses is exercised.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy import select

from alembic import command
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import alembic_config, upgrade_database
from app.storage.models import DiscussionMessageRow

HEAD = "0012"
PREVIOUS = "0011"
COLUMNS = {"session_id", "seq", "kind", "bot_id", "round", "payload", "created_at"}
INDEX = "ix_discussion_messages_session"
SURVIVING_TABLES = {"discussion_sessions", "discussion_proposals", "discussion_reviews", "bot_files"}


def _version(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("select version_num from alembic_version").fetchone()
        return str(row[0]) if row else ""
    finally:
        connection.close()


def _tables(db_path: Path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute("select name from sqlite_master where type = 'table'").fetchall()
        return {str(row[0]) for row in rows}
    finally:
        connection.close()


def _columns(db_path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(f"pragma table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
    finally:
        connection.close()


def _indexes(db_path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(f"pragma index_list({table})").fetchall()
        return {str(row[1]) for row in rows}
    finally:
        connection.close()


def test_discussion_messages_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    db = tmp_path / "messages-mig.db"
    command.upgrade(alembic_config(db), "head")

    assert _version(db) == HEAD
    assert "discussion_messages" in _tables(db)
    assert _columns(db, "discussion_messages") == COLUMNS
    assert INDEX in _indexes(db, "discussion_messages")

    command.downgrade(alembic_config(db), PREVIOUS)
    assert _version(db) == PREVIOUS
    assert "discussion_messages" not in _tables(db)
    surviving = _tables(db)
    assert SURVIVING_TABLES <= surviving, sorted(SURVIVING_TABLES - surviving)

    command.upgrade(alembic_config(db), HEAD)
    assert _version(db) == HEAD
    assert "discussion_messages" in _tables(db)
    assert _columns(db, "discussion_messages") == COLUMNS
    assert INDEX in _indexes(db, "discussion_messages")


def test_migrated_database_round_trips_a_discussion_message(tmp_path: Path) -> None:
    db = tmp_path / "messages-round-trip.db"
    upgrade_database(db)
    assert _version(db) == HEAD

    async def write_and_read() -> DiscussionMessageRow:
        engine = make_engine(sqlite_url(db))
        try:
            async with session_factory(engine)() as session:
                session.add(
                    DiscussionMessageRow(
                        session_id="s1",
                        seq=1,
                        kind="system",
                        bot_id=None,
                        round=0,
                        payload={"event": "session_started"},
                        created_at="2026-11-20T00:00:00+00:00",
                    )
                )
                await session.commit()
            async with session_factory(engine)() as session:
                row = await session.scalar(
                    select(DiscussionMessageRow).where(
                        DiscussionMessageRow.session_id == "s1",
                        DiscussionMessageRow.seq == 1,
                    )
                )
                assert row is not None
                return row
        finally:
            await engine.dispose()

    row = asyncio.run(write_and_read())
    assert row.kind == "system"
    assert row.bot_id is None
    assert row.round == 0
    assert row.payload == {"event": "session_started"}
    assert row.created_at == "2026-11-20T00:00:00+00:00"