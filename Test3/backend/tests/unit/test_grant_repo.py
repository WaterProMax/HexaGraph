from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.execution.grant_repo import GrantRepo
from app.schemas.execution_grant import ExecutionGrant
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database


def _grant(grant_id: str = "G-1", run_id: str = "run-A", created_at: str = "2026-11-19T00:00:00+00:00") -> ExecutionGrant:
    return ExecutionGrant(
        grant_id=grant_id,
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat-p1-demo",
        allowed_tool_refs=[],
        status="active",
        created_at=created_at,
    )


@pytest.fixture
async def factory(tmp_path: Path):
    db = tmp_path / "grants.db"
    # Production uses Alembic only; this unit fixture does the same so the repo
    # tests cannot keep a second create_all schema path alive.
    upgrade_database(db)
    engine = make_engine(sqlite_url(db))
    yield session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_removes_uncommitted_grant(factory) -> None:
    async with factory() as session:
        await GrantRepo(session).add(_grant())
        await session.rollback()
    async with factory() as session:
        assert await GrantRepo(session).list_for_run("run-A") == []


@pytest.mark.asyncio
async def test_list_for_run_filters_by_run(factory) -> None:
    async with factory() as session:
        repo = GrantRepo(session)
        await repo.add(_grant("G-1", "run-A"))
        await repo.add(_grant("G-2", "run-B"))
        await session.commit()
    async with factory() as session:
        items = await GrantRepo(session).list_for_run("run-A")
    assert [item.grant_id for item in items] == ["G-1"]


@pytest.mark.asyncio
async def test_get_and_update_status(factory) -> None:
    async with factory() as session:
        repo = GrantRepo(session)
        await repo.add(_grant())
        await session.commit()
    async with factory() as session:
        repo = GrantRepo(session)
        updated = await repo.update_status("G-1", "consumed")
        await session.commit()
        assert updated.status == "consumed"
    async with factory() as session:
        stored = await GrantRepo(session).get("G-1")
    assert stored is not None
    assert stored.status == "consumed"


@pytest.mark.asyncio
async def test_two_sessions_duplicate_pk_only_one_row(factory) -> None:
    async with factory() as first:
        await GrantRepo(first).add(_grant())
        await first.commit()
    async with factory() as second:
        with pytest.raises(IntegrityError):
            await GrantRepo(second).add(_grant())
            await second.commit()
    async with factory() as session:
        assert len(await GrantRepo(session).list_for_run("run-A")) == 1