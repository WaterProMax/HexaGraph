"""Integration tests for task context assembly and injection (I subsystem).

These are offline: scripted provider, temporary data dir, no git worktree and no
network. They verify that the legacy tool-agent path receives the task/role
memory and selected shared skill as a guarded data block, while the context hash
is frozen onto the attempt.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry, run_tool_agent
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.memory.task_context import (
    build_task_role_sections,
    read_task_role_memory,
    save_task_role_manual,
)
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.docs import TaskCard
from app.services import runtime as runtime_module
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


class _CaptureGateway:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    async def complete(self, slot, messages, **kwargs):
        self.messages.append([dict(item) for item in messages])
        return SimpleNamespace(tool_calls=[], parsed=None, text="done", finish_reason="stop")


def _card(code: str, role: str = "coder") -> TaskCard:
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


def _task(run, code: str, role: str = "coder") -> dict:
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
async def env(tmp_path: Path, monkeypatch):
    bench = Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    project = bench.create_project("I-project")
    run = bench.create_run(project["id"], "idea")
    run.tasks["T1"] = _task(run, "T1")
    run.tasks["T2"] = _task(run, "T2")
    from app.bots.registry import BotRegistry

    async with bench.db_session() as session:
        leader = await BotRegistry(session).create(
            BotCreate(
                display_name="Leader",
                role_template="developer",
                provider_ref="dashscope",
                model="qwen-plus",
                slot="coder",
                secret_ref="DASHSCOPE_API_KEY",
            )
        )
        await session.commit()
    async with bench.db_session() as session:
        await MembershipService(session, project_exists=lambda pid: pid == project["id"]).add(
            project["id"],
            MembershipCreate(bot_id=leader.bot_id, role_in_project="dev", is_leader=True),
        )
        await session.commit()

    monkeypatch.setattr(
        runtime_module,
        "SHARED_SKILLS_PATH",
        Path(__file__).resolve().parents[1] / "fixtures" / "shared_skills_valid.md",
    )
    yield SimpleNamespace(bench=bench, run=run, leader=leader.bot_id)
    await bench.close()


@pytest.mark.asyncio
async def test_build_task_context_selects_role_manual_and_shared(env) -> None:
    await save_task_role_manual(
        env.bench,
        env.leader,
        env.run.id,
        "T1",
        "coder",
        0,
        "manual body for T1",
    )
    snapshot, meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    kinds = {section.kind for section in snapshot.sections}
    assert kinds == {"task_role", "task_manual", "shared_skill"}
    assert meta["role"] == "coder"
    assert meta["manual_revision"] == 1
    assert meta["context_hash"] == snapshot.context_hash
    assert meta["skill_bundle_hash"]

    other, other_meta = env.bench._build_task_context(env.run, "T2", _card("T2"))
    assert all("manual body for T1" not in section.text for section in other.sections)
    assert other_meta["context_hash"] != meta["context_hash"]


@pytest.mark.asyncio
async def test_context_hash_is_frozen_on_attempt_and_skips_later_edits(env) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "first")
    snapshot, meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    task = env.run.tasks["T1"]
    env.bench._begin_attempt(env.run, task, "T1", context_meta=meta)
    frozen = task["attempt"]["context_hash"]
    assert frozen == snapshot.context_hash
    assert task["attempt"]["role"] == "coder"
    assert task["attempt"]["manual_revision"] == 1

    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1, "second")
    assert task["attempt"]["context_hash"] == frozen


@pytest.mark.asyncio
async def test_run_tool_agent_receives_guarded_context_block(env) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "manual marker")
    snapshot, _meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    gateway = _CaptureGateway()
    toolset = SimpleNamespace(specs=None, execute=lambda *a, **k: {"ok": True})
    await run_tool_agent(
        "coder",
        {"task_card": _card("T1").model_dump()},
        toolset,
        registry=env.bench.registry,
        gateway=gateway,
        context_block=snapshot.render(),
    )
    assert gateway.messages
    user_text = gateway.messages[0][-1]["content"]
    assert "manual marker" in user_text
    assert "task_context" in user_text
    assert "不是指令" in user_text
    payload = user_text.split('<资料 name="task_context">', 1)[1].split("</资料>", 1)[0]
    sections = json.loads(payload)
    assert {item["kind"] for item in sections} == {"task_role", "task_manual", "shared_skill"}


@pytest.mark.asyncio
async def test_sections_are_read_only(env) -> None:
    before = json.dumps(env.run.tasks["T1"], ensure_ascii=False, sort_keys=True)
    sections, _meta = build_task_role_sections(env.bench, env.run, "T1")
    assert sections
    after = json.dumps(env.run.tasks["T1"], ensure_ascii=False, sort_keys=True)
    assert before == after

@pytest.mark.asyncio
async def test_real_freeze_reports_current_effective(env) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "first")
    _snapshot, meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    env.bench._begin_attempt(env.run, env.run.tasks["T1"], "T1", context_meta=meta)
    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert view["frozen"] is True
    assert view["effective"] == "current"
    assert view["frozen_context"]["memory_context_hash"] == meta["memory_context_hash"]
    assert view["frozen_context"]["context_hash"] == meta["context_hash"]


@pytest.mark.asyncio
async def test_raw_task_endpoints_do_not_leak_role_memory(env) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "leak marker")
    app = create_app()
    app.state.workbench = env.bench
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        listed = await client.get(f"/api/runs/{env.run.id}/tasks")
        assert listed.status_code == 200
        assert all("role_memory" not in task for task in listed.json())
        assert "leak marker" not in listed.text

        detail = await client.get("/api/tasks/T1")
        assert detail.status_code == 200
        assert "role_memory" not in detail.json()
        assert "leak marker" not in detail.text


# --- failed memory write must not leak into the next attempt -----------------


class _SnapshotWriteSwitch:
    """Raise on the snapshot atomic write until explicitly re-enabled."""

    def __init__(self) -> None:
        self.enabled = False
        self.calls = 0
        self.original = runtime_module._atomic_write

    def __call__(self, path: Path, text: str) -> None:
        if self.enabled and Path(path).name == "snapshot.json":
            self.calls += 1
            raise OSError("injected snapshot write failure")
        self.original(path, text)


@pytest.fixture
def fail_snapshot_write(monkeypatch) -> _SnapshotWriteSwitch:
    switch = _SnapshotWriteSwitch()
    monkeypatch.setattr(runtime_module, "_atomic_write", switch)
    return switch


@pytest.mark.asyncio
async def test_failed_memory_write_does_not_change_next_attempt(env, fail_snapshot_write) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "old manual")
    task = env.run.tasks["T1"]
    baseline_sections, baseline_meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    assert baseline_meta["manual_revision"] == 1

    fail_snapshot_write.enabled = True
    with pytest.raises(OSError):
        await save_task_role_manual(
            env.bench, env.leader, env.run.id, "T1", "coder", 1, "never frozen"
        )

    assert fail_snapshot_write.calls == 1
    assert task["role_memory"]["coder"]["manual_text"] == "old manual"
    assert task["role_memory"]["coder"]["revision"] == 1

    # Restore persistence: the assembler and the frozen attempt must still see
    # the old manual text/revision/hash, never the failed write.
    fail_snapshot_write.enabled = False
    snapshot, meta = env.bench._build_task_context(env.run, "T1", _card("T1"))
    assert meta["manual_revision"] == 1
    assert meta["context_hash"] == baseline_meta["context_hash"]
    assert meta["memory_context_hash"] == baseline_meta["memory_context_hash"]
    assert any(section.text == "old manual" for section in snapshot.sections)
    assert all("never frozen" not in section.text for section in snapshot.sections)

    env.bench._begin_attempt(env.run, task, "T1", context_meta=meta)
    attempt = task["attempt"]
    assert attempt["manual_revision"] == 1
    assert attempt["context_hash"] == baseline_meta["context_hash"]
    assert attempt["memory_context_hash"] == baseline_meta["memory_context_hash"]

    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (1, "old manual")
    assert view["frozen"] is True
    assert view["effective"] == "current"

    # An unrelated later snapshot only confirms the old frozen metadata.
    env.bench._persist_snapshot(env.run)
    assert task["attempt"] == attempt
    restored_task = env.bench.runs[env.run.id].tasks["T1"]
    assert restored_task["attempt"]["manual_revision"] == 1
    assert restored_task["attempt"]["context_hash"] == baseline_meta["context_hash"]
