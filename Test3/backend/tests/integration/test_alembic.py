from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command


def test_alembic_upgrade_and_downgrade(tmp_path: Path) -> None:
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    db = tmp_path / "mig.db"
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
