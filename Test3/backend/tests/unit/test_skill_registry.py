from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.execution.tool_policy import effective_tools
from app.schemas.skill_definition import SkillCreate, SkillDefinition
from app.skills.registry import SkillNotFound, SkillRegistry, SkillVersionExists
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import SkillDefinitionRow


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "skills.db"
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


def _skill(
    *,
    skill_id: str = "review",
    version: str = "1.0.0",
    description: str = "x",
    refs: list[str] | None = None,
) -> SkillCreate:
    return SkillCreate(
        skill_id=skill_id,
        version=version,
        description_md=description,
        allowed_tool_refs=list(refs if refs is not None else ["git_read"]),
    )


@pytest.mark.asyncio
async def test_create_and_list_versions(factory) -> None:
    async with factory() as session:
        created = await SkillRegistry(session).create(_skill())
        await session.commit()
    assert created.skill_id == "review"
    assert created.version == "1.0.0"
    async with factory() as session:
        items = await SkillRegistry(session).list_versions("review")
    assert [item.version for item in items] == ["1.0.0"]
    assert items[0].allowed_tool_refs == ["git_read"]


@pytest.mark.asyncio
async def test_duplicate_version_keeps_old_payload(factory) -> None:
    async with factory() as session:
        await SkillRegistry(session).create(_skill(description="x"))
        await session.commit()
    async with factory() as session:
        with pytest.raises(SkillVersionExists):
            await SkillRegistry(session).create(_skill(description="y"))
        await session.rollback()
    async with factory() as session:
        items = await SkillRegistry(session).list_versions("review")
    assert len(items) == 1
    assert items[0].description_md == "x"


@pytest.mark.asyncio
async def test_missing_skill_raises(factory) -> None:
    async with factory() as session:
        with pytest.raises(SkillNotFound):
            await SkillRegistry(session).list_versions("no-such")


@pytest.mark.asyncio
async def test_empty_allowed_refs_are_not_a_wildcard(factory) -> None:
    async with factory() as session:
        await SkillRegistry(session).create(_skill(description="mentions shell_exec", refs=[]))
        await session.commit()
        skill = (await SkillRegistry(session).list_versions("review"))[0]
    bot = SimpleNamespace(tool_policy=["shell_exec", "git_read"])
    grant = SimpleNamespace(allowed_tool_refs=["git_read"])
    assert effective_tools(["git_read", "shell_exec"], bot, grant, skill) == set()
    assert effective_tools(["git_read", "shell_exec"], bot, grant) == {"git_read"}


@pytest.mark.asyncio
async def test_concurrent_duplicate_leaves_one_row(factory) -> None:
    async def attempt() -> str:
        async with factory() as session:
            try:
                await SkillRegistry(session).create(_skill())
                await session.commit()
                return "created"
            except SkillVersionExists:
                await session.rollback()
                return "conflict"

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == ["conflict", "created"]
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(SkillDefinitionRow))).scalar_one()
    assert count == 1


def test_skill_definition_round_trips_contract_fields() -> None:
    skill = SkillDefinition(
        skill_id="review",
        version="1.0.0",
        description_md="x",
        allowed_tool_refs=["git_read"],
    )
    assert skill.model_dump() == {
        "skill_id": "review",
        "version": "1.0.0",
        "description_md": "x",
        "allowed_tool_refs": ["git_read"],
    }