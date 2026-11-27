from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete

from app.agents.runtime import RoleRegistry, call_agent
from app.bots.registry import BotRegistry
from app.bots.snapshot import (
    BotPinError,
    freeze_bot_pins,
    frozen_skill_tools,
    get_frozen_pin,
    get_frozen_skill,
)
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.bot import BotCreate, BotPatch, BotSkillBinding
from app.schemas.skill_definition import SkillCreate
from app.skills.registry import SkillRegistry
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import SkillDefinitionRow
from app.settings import load_models, load_roles


class RecordingScriptedProvider(ScriptedProvider):
    def __init__(self, queue=None) -> None:
        super().__init__(queue)
        self.requested_models: list[str | None] = []

    async def complete(self, slot, messages, *, schema=None, tools=None, **kwargs):
        self.requested_models.append(kwargs.get("model"))
        return await super().complete(slot, messages, schema=schema, tools=tools, **kwargs)


@pytest.fixture
async def store(tmp_path: Path):
    db = tmp_path / "test3.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield db, session_factory(engine)
    await engine.dispose()


def _bot(
    *,
    name: str = "Alice",
    model: str = "qwen-plus",
    provider_ref: str = "dashscope",
    bindings: list[BotSkillBinding] | None = None,
) -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref=provider_ref,
        model=model,
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
        skill_bindings=list(bindings or []),
    )


def _skill(version: str, refs: list[str], description: str = "x") -> SkillCreate:
    return SkillCreate(
        skill_id="review",
        version=version,
        description_md=description,
        allowed_tool_refs=refs,
    )


async def _create_bot(factory, data: BotCreate) -> str:
    async with factory() as session:
        bot = await BotRegistry(session).create(data)
        await session.commit()
        return bot.bot_id


async def _add_skill(factory, data: SkillCreate) -> None:
    async with factory() as session:
        await SkillRegistry(session).create(data)
        await session.commit()


def _gateway(tmp_path: Path, provider) -> Gateway:
    return Gateway(load_models(), provider, data_dir=tmp_path)


@pytest.mark.asyncio
async def test_frozen_pin_survives_later_patch_and_drives_gateway_model(store, tmp_path: Path) -> None:
    db, factory = store
    bot_id = await _create_bot(factory, _bot(model="qwen-plus"))
    await freeze_bot_pins("run-A", [bot_id], db_path=db)

    async with factory() as session:
        await BotRegistry(session).update(bot_id, BotPatch(model="newer-model"))
        await session.commit()

    pin = await get_frozen_pin("run-A", bot_id, db_path=db)
    assert pin["model"] == "qwen-plus"
    assert pin["revision"] == 1

    provider = RecordingScriptedProvider([{"approach": "上报+查看", "features": ["a", "b"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
        bot_id=bot_id,
        run_id="run-A",
    )
    assert result.approach == "上报+查看"
    assert provider.requested_models == ["qwen-plus"]


@pytest.mark.asyncio
async def test_frozen_skill_version_does_not_follow_latest(store) -> None:
    db, factory = store
    await _add_skill(factory, _skill("1.0.0", ["git_read"]))
    bot_id = await _create_bot(
        factory, _bot(bindings=[BotSkillBinding(skill_id="review", pinned_version="1.0.0")])
    )
    await freeze_bot_pins("run-B", [bot_id], db_path=db)
    await _add_skill(factory, _skill("2.0.0", ["shell_exec"]))

    skill = await get_frozen_skill("run-B", bot_id, "review", db_path=db)
    assert skill.version == "1.0.0"
    assert skill.allowed_tool_refs == ["git_read"]
    assert await frozen_skill_tools("run-B", bot_id, "review", db_path=db) == {"git_read"}

    await _add_skill(factory, _skill("3.0.0", ["network"]))
    async with factory() as session:
        await session.execute(
            delete(SkillDefinitionRow).where(
                SkillDefinitionRow.skill_id == "review",
                SkillDefinitionRow.version == "1.0.0",
            )
        )
        await session.commit()

    with pytest.raises(BotPinError) as caught:
        await frozen_skill_tools("run-B", bot_id, "review", db_path=db)
    assert caught.value.category == "skill_version_missing"


@pytest.mark.asyncio
async def test_unbound_skill_is_rejected(store) -> None:
    db, factory = store
    bot_id = await _create_bot(factory, _bot(bindings=[]))
    await freeze_bot_pins("run-B", [bot_id], db_path=db)
    with pytest.raises(BotPinError) as caught:
        await get_frozen_skill("run-B", bot_id, "review", db_path=db)
    assert caught.value.category == "skill_not_bound"


@pytest.mark.asyncio
async def test_scripted_path_makes_no_external_http_calls(store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, factory = store
    bot_id = await _create_bot(factory, _bot(model="qwen-plus"))
    await freeze_bot_pins("run-C", [bot_id], db_path=db)
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("http")
        raise AssertionError("scripted path must not use HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    try:
        import requests  # type: ignore[import-not-found]

        monkeypatch.setattr(requests.Session, "request", forbidden)
    except ImportError:
        pass

    provider = RecordingScriptedProvider([{"approach": "scripted", "features": ["a"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
        bot_id=bot_id,
        run_id="run-C",
    )
    assert result.approach == "scripted"
    assert calls == []


@pytest.mark.asyncio
async def test_without_bot_id_never_reads_snapshot(store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("bot_id=None must not read snapshot tables")

    monkeypatch.setattr("app.agents.runtime.get_frozen_pin", boom)
    provider = RecordingScriptedProvider([{"approach": "default", "features": ["a"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
    )
    assert result.approach == "default"
    assert provider.requested_models == [load_models().slots["flagship"].model]


@pytest.mark.asyncio
async def test_two_runs_freeze_independent_pins_and_refreeze_keeps_first(store) -> None:
    db, factory = store
    bot_id = await _create_bot(factory, _bot(model="v1"))
    await freeze_bot_pins("run-A", [bot_id], db_path=db)

    async with factory() as session:
        await BotRegistry(session).update(bot_id, BotPatch(model="v2"))
        await session.commit()
    await freeze_bot_pins("run-B", [bot_id], db_path=db)

    async with factory() as session:
        await BotRegistry(session).update(bot_id, BotPatch(model="v3"))
        await session.commit()
    await freeze_bot_pins("run-A", [bot_id], db_path=db)

    assert (await get_frozen_pin("run-A", bot_id, db_path=db))["model"] == "v1"
    assert (await get_frozen_pin("run-B", bot_id, db_path=db))["model"] == "v2"


@pytest.mark.asyncio
async def test_missing_snapshot_and_missing_run_id_errors(store, tmp_path: Path) -> None:
    db, factory = store
    bot_id = await _create_bot(factory, _bot())
    with pytest.raises(BotPinError) as missing:
        await get_frozen_pin("run-X", bot_id, db_path=db)
    assert missing.value.category == "pin_snapshot_missing"

    provider = RecordingScriptedProvider([{"approach": "x", "features": []}])
    with pytest.raises(BotPinError) as no_run:
        await call_agent(
            "pm_draft",
            {"idea_card": {"raw": "x"}},
            registry=RoleRegistry(load_roles()),
            gateway=_gateway(tmp_path, provider),
            bot_id=bot_id,
        )
    assert no_run.value.category == "run_id_required"
    assert provider.requested_models == []