"""Run-scoped frozen bot pins.

A run freezes the latest pin of each participating bot once.  Later bot edits
append new pin revisions but never touch the snapshot, so a long-running task
keeps the model/provider/skill authorization it started with.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bots.registry import BotRegistry
from app.errors import Test3Error
from app.schemas.skill_definition import SkillDefinition
from app.settings import get_settings
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import RunBotPinSnapshotRow, SkillDefinitionRow


class BotPinError(Test3Error):
    code = "BOT_PIN_ERROR"

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@asynccontextmanager
async def _session_scope(session: AsyncSession | None, db_path: Path | None):
    if session is not None:
        yield session, False
        return
    path = Path(db_path) if db_path is not None else get_settings().data_dir() / "test3.db"
    upgrade_database(path)
    engine = make_engine(sqlite_url(path))
    factory = session_factory(engine)
    try:
        async with factory() as owned:
            yield owned, True
    finally:
        await engine.dispose()


async def _get_pin(session: AsyncSession, run_id: str, bot_id: str) -> dict:
    row = await session.get(RunBotPinSnapshotRow, (run_id, bot_id))
    if row is None:
        raise BotPinError(
            "pin_snapshot_missing",
            f"no frozen pin for run {run_id} and bot {bot_id}",
        )
    return dict(row.payload)


async def freeze_bot_pins(
    run_id: str,
    bot_ids: list[str],
    *,
    session: AsyncSession | None = None,
    db_path: Path | None = None,
) -> None:
    """Freeze each bot's current latest pin for ``run_id``; never overwrite."""
    async with _session_scope(session, db_path) as (sess, owned):
        registry = BotRegistry(sess)
        for bot_id in bot_ids:
            if await sess.get(RunBotPinSnapshotRow, (run_id, bot_id)) is not None:
                continue
            pin = await registry.latest_pin(bot_id)
            payload = {
                "revision": pin["revision"],
                "model": pin["model"],
                "provider_ref": pin["provider_ref"],
                "skill_bindings": list(pin["skill_bindings"]),
            }
            # INSERT OR IGNORE keeps two concurrent freezes idempotent without
            # ever replacing the first snapshot.
            await sess.execute(
                text(
                    "INSERT OR IGNORE INTO run_bot_pin_snapshots "
                    "(run_id, bot_id, payload) VALUES (:run_id, :bot_id, :payload)"
                ),
                {
                    "run_id": run_id,
                    "bot_id": bot_id,
                    "payload": json.dumps(payload),
                },
            )
        if owned:
            await sess.commit()


async def get_frozen_pin(
    run_id: str,
    bot_id: str,
    *,
    session: AsyncSession | None = None,
    db_path: Path | None = None,
) -> dict:
    async with _session_scope(session, db_path) as (sess, _owned):
        return await _get_pin(sess, run_id, bot_id)


async def get_frozen_skill(
    run_id: str,
    bot_id: str,
    skill_id: str,
    *,
    session: AsyncSession | None = None,
    db_path: Path | None = None,
) -> SkillDefinition:
    async with _session_scope(session, db_path) as (sess, _owned):
        pin = await _get_pin(sess, run_id, bot_id)
        binding = next(
            (item for item in pin.get("skill_bindings", []) if item.get("skill_id") == skill_id),
            None,
        )
        if binding is None:
            raise BotPinError(
                "skill_not_bound",
                f"bot {bot_id} has no pinned skill {skill_id} for run {run_id}",
            )
        row = await sess.get(SkillDefinitionRow, (skill_id, binding["pinned_version"]))
        if row is None:
            raise BotPinError(
                "skill_version_missing",
                f"pinned skill version {skill_id}@{binding['pinned_version']} is missing",
            )
        return SkillDefinition.model_validate(row.payload)


async def frozen_skill_tools(
    run_id: str,
    bot_id: str,
    skill_id: str,
    *,
    session: AsyncSession | None = None,
    db_path: Path | None = None,
) -> set[str]:
    skill = await get_frozen_skill(
        run_id, bot_id, skill_id, session=session, db_path=db_path
    )
    return set(skill.allowed_tool_refs)


__all__ = [
    "BotPinError",
    "freeze_bot_pins",
    "frozen_skill_tools",
    "get_frozen_pin",
    "get_frozen_skill",
]