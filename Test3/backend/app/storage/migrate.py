"""Single Alembic entry point for the production SQLite schema."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # Alembic's env.py uses a synchronous engine; the runtime async URL would
    # make ``engine_from_config`` fail before any migration runs.
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{Path(db_path)}")
    return cfg


def upgrade_database(db_path: Path) -> None:
    command.upgrade(alembic_config(db_path), "head")


__all__ = ["alembic_config", "upgrade_database"]
