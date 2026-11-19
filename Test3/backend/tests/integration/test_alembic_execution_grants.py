from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command


def _cfg(tmp_path: Path) -> tuple[Config, Path]:
    backend = Path(__file__).resolve().parents[2]
    db = tmp_path / "grants-mig.db"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return cfg, db


def _columns(db: Path, table: str) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        return {column["name"] for column in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_execution_grants_upgrade_and_downgrade(tmp_path: Path) -> None:
    cfg, db = _cfg(tmp_path)
    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        assert "execution_grants" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()
    assert {"grant_id", "run_id", "status", "payload"} <= _columns(db, "execution_grants")

    command.downgrade(cfg, "0001")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        assert "execution_grants" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")
    assert {"grant_id", "run_id", "status", "payload"} <= _columns(db, "execution_grants")