"""Offline unit tests for the task assignment overlay (A1).

The overlay lives on the run task (``task["assignment"]``), never on the PLAN
TaskCard and never inside the role-memory subject ``run_id + task_code + role``.
Everything runs against a temporary data dir with a scripted provider; no
network, no real model, no git side effects.

CAS source declaration (locked here on purpose): ``expected_revision`` is the
**task-level** ``task["revision"]`` — the same source the existing
``Workbench.control_task`` uses — while a successful write bumps both the task
revision and ``run.revision``.  Frontend and backend must use this one source.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.runtime import RoleRegistry
from app.bots.registry import BotRegistry
from app.errors import RevisionConflict
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.memory.task_context import get_memory, save_task_role_manual
from app.orchestrator.scheduler import select_tasks
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.docs import TaskCard, TaskGraph
from app.services.monitor import build_monitor_snapshot
from app.services.runtime import (
    AssignmentBotNotFound,
    AssignmentForbidden,
    AssignmentRunReadOnly,
    AssigneeNotMember,
    Workbench,
)
from app.settings import load_models, load_roles


def _bench(data_dir: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        data_dir,
    )


def _bot(name: str) -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref="dashscope",
        model="qwen-plus",
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
    )


def _card(code: str, role: str) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": f"Task {code}",
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": f"Desc for {code}",
            "write_set": [f"src/{code}.py"],
            "acceptance": [
                {"cmd": ["python", "-m", "pytest", "-q"], "pass_criteria": "ok", "from_criterion": "F1"}
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": role,
        }
    )


def _task(run, code: str, role: str) -> dict:
    return {
        "id": f"{run.id}:{code}",
        "code": code,
        "state": "ready",
        "revision": 1,
        "card": _card(code, role).model_dump(),
        "repair_rounds": 0,
        "signatures": [],
        "evidence": [],
        "paused": False,
        "locked_by": "",
        "tokens_used": 0,
        "prev_output": "",
        "review_issues": [],
    }


@pytest.fixture
async def env(tmp_path: Path):
    bench = _bench(tmp_path)
    project = bench.create_project("assignment-project")
    run = bench.create_run(project["id"], "idea")
    for code, role in (("T1", "coder"), ("T2", "tester")):
        run.tasks[code] = _task(run, code, role)
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T1", "coder"), _card("T2", "tester")]).model_dump()
    async with bench.db_session() as session:
        leader = await BotRegistry(session).create(_bot("Leader"))
        member = await BotRegistry(session).create(_bot("Member"))
        outsider = await BotRegistry(session).create(_bot("Outsider"))
        await session.commit()
    async with bench.db_session() as session:
        memberships = MembershipService(session, project_exists=lambda pid: pid == project["id"])
        await memberships.add(project["id"], MembershipCreate(bot_id=leader.bot_id, role_in_project="dev", is_leader=True))
        await memberships.add(project["id"], MembershipCreate(bot_id=member.bot_id, role_in_project="dev"))
        await session.commit()
    data = SimpleNamespace(
        bench=bench,
        tmp_path=tmp_path,
        project_id=project["id"],
        run=run,
        leader=leader.bot_id,
        member=member.bot_id,
        outsider=outsider.bot_id,
    )
    yield data
    await bench.close()


async def test_unassigned_task_has_no_overlay(env) -> None:
    assert env.run.tasks["T1"].get("assignment") is None


async def test_leader_assign_writes_overlay_and_bumps_revisions(env) -> None:
    run = env.run
    task = run.tasks["T1"]
    old_task_rev = int(task["revision"])
    old_run_rev = int(run.revision)
    old_card = copy.deepcopy(task["card"])

    updated = await env.bench.assign_task(run, "T1", env.member, old_task_rev, actor=env.leader)

    assignment = updated["assignment"]
    assert assignment["assignee_bot_id"] == env.member
    assert assignment["assigned_by_bot_id"] == env.leader
    assert assignment["assigned_at"]
    assert int(assignment["revision"]) == 1
    # CAS source is the task revision; both counters advance on success.
    assert int(updated["revision"]) == old_task_rev + 1
    assert int(run.revision) == old_run_rev + 1
    # The PLAN card and the memory subject are untouched.
    assert updated["card"] == old_card
    assert "role_memory" not in updated


async def test_assign_emits_task_assigned_event(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    event = run.events[-1]
    assert event["kind"] == "task.assigned"
    assert event["subject"] == "T1"
    payload = event["payload"]
    assert payload["assignee_bot_id"] == env.member
    assert payload["assignee_display_name"] == "Member"
    assert payload["assigned_by_bot_id"] == env.leader
    assert payload["previous_assignee_bot_id"] is None
    assert payload["role"] == "coder"


async def test_clear_assignment_emits_cleared(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    updated = await env.bench.assign_task(run, "T1", None, int(run.tasks["T1"]["revision"]), actor=env.leader)
    assert updated.get("assignment") is None
    event = run.events[-1]
    assert event["kind"] == "task.assignment_cleared"
    assert event["subject"] == "T1"
    assert event["payload"]["previous_assignee_bot_id"] == env.member
    assert event["payload"]["assigned_by_bot_id"] == env.leader
    assert event["payload"]["role"] == "coder"


async def test_reassign_increments_assignment_revision(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    updated = await env.bench.assign_task(run, "T1", env.leader, int(run.tasks["T1"]["revision"]), actor=env.leader)
    assert int(updated["assignment"]["revision"]) == 2
    assert run.events[-1]["payload"]["previous_assignee_bot_id"] == env.member


async def test_non_leader_and_outsider_cannot_assign(env) -> None:
    run = env.run
    for actor in (env.member, env.outsider):
        with pytest.raises(AssignmentForbidden):
            await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=actor)
    assert run.tasks["T1"].get("assignment") is None


async def test_unknown_actor_bot_is_not_found(env) -> None:
    with pytest.raises(AssignmentBotNotFound):
        await env.bench.assign_task(env.run, "T1", env.member, 1, actor="bot-missing")


async def test_assignee_must_be_an_active_member(env) -> None:
    run = env.run
    with pytest.raises(AssigneeNotMember):
        await env.bench.assign_task(run, "T1", env.outsider, int(run.tasks["T1"]["revision"]), actor=env.leader)
    with pytest.raises(AssigneeNotMember):
        await env.bench.assign_task(run, "T1", "bot-missing", int(run.tasks["T1"]["revision"]), actor=env.leader)
    # An archived member is no longer a valid assignee either.
    async with env.bench.db_session() as session:
        await BotRegistry(session).archive(env.member)
        await session.commit()
    with pytest.raises(AssigneeNotMember):
        await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    assert run.tasks["T1"].get("assignment") is None


async def test_stale_revision_conflict_keeps_old_assignment(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    before = copy.deepcopy(run.tasks["T1"]["assignment"])
    run_rev = int(run.revision)
    with pytest.raises(RevisionConflict):
        await env.bench.assign_task(run, "T1", env.leader, 0, actor=env.leader)
    assert run.tasks["T1"]["assignment"] == before
    assert int(run.revision) == run_rev


async def test_terminal_run_is_read_only(env) -> None:
    run = env.run
    for status in ("terminated", "done"):
        run.status = status
        with pytest.raises(AssignmentRunReadOnly):
            await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    assert run.tasks["T1"].get("assignment") is None


async def test_snapshot_roundtrip_preserves_assignment(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    env.bench._persist_snapshot(run)
    snapshot_path = env.tmp_path / "runs" / run.id / "snapshot.json"
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert data["tasks"]["T1"]["assignment"]["assignee_bot_id"] == env.member
    restored = env.bench._deserialize_run(data)
    assert restored.tasks["T1"]["assignment"] == run.tasks["T1"]["assignment"]


async def test_assignment_never_changes_role_memory_subject(env) -> None:
    run = env.run
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    # The leader can still write role memory keyed by (run, task, role).
    await save_task_role_manual(env.bench, env.leader, run.id, "T1", "coder", 0, "优先覆盖空输入")
    memory = get_memory(run, "T1", "coder")
    assert memory["revision"] == 1
    store = run.tasks["T1"].get("role_memory") or {}
    assert set(store.keys()) == {"coder"}
    assert env.member not in store
    assert "assignment" not in store
    # The overlay itself carries no memory payload.
    assert "role_memory" not in (run.tasks["T1"].get("assignment") or {})


async def test_scheduler_selection_ignores_assignment(env) -> None:
    run = env.run
    graph = TaskGraph.model_validate(run.artifacts["plan"])
    states = {code: task["state"] for code, task in run.tasks.items()}
    picked = select_tasks(graph, states)
    assert [card.code for card in picked] == ["T1", "T2"] or {card.code for card in picked} == {"T1", "T2"}
    # Assigning one task must not remove the other (unassigned) task from selection.
    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    states = {code: task["state"] for code, task in run.tasks.items()}
    picked = select_tasks(graph, states)
    assert {card.code for card in picked} == {"T1", "T2"}


async def test_monitor_rows_carry_assignee_summary(env) -> None:
    run = env.run
    rows = build_monitor_snapshot(run, None, None)["tasks"]
    assert all(row["assignee_bot_id"] is None for row in rows)
    assert all(row["assignee_display_name"] is None for row in rows)

    await env.bench.assign_task(run, "T1", env.member, int(run.tasks["T1"]["revision"]), actor=env.leader)
    names = await env.bench.member_display_names(env.project_id)
    rows = build_monitor_snapshot(run, None, None, assignee_names=names)["tasks"]
    by_code = {row["code"]: row for row in rows}
    assert by_code["T1"]["assignee_bot_id"] == env.member
    assert by_code["T1"]["assignee_display_name"] == "Member"
    assert by_code["T2"]["assignee_bot_id"] is None
    # Without a name map the row still reports the bot id, never a blank name.
    rows = build_monitor_snapshot(run, None, None)["tasks"]
    by_code = {row["code"]: row for row in rows}
    assert by_code["T1"]["assignee_display_name"] == env.member