"""P7-T01: the new domains write SQLite only; legacy JSONL keeps working.

Creating a Bot (and the other P2–P5 domains) must not append a JSONL line with
that bot_id as a payload/kind.  Appending one legacy run event must still add
exactly one line, proving the legacy writer was not frozen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.bots.registry import BotRegistry
from app.discussion.models import DiscussionBudget
from app.leader.steward import DiscussionSteward
from app.memory.store import MemoryStore
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.memory import MemoryCreate, MemorySource
from app.schemas.skill_definition import SkillCreate
from app.skills.registry import SkillRegistry
from tests.p1_support import install_plan, make_bench, make_grant, persist_granted_profile


def _jsonl_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/*.jsonl"))


def _line_count(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        total += len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    return total


@pytest.mark.asyncio
async def test_new_domain_creation_adds_no_jsonl_lines(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    try:
        project = bench.create_project("p7-jsonl")
        run = bench.create_run(project["id"], "idea")
        install_plan(bench, run, ["T-01"])
        await persist_granted_profile(bench, run, {"PLAN": "aaa"})
        files_before = _jsonl_files(tmp_path)
        lines_before = _line_count(files_before)

        async with bench.db_session() as session:
            bot = await BotRegistry(session).create(
                BotCreate(
                    display_name="JSONL Probe",
                    role_template="coder",
                    provider_ref="dashscope",
                    model="qwen-max",
                    slot="coder",
                    secret_ref="DASHSCOPE_API_KEY",
                )
            )
            await SkillRegistry(session).create(
                SkillCreate(
                    skill_id="review",
                    version="1.0.0",
                    description_md="read-only review",
                    allowed_tool_refs=["git_read"],
                )
            )
            await session.commit()
        async with bench.db_session() as session:
            await MembershipService(session, project_exists=lambda pid: pid in bench.projects).add(
                project["id"],
                MembershipCreate(bot_id=bot.bot_id, role_in_project="dev", is_leader=True),
            )
            await session.commit()
        await bench.add_grant(make_grant(run.id, ["T-01"]))
        async with bench.db_session() as session:
            await MemoryStore(session).create(
                MemoryCreate(
                    owner_bot_id=bot.bot_id,
                    project_id=project["id"],
                    visibility="project",
                    sources=[MemorySource(kind="doc", ref="req.md", sha="c" * 64)],
                    body={"t": 1},
                    title="jsonl probe",
                )
            )
            await session.commit()
        async with bench.db_session() as session:
            await DiscussionSteward(
                session, project_exists=lambda pid: pid in bench.projects
            ).create_session(project["id"], bot.bot_id, [bot.bot_id], "req", DiscussionBudget())

        files_after = _jsonl_files(tmp_path)
        assert _line_count(files_after) == lines_before

        blob = "\n".join(path.read_text(encoding="utf-8") for path in files_after)
        assert bot.bot_id not in blob
        for path in files_after:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                assert row.get("kind") != "bot.created"
                assert "bot_id" not in (row.get("payload") or {})
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_legacy_event_still_appends_one_jsonl_line(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    try:
        project = bench.create_project("p7-legacy")
        run = bench.create_run(project["id"], "idea")
        events_file = tmp_path / "runs" / run.id / "events.jsonl"
        before = len(events_file.read_text(encoding="utf-8").splitlines())

        bench.emit(run, "task.note", "T-01", {"note": "legacy writer alive"})

        after_lines = events_file.read_text(encoding="utf-8").splitlines()
        assert len(after_lines) == before + 1
        last = json.loads(after_lines[-1])
        assert last["kind"] == "task.note"
        assert last["subject"] == "T-01"
    finally:
        await bench.close()