from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.agents.runtime import RoleRegistry, call_agent
from app.bots.registry import BotRegistry
from app.bots.snapshot import BotPinError, freeze_bot_pins
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.memory.promotion import MemoryPromotionService
from app.memory.store import MemoryStore
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.memory import MemoryCreate, MemoryRecord
from app.settings import load_models, load_roles
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database


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


def _bot(name: str, model: str = "qwen-plus") -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref="dashscope",
        model=model,
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
    )


def _gateway(tmp_path: Path, provider) -> Gateway:
    return Gateway(load_models(), provider, data_dir=tmp_path)


async def _seed(store):
    db, factory = store
    async with factory() as session:
        owner = await BotRegistry(session).create(_bot("Owner"))
        other = await BotRegistry(session).create(_bot("Other"))
        await session.commit()
    async with factory() as session:
        membership = MembershipService(session, project_exists=lambda _pid: True)
        await membership.add("P1", MembershipCreate(bot_id=owner.bot_id, role_in_project="dev"))
        await session.commit()
    async with factory() as session:
        memory = MemoryStore(session)
        await memory.create(
            MemoryCreate(
                owner_bot_id=owner.bot_id,
                visibility="private",
                sources=[],
                body={"text": "private-body"},
                title="private-note",
            )
        )
        project = await memory.create(
            MemoryCreate(
                owner_bot_id=owner.bot_id,
                project_id="P1",
                visibility="project",
                sources=[],
                body={"text": "project-body"},
                title="project-note",
            )
        )
        await memory.create(
            MemoryCreate(
                owner_bot_id=owner.bot_id,
                visibility="run",
                run_id="run-1",
                sources=[],
                body={"text": "run-body"},
                title="run-note",
            )
        )
        await session.commit()
    async with factory() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(
            project.mem_id, 1, actor=owner.bot_id
        )
        await session.commit()
    async with factory() as session:
        await MemoryStore(session).create(
            MemoryCreate(
                owner_bot_id=other.bot_id,
                visibility="private",
                sources=[],
                body={"text": "other-body"},
                title="other-private-note",
            )
        )
        await session.commit()
    await freeze_bot_pins("run-1", [owner.bot_id], db_path=db)
    return owner.bot_id, other.bot_id


@pytest.mark.asyncio
async def test_bot_call_injects_only_own_memory_and_keeps_frozen_model(store, tmp_path: Path) -> None:
    owner, _other = await _seed(store)
    provider = RecordingScriptedProvider([{"approach": "x", "features": ["a"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
        bot_id=owner,
        run_id="run-1",
        project_id="P1",
    )
    assert result.approach == "x"
    blob = json.dumps(provider.calls[0]["messages"], ensure_ascii=False)
    assert "private-note" in blob
    assert "project-note" in blob
    assert "run-note" in blob
    assert "other-private-note" not in blob
    assert provider.requested_models == ["qwen-plus"]


@pytest.mark.asyncio
async def test_without_bot_id_never_builds_memory_or_uses_http(
    store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("bot_id=None must not build memory")

    monkeypatch.setattr("app.agents.runtime.build_memory_slot", boom)
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("http")
        raise AssertionError("scripted path must not use HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    provider = RecordingScriptedProvider([{"approach": "default", "features": ["a"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
    )
    assert result.approach == "default"
    assert calls == []


@pytest.mark.asyncio
async def test_explicit_memory_slot_is_injected_without_bot(tmp_path: Path) -> None:
    provider = RecordingScriptedProvider([{"approach": "explicit", "features": ["a"]}])
    result = await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
        memory_slot=[
            {
                "mem_id": "m1",
                "version": 1,
                "visibility": "private",
                "title": "explicit-memory",
                "body": {"text": "x"},
            }
        ],
    )
    assert result.approach == "explicit"
    blob = json.dumps(provider.calls[0]["messages"], ensure_ascii=False)
    assert "explicit-memory" in blob


@pytest.mark.asyncio
async def test_dirty_secret_record_is_dropped_from_injection(store, tmp_path: Path) -> None:
    db, factory = store
    async with factory() as session:
        owner = await BotRegistry(session).create(_bot("Owner"))
        await session.commit()
    await freeze_bot_pins("run-1", [owner.bot_id], db_path=db)
    dirty = MemoryRecord(
        mem_id="dirty",
        owner_bot_id=owner.bot_id,
        project_id=None,
        visibility="private",
        version=1,
        status="pending",
        sources=[],
        body={"text": "sk-leak"},
        title="dirty-note",
    )
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO memory_records "
                "(mem_id, version, owner_bot_id, project_id, visibility, status, payload) "
                "VALUES (:mem_id, :version, :owner, :project, :visibility, :status, :payload)"
            ),
            {
                "mem_id": dirty.mem_id,
                "version": dirty.version,
                "owner": dirty.owner_bot_id,
                "project": dirty.project_id,
                "visibility": dirty.visibility,
                "status": dirty.status,
                "payload": dirty.model_dump_json(),
            },
        )
        await session.commit()
    provider = RecordingScriptedProvider([{"approach": "safe", "features": ["a"]}])
    await call_agent(
        "pm_draft",
        {"idea_card": {"raw": "x"}},
        registry=RoleRegistry(load_roles()),
        gateway=_gateway(tmp_path, provider),
        bot_id=owner.bot_id,
        run_id="run-1",
    )
    blob = json.dumps(provider.calls[0]["messages"], ensure_ascii=False)
    assert "sk-leak" not in blob
    assert "dirty-note" not in blob


@pytest.mark.asyncio
async def test_missing_pin_blocks_before_memory_injection(
    store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, factory = store
    async with factory() as session:
        owner = await BotRegistry(session).create(_bot("Owner"))
        await session.commit()

    def boom(*args, **kwargs):
        raise AssertionError("memory must not be built before the pin is resolved")

    monkeypatch.setattr("app.agents.runtime.build_memory_slot", boom)
    provider = RecordingScriptedProvider([{"approach": "x", "features": []}])
    with pytest.raises(BotPinError) as caught:
        await call_agent(
            "pm_draft",
            {"idea_card": {"raw": "x"}},
            registry=RoleRegistry(load_roles()),
            gateway=_gateway(tmp_path, provider),
            bot_id=owner.bot_id,
            run_id="run-1",
        )
    assert caught.value.category == "pin_snapshot_missing"
    assert provider.calls == []