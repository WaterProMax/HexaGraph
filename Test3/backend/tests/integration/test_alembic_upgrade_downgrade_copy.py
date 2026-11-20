"""P7-T02: Alembic compatibility on a *copy* of a P0-era database.

The source is a fresh database migrated only to ``0001`` (the head recorded in
the P0 report).  Every upgrade/downgrade runs on a copy inside pytest's
tmp_path; the user's ``Test3/data/test3.db`` is never opened or migrated.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from alembic import command
from app.settings import get_settings
from app.storage.migrate import alembic_config

P0_HEAD = "0001"
CURRENT_HEAD = "0010"

REQUIRED_TABLES = {
    "bots",
    "skill_definitions",
    "project_memberships",
    "execution_grants",
    "memory_records",
    "discussion_sessions",
}
RECOMMENDED_TABLES = {
    "bot_pin_revisions",
    "run_bot_pin_snapshots",
    "discussion_proposals",
    "discussion_reviews",
    "module_acceptances",
    "defects",
    "run_execution_state",
}
C6_TABLES = REQUIRED_TABLES | RECOMMENDED_TABLES


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


def test_copy_of_p0_head_upgrades_downgrades_and_upgrades(tmp_path: Path) -> None:
    source = tmp_path / "p0-era-0001.db"
    command.upgrade(alembic_config(source), P0_HEAD)
    assert _version(source) == P0_HEAD

    # The experiment runs on a copy, never on the source or the user's data dir.
    work = tmp_path / "tmp-copy-under-test.db"
    shutil.copy2(source, work)
    user_db = Path(get_settings().data_dir()) / "test3.db"
    assert work != user_db
    assert str(work).startswith(str(tmp_path))
    assert _version(work) == P0_HEAD

    command.upgrade(alembic_config(work), "head")
    assert _version(work) == CURRENT_HEAD
    tables = _tables(work)
    assert REQUIRED_TABLES <= tables, sorted(REQUIRED_TABLES - tables)
    assert RECOMMENDED_TABLES <= tables, sorted(RECOMMENDED_TABLES - tables)
    assert {"mem_id", "version", "owner_bot_id", "payload"} <= _columns(work, "memory_records")
    assert {"grant_id", "run_id", "status", "payload"} <= _columns(work, "execution_grants")
    assert {"session_id", "project_id", "status", "payload"} <= _columns(work, "discussion_sessions")

    # Downgrade back to the P0 head on the copy only.
    command.downgrade(alembic_config(work), P0_HEAD)
    assert _version(work) == P0_HEAD
    after_down = _tables(work)
    assert not (C6_TABLES & after_down), sorted(C6_TABLES & after_down)

    # And the copy is still a valid database that can reach head again.
    command.upgrade(alembic_config(work), "head")
    assert _version(work) == CURRENT_HEAD
    assert C6_TABLES <= _tables(work)

    # The user's data directory was not used as the experiment target.
    assert not user_db.exists() or user_db != work