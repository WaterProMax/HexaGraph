"""P7-T01: restart reconciliation (kill process → same data_dir → same rows).

The process-local caches (grant cache, pin snapshots lookup, membership) are
gone after a restart; SQLite must be enough to rebuild them.  Nothing here
touches Test3/data — every test uses pytest's tmp_path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.bots.registry import BotRegistry
from app.bots.snapshot import freeze_bot_pins, get_frozen_pin
from app.discussion.models import DiscussionBudget
from app.discussion.session_store import DiscussionSessionStore
from app.execution.acceptance import list_defects
from app.execution.grant_repo import GrantRepo
from app.execution.run_profile import run_execution_profile
from app.leader.steward import DiscussionSteward
from app.memory.promotion import MemoryPromotionService
from app.memory.store import MemoryStore
from app.ops.reconcile import reconcile
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.memory import MemoryCreate, MemorySource
from app.storage.models import ExecutionGrantRow, MemoryRecordRow, RunBotPinSnapshotRow
from tests.p1_support import install_plan, make_bench, make_grant, persist_granted_profile

EVIDENCE = "file://logs/t01.log"


async def _seed(tmp_path: Path):
    bench = make_bench(tmp_path)
    project = bench.create_project("p7-reconcile")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    await persist_granted_profile(bench, run, {"PLAN": "aaa"})
    grant = make_grant(run.id, ["T-01"])
    await bench.add_grant(grant)
    run.tasks["T-01"]["state"] = "done"
    run.tasks["T-01"]["evidence"] = [{"kind": "command", "summary": "ok", "path": EVIDENCE}]
    await bench.record_defect(
        run,
        {"task_code": "T-01", "module_id": "M1", "evidence_uris": [EVIDENCE], "detail": "缺回归"},
        actor="bot-seed",
    )

    async with bench.db_session() as session:
        bot = await BotRegistry(session).create(
            BotCreate(
                display_name="P7 Leader",
                role_template="coder",
                provider_ref="dashscope",
                model="qwen-max",
                slot="coder",
                secret_ref="DASHSCOPE_API_KEY",
            )
        )
        await session.commit()
    async with bench.db_session() as session:
        await MembershipService(session, project_exists=lambda pid: pid in bench.projects).add(
            project["id"],
            MembershipCreate(bot_id=bot.bot_id, role_in_project="dev", is_leader=True),
        )
        await session.commit()
    await freeze_bot_pins(run.id, [bot.bot_id], db_path=bench.db_path)

    async with bench.db_session() as session:
        memory = await MemoryStore(session).create(
            MemoryCreate(
                owner_bot_id=bot.bot_id,
                project_id=project["id"],
                visibility="project",
                sources=[MemorySource(kind="doc", ref="req.md", sha="a" * 64)],
                body={"decision": "seats"},
                title="座位规则",
            )
        )
        await session.commit()
    async with bench.db_session() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(memory.mem_id, 1, actor=bot.bot_id)
        await session.commit()

    async with bench.db_session() as session:
        steward = DiscussionSteward(session, project_exists=lambda pid: pid in bench.projects)
        discussion = await steward.create_session(
            project["id"], bot.bot_id, [bot.bot_id], "需求快照", DiscussionBudget(max_rounds=2)
        )
        await session.commit()

    bench._persist_snapshot(run)
    return bench, run, bot, grant, memory, discussion


@pytest.mark.asyncio
async def test_restart_keeps_new_domain_rows_and_rebinds_grant(tmp_path: Path) -> None:
    bench, run, bot, grant, memory, discussion = await _seed(tmp_path)
    run_id = run.id
    project_id = run.project_id
    await bench.close()

    restored = make_bench(tmp_path)
    try:
        await restored._ensure_db()
        async with restored.db_session() as session:
            assert (await BotRegistry(session).get(bot.bot_id)).display_name == "P7 Leader"
            members = await MembershipService(
                session, project_exists=lambda pid: pid in restored.projects
            ).list(project_id)
            assert [member.bot_id for member in members] == [bot.bot_id]
            pin = await get_frozen_pin(run_id, bot.bot_id, session=session)
            assert pin["model"] == "qwen-max"
            stored_memory = await MemoryStore(session).get(memory.mem_id)
            assert stored_memory.status == "published"
            stored_discussion = await DiscussionSessionStore(session).get(discussion.session_id)
            assert stored_discussion.project_id == project_id
            defects = await list_defects(session, run_id)
            assert [item.task_code for item in defects] == ["T-01"]
            pin_rows = (
                await session.execute(
                    select(func.count()).select_from(RunBotPinSnapshotRow).where(
                        RunBotPinSnapshotRow.run_id == run_id
                    )
                )
            ).scalar_one()
            assert pin_rows == 1

        grants = await restored.grants_for_run(run_id)
        assert [item.grant_id for item in grants] == [grant.grant_id]
        assert [item.status for item in grants] == ["active"]
        # The cache is hydrated from SQLite during restore, before any request.
        assert [item.grant_id for item in restored._grant_cache[run_id]] == [grant.grant_id]

        restored_run = restored.runs[run_id]
        assert run_execution_profile(restored_run) == "granted_v1"
        restored._attach_granted_specs(restored_run)
        spec = restored_run.tasks["T-01"]["granted_execution"]
        assert spec["grant_id"] == grant.grant_id
        assert spec["tool_refs"] == []
        assert spec["feature_branch"] == grant.feature_branch
        # No duplicate grant or duplicate snapshot was produced by the restore.
        assert len(await restored.grants_for_run(run_id)) == 1
        assert len(restored._grant_cache[run_id]) == 1
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_uncommitted_grant_is_invisible_and_reconcile_succeeds(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    try:
        project = bench.create_project("p7-uncommitted")
        run = bench.create_run(project["id"], "idea")
        install_plan(bench, run, ["T-01"])
        await persist_granted_profile(bench, run, {"PLAN": "aaa"})
        pending = make_grant(run.id, ["T-01"])
        async with bench.db_session() as session:
            await GrantRepo(session).add(pending)
            # Deliberately no commit: this is the crash window.
        await bench.close()

        restored = make_bench(tmp_path)
        try:
            await restored._ensure_db()
            assert await restored.grants_for_run(run.id) == []
            async with restored.db_session() as session:
                report = await reconcile(session)
            assert report.grants_active == 0
            # The database accepts new committed work afterwards.
            await restored.add_grant(pending)
            assert [item.grant_id for item in await restored.grants_for_run(run.id)] == [pending.grant_id]
            async with restored.db_session() as session:
                rows = (
                    await session.execute(select(func.count()).select_from(ExecutionGrantRow))
                ).scalar_one()
            assert rows == 1
        finally:
            await restored.close()
    finally:
        await bench.close()


async def _member_bot(bench, project_id: str, name: str) -> str:
    async with bench.db_session() as session:
        bot = await BotRegistry(session).create(
            BotCreate(
                display_name=name,
                role_template="coder",
                provider_ref="dashscope",
                model="qwen-max",
                slot="coder",
                secret_ref="DASHSCOPE_API_KEY",
            )
        )
        await session.commit()
    async with bench.db_session() as session:
        await MembershipService(session, project_exists=lambda pid: pid in bench.projects).add(
            project_id,
            MembershipCreate(bot_id=bot.bot_id, role_in_project="dev", is_leader=True),
        )
        await session.commit()
    return bot.bot_id


async def _published_memory(bench, project_id: str, name: str) -> str:
    bot_id = await _member_bot(bench, project_id, name)
    async with bench.db_session() as session:
        record = await MemoryStore(session).create(
            MemoryCreate(
                owner_bot_id=bot_id,
                project_id=project_id,
                visibility="project",
                sources=[MemorySource(kind="doc", ref="req.md", sha="b" * 64)],
                body={"decision": "seats"},
                title="座位规则",
            )
        )
        await session.commit()
    async with bench.db_session() as session:
        await MemoryPromotionService(MemoryStore(session)).publish(record.mem_id, 1, actor=bot_id)
        await session.commit()
    return record.mem_id


@pytest.mark.asyncio
async def test_reconcile_keeps_published_memory_and_is_idempotent(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    try:
        project = bench.create_project("p7-memory")
        mem_id = await _published_memory(bench, project["id"], "Memory Owner")
        # Simulate an index-column drift (payload stays authoritative).
        async with bench.db_session() as session:
            await session.execute(
                update(MemoryRecordRow)
                .where(MemoryRecordRow.mem_id == mem_id)
                .values(status="pending")
            )
            await session.commit()

        async with bench.db_session() as session:
            first = await reconcile(session)
        assert first.grants_active == 0
        assert first.memory_orphans_fixed == 1
        async with bench.db_session() as session:
            rows = (
                await session.execute(select(MemoryRecordRow).where(MemoryRecordRow.mem_id == mem_id))
            ).scalars().all()
            assert [row.status for row in rows] == ["published"]
            assert [row.version for row in rows] == [1]
            assert rows[0].payload["status"] == "published"
            assert rows[0].payload["body"] == {"decision": "seats"}

        async with bench.db_session() as session:
            second = await reconcile(session)
        assert second.memory_orphans_fixed == 0
        assert second.grants_active == first.grants_active
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_concurrent_reconcile_fixes_once(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    try:
        project = bench.create_project("p7-concurrent")
        mem_id = await _published_memory(bench, project["id"], "Memory Owner")
        async with bench.db_session() as session:
            await session.execute(
                update(MemoryRecordRow)
                .where(MemoryRecordRow.mem_id == mem_id)
                .values(status="pending")
            )
            await session.commit()

        async def one() -> int:
            async with bench.db_session() as session:
                return (await reconcile(session)).memory_orphans_fixed

        first, second = await asyncio.gather(one(), one())
        assert first + second == 1
        async with bench.db_session() as session:
            rows = (
                await session.execute(select(MemoryRecordRow).where(MemoryRecordRow.mem_id == mem_id))
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].status == "published"
        async with bench.db_session() as session:
            assert (await reconcile(session)).memory_orphans_fixed == 0
    finally:
        await bench.close()