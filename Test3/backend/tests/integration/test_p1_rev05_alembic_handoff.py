"""P1-REV-05: Alembic is the only schema upgrade authority.

Both paths use a temporary SQLite file; the user's real database is never
opened, upgraded or stamped.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from alembic import command
from app.execution.grant_repo import GrantRepo
from app.schemas.execution_grant import ExecutionGrant
from app.storage.db import create_all, make_engine, session_factory, sqlite_url
from tests.p1_support import make_bench


def _cfg(tmp_path: Path) -> tuple[Config, Path]:
    backend = Path(__file__).resolve().parents[2]
    db = tmp_path / "handoff.db"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return cfg, db


def _grant(run_id: str = "run-handoff") -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-HANDOFF",
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=[],
        created_at="2026-11-19T00:00:00+00:00",
    )


def _table_names(db: Path) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
    finally:
        con.close()


def test_0001_database_survives_workbench_grant_then_upgrade_head(tmp_path: Path) -> None:
    cfg, db = _cfg(tmp_path)
    command.upgrade(cfg, "0001")

    async def seed_grant_through_old_workbench_path() -> None:
        engine = make_engine(sqlite_url(db))
        try:
            await create_all(engine)
            async with session_factory(engine)() as session:
                await GrantRepo(session).add(_grant())
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed_grant_through_old_workbench_path())
    assert "execution_grants" in _table_names(db)

    try:
        command.upgrade(cfg, "head")
    except OperationalError as exc:  # pragma: no cover - pre-fix failure path
        pytest.fail(f"upgrade head failed after Workbench wrote grants: {exc}")

    con = sqlite3.connect(db)
    try:
        remaining = con.execute("select count(*) from execution_grants").fetchone()[0]
    finally:
        con.close()
    assert remaining == 1


def test_runtime_boot_then_alembic_upgrade_does_not_double_create(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db = data_dir / "test3.db"
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.set_main_option("script_location", str(backend / "alembic"))

    async def boot_runtime() -> None:
        bench = make_bench(data_dir)
        try:
            await bench._ensure_db()
        finally:
            await bench.close()

    asyncio.run(boot_runtime())
    try:
        command.upgrade(cfg, "head")
    except OperationalError as exc:  # pragma: no cover - pre-fix failure path
        pytest.fail(f"first Alembic upgrade failed after runtime create_all: {exc}")

    expected_head = ScriptDirectory.from_config(cfg).get_current_head()
    con = sqlite3.connect(db)
    try:
        version = con.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        con.close()
    assert version == expected_head