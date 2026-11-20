from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.bots.registry import (
    BotAlreadyArchived,
    BotArchived,
    BotNameConflict,
    BotNotFound,
    BotRegistry,
)
from app.schemas.bot import BotCreate, BotPatch, BotSkillBinding
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import BotPinRevisionRow, BotRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "bots.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


def _bindings(*pairs: tuple[str, str]) -> list[BotSkillBinding]:
    return [BotSkillBinding(skill_id=skill_id, pinned_version=version) for skill_id, version in pairs]


def _bot(
    *,
    display_name: str = "Alice",
    model: str = "qwen-plus",
    provider_ref: str = "dashscope",
    secret_ref: str = "DASHSCOPE_API_KEY",
    bindings: list[BotSkillBinding] | None = None,
) -> BotCreate:
    return BotCreate(
        display_name=display_name,
        role_template="developer",
        provider_ref=provider_ref,
        model=model,
        slot="coder",
        secret_ref=secret_ref,
        tool_policy=["git_read"],
        skill_bindings=list(bindings if bindings is not None else []),
        token_budget=40_000,
    )


@pytest.mark.asyncio
async def test_create_bot_and_first_pin(factory) -> None:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot(bindings=_bindings(("review", "1.0.0"))))
        await session.commit()
    assert bot.bot_id
    assert bot.status == "active"
    async with factory() as session:
        pin = await BotRegistry(session).latest_pin(bot.bot_id)
    assert pin["revision"] == 1
    assert pin["model"] == "qwen-plus"
    assert pin["provider_ref"] == "dashscope"
    assert pin["skill_bindings"] == [{"skill_id": "review", "pinned_version": "1.0.0"}]


@pytest.mark.asyncio
async def test_model_update_appends_pin_and_keeps_old_revision(factory) -> None:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot())
        await session.commit()
    async with factory() as session:
        updated = await BotRegistry(session).update(bot.bot_id, BotPatch(model="gpt-4o-compatible"))
        await session.commit()
    assert updated.model == "gpt-4o-compatible"
    async with factory() as session:
        registry = BotRegistry(session)
        latest = await registry.latest_pin(bot.bot_id)
        first = await registry.pin_at(bot.bot_id, 1)
        fetched = await registry.get(bot.bot_id)
    assert latest["revision"] == 2
    assert latest["model"] == "gpt-4o-compatible"
    assert first["model"] == "qwen-plus"
    assert fetched.model == "gpt-4o-compatible"


@pytest.mark.asyncio
async def test_display_name_only_update_does_not_append_pin(factory) -> None:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot())
        await session.commit()
    async with factory() as session:
        await BotRegistry(session).update(bot.bot_id, BotPatch(display_name="Bob"))
        await session.commit()
    async with factory() as session:
        assert (await BotRegistry(session).latest_pin(bot.bot_id))["revision"] == 1


@pytest.mark.asyncio
async def test_display_name_is_case_insensitively_unique(factory) -> None:
    async with factory() as session:
        await BotRegistry(session).create(_bot(display_name="alice"))
        await session.commit()
    async with factory() as session:
        with pytest.raises(BotNameConflict):
            await BotRegistry(session).create(_bot(display_name="Alice"))
        await session.rollback()


@pytest.mark.asyncio
async def test_archive_keeps_history_and_blocks_binding_changes(factory) -> None:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot())
        await session.commit()
    async with factory() as session:
        archived = await BotRegistry(session).archive(bot.bot_id)
        await session.commit()
    assert archived.status == "archived"
    async with factory() as session:
        registry = BotRegistry(session)
        assert (await registry.get(bot.bot_id)).status == "archived"
        assert (await registry.pin_at(bot.bot_id, 1))["model"] == "qwen-plus"
        with pytest.raises(BotAlreadyArchived):
            await registry.archive(bot.bot_id)
        await session.rollback()
    async with factory() as session:
        with pytest.raises(BotArchived):
            await BotRegistry(session).update(bot.bot_id, BotPatch(model="other-model"))
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_ref_stores_env_name_not_secret_value(factory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASH_SCOPE_KEY", "sk-leak")
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot(secret_ref="DASH_SCOPE_KEY"))
        await session.commit()
    async with factory() as session:
        row = await session.get(BotRow, bot.bot_id)
    assert row is not None
    assert row.payload["secret_ref"] == "DASH_SCOPE_KEY"
    assert "sk-leak" not in json.dumps(row.payload)


@pytest.mark.asyncio
async def test_missing_bot_raises(factory) -> None:
    async with factory() as session:
        with pytest.raises(BotNotFound):
            await BotRegistry(session).get("no-such")


@pytest.mark.asyncio
async def test_concurrent_updates_never_duplicate_revisions(factory) -> None:
    async with factory() as session:
        bot = await BotRegistry(session).create(_bot())
        await session.commit()

    async def update(model: str) -> str:
        async with factory() as session:
            try:
                await BotRegistry(session).update(bot.bot_id, BotPatch(model=model))
                await session.commit()
                return "ok"
            except Exception as exc:  # surfaced by the assertion below
                await session.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(update("model-a"), update("model-b"))
    assert results == ["ok", "ok"]
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(BotPinRevisionRow)
                    .where(BotPinRevisionRow.bot_id == bot.bot_id)
                    .order_by(BotPinRevisionRow.revision)
                )
            ).scalars()
        )
    revisions = [row.revision for row in rows]
    assert revisions == sorted(set(revisions))
    assert revisions[0] == 1
    assert max(revisions) in {2, 3}
    assert rows[0].model == "qwen-plus"