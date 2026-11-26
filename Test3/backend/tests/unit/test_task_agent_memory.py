"""Offline tests for task/role scoped memory (M subsystem).

Everything runs against a temporary data dir with a scripted provider; no
network, no real model and no git side effects are involved.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.api.routes_task_agent_memory import router
from app.bots.registry import BotRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.memory.task_context import (
    MAX_MANUAL_CHARS,
    TaskMemoryConflict,
    TaskMemoryForbidden,
    TaskMemoryNotFound,
    build_task_role_sections,
    canonical_task_card,
    context_hash_for_sections,
    delete_task_role_manual,
    freeze_role_meta,
    get_memory,
    read_task_role_memory,
    role_source,
    save_task_role_manual,
    task_role,
)
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.docs import TaskCard
from app.services import runtime as runtime_module
from app.services.runtime import Workbench
from app.settings import CONFIG_DIR, load_models, load_roles


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


def _task(run: SimpleNamespace, code: str, role: str) -> dict:
    card = _card(code, role)
    return {
        "id": f"{run.id}:{code}",
        "code": code,
        "state": "ready",
        "revision": 1,
        "card": card.model_dump(),
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
    project = bench.create_project("M-project")
    run = bench.create_run(project["id"], "idea")
    for code, role in (("T1", "coder"), ("T2", "coder"), ("T3", "tester")):
        run.tasks[code] = _task(run, code, role)
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


def _client(bench: Workbench) -> AsyncClient:
    app = FastAPI()
    app.state.workbench = bench
    app.include_router(router, prefix="/api")
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _conflict(exc_info, code: str) -> None:
    assert isinstance(exc_info.value, TaskMemoryConflict)
    assert exc_info.value.code == code


class _SnapshotWriteSwitch:
    """Fail the snapshot atomic write on demand, leaving everything else intact.

    ``_atomic_write`` is the single point where ``_persist_snapshot`` turns the
    serialized payload into ``snapshot.json``, so raising here reproduces a disk
    failure *after* the service has decided to commit but *before* the bytes hit
    the snapshot file.
    """

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


def _snapshot_path(env) -> Path:
    return env.tmp_path / "runs" / env.run.id / "snapshot.json"


def _disk_task(env, code: str = "T1") -> dict:
    payload = json.loads(_snapshot_path(env).read_text(encoding="utf-8"))
    return payload["tasks"][code]


# --- service: defaults and isolation ----------------------------------------


async def test_default_memory_is_empty_revision_zero(env) -> None:
    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert view["run_id"] == env.run.id
    assert view["project_id"] == env.project_id
    assert view["task_code"] == "T1"
    assert view["role"] == "coder"
    assert view["revision"] == 0
    assert view["manual_text"] == ""
    assert view["manual_updated_by"] is None
    assert view["manual_updated_at"] is None
    assert view["manual_section"] is None
    assert view["frozen"] is False
    assert view["frozen_context"] == {}
    assert view["effective"] == "current"
    assert view["role_snapshot"]["matcher_version"] == "task-role-v1"
    assert view["role_section"]["kind"] == "task_role"
    assert view["role_section"]["text"] == view["role_snapshot"]["text"]
    assert len(view["context_hash"]) == 64

    assert get_memory(env.run, "T1", "coder") == {
        "revision": 0,
        "manual_text": "",
        "manual_updated_by": None,
        "manual_updated_at": None,
        "frozen_context": {},
    }


async def test_task_and_role_are_isolated(env) -> None:
    saved = await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "only T1 coder")
    assert saved["revision"] == 1

    t2 = await read_task_role_memory(env.bench, env.member, env.run.id, "T2", "coder")
    t3 = await read_task_role_memory(env.bench, env.member, env.run.id, "T3", "tester")
    assert (t2["revision"], t2["manual_text"]) == (0, "")
    assert (t3["revision"], t3["manual_text"]) == (0, "")
    assert t2["role_snapshot"]["text"] != saved["role_snapshot"]["text"]

    t1 = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert (t1["revision"], t1["manual_text"]) == (1, "only T1 coder")

    with pytest.raises(TaskMemoryConflict) as t1_tester:
        await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "tester")
    _conflict(t1_tester, "role_mismatch")

    with pytest.raises(TaskMemoryConflict) as direct:
        get_memory(env.run, "T1", "tester")
    _conflict(direct, "role_mismatch")


async def test_unknown_run_or_task_is_not_found(env) -> None:
    with pytest.raises(TaskMemoryNotFound):
        await read_task_role_memory(env.bench, env.leader, "missing-run", "T1", "coder")
    with pytest.raises(TaskMemoryNotFound):
        await read_task_role_memory(env.bench, env.leader, env.run.id, "T9", "coder")
    with pytest.raises(TaskMemoryNotFound):
        task_role(env.run, "T9")
    assert freeze_role_meta(env.bench, env.run, "T9") == {}


# --- service: permissions ----------------------------------------------------


async def test_non_member_cannot_read(env) -> None:
    with pytest.raises(TaskMemoryForbidden):
        await read_task_role_memory(env.bench, env.outsider, env.run.id, "T1", "coder")
    view = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert view["revision"] == 0


async def test_non_leader_cannot_write(env) -> None:
    for actor in (env.member, env.outsider):
        with pytest.raises(TaskMemoryForbidden):
            await save_task_role_manual(env.bench, actor, env.run.id, "T1", "coder", 0, "nope")
        with pytest.raises(TaskMemoryForbidden):
            await delete_task_role_manual(env.bench, actor, env.run.id, "T1", "coder", 0)
    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (0, "")


# --- service: leader write and validation -----------------------------------


async def test_leader_write_success(env) -> None:
    view = await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "  keep this  ")
    assert view["revision"] == 1
    assert view["manual_text"] == "keep this"
    assert view["manual_updated_by"] == env.leader
    assert view["manual_updated_at"] is not None
    assert datetime.fromisoformat(view["manual_updated_at"]).tzinfo is not None
    assert view["manual_section"]["kind"] == "task_manual"
    assert view["manual_section"]["source_version"] == "1"
    assert view["manual_section"]["sha256"] == hashlib.sha256(b"keep this").hexdigest()
    assert view["role_section"]["sha256"] == hashlib.sha256(
        view["role_section"]["text"].encode("utf-8")
    ).hexdigest()
    assert view["role_section"]["source_version"] == "task-role-v1"
    source_kinds = [item["kind"] for item in view["role_snapshot"]["sources"]]
    assert source_kinds == ["task_card", "role_definition"]
    assert view["role_snapshot"]["sources"][0]["ref"] == "T1"
    assert view["role_snapshot"]["sources"][1]["ref"] == "coder"
    assert view["role_snapshot"]["sources"][1]["sha256"] == hashlib.sha256(
        (CONFIG_DIR / "roles.yaml").read_bytes()
    ).hexdigest()
    assert view["effective"] == "current"

    reread = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert reread["manual_text"] == "keep this"
    assert reread["context_hash"] == view["context_hash"]


async def test_manual_too_long_is_rejected(env) -> None:
    with pytest.raises(TaskMemoryConflict) as info:
        await save_task_role_manual(
            env.bench, env.leader, env.run.id, "T1", "coder", 0, "x" * (MAX_MANUAL_CHARS + 1)
        )
    _conflict(info, "manual_text_too_long")
    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (0, "")


async def test_secret_manual_is_rejected(env) -> None:
    with pytest.raises(TaskMemoryConflict) as info:
        await save_task_role_manual(
            env.bench, env.leader, env.run.id, "T1", "coder", 0, "use sk-abcdef123456 please"
        )
    _conflict(info, "secret_in_manual")
    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (0, "")


async def test_role_mismatch_on_write(env) -> None:
    with pytest.raises(TaskMemoryConflict) as info:
        await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "tester", 0, "text")
    _conflict(info, "role_mismatch")
    with pytest.raises(TaskMemoryConflict) as info:
        await delete_task_role_manual(env.bench, env.leader, env.run.id, "T1", "tester", 0)
    _conflict(info, "role_mismatch")


# --- service: CAS and delete -------------------------------------------------


async def test_cas_two_writers_one_success_one_conflict(env) -> None:
    results = await asyncio.gather(
        save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "first"),
        save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "second"),
        return_exceptions=True,
    )
    winners = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, TaskMemoryConflict)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "revision_conflict"

    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert view["revision"] == 1
    assert view["manual_text"] in {"first", "second"}

    with pytest.raises(TaskMemoryConflict) as stale:
        await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "late")
    _conflict(stale, "revision_conflict")

    # The single winner must also be the durable state and the next frozen attempt.
    winner_text = view["manual_text"]
    stored = _disk_task(env)["role_memory"]["coder"]
    assert (stored["revision"], stored["manual_text"]) == (1, winner_text)
    async with _client(env.bench) as client:
        response = await client.get(
            f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder",
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 1
        assert response.json()["manual_text"] == winner_text
    _context, meta = env.bench._build_task_context(env.run, "T1", _card("T1", "coder"))
    env.bench._begin_attempt(env.run, env.run.tasks["T1"], "T1", context_meta=meta)
    attempt = env.run.tasks["T1"]["attempt"]
    assert attempt["manual_revision"] == 1
    assert attempt["memory_context_hash"] == view["context_hash"]


async def test_delete_clears_manual_and_bumps_revision(env) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "to delete")
    view = await delete_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1)
    assert view["revision"] == 2
    assert view["manual_text"] == ""
    assert view["manual_updated_by"] is None
    assert view["manual_updated_at"] is None
    assert view["manual_section"] is None
    reread = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert (reread["revision"], reread["manual_text"]) == (2, "")

    with pytest.raises(TaskMemoryConflict) as stale:
        await delete_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1)
    _conflict(stale, "revision_conflict")


# --- service: failed snapshot commit must not drift memory -------------------


async def test_failed_save_keeps_memory_disk_and_revision(env, fail_snapshot_write) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "old text")
    task = env.run.tasks["T1"]
    before_task = copy.deepcopy(task)
    before_others = {
        code: copy.deepcopy(item) for code, item in env.run.tasks.items() if code != "T1"
    }
    before_disk = json.loads(_snapshot_path(env).read_text(encoding="utf-8"))
    assert before_disk["tasks"]["T1"]["role_memory"]["coder"]["manual_text"] == "old text"

    fail_snapshot_write.enabled = True
    with pytest.raises(OSError):
        await save_task_role_manual(
            env.bench, env.leader, env.run.id, "T1", "coder", 1, "failed text"
        )

    assert fail_snapshot_write.calls == 1
    # Canonical state is untouched: same object, same payload, other tasks too.
    assert env.run.tasks["T1"] is task
    assert task == before_task
    assert task["role_memory"]["coder"]["manual_text"] == "old text"
    assert task["role_memory"]["coder"]["revision"] == 1
    for code, expected in before_others.items():
        assert env.run.tasks[code] == expected

    view = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (1, "old text")

    # Nothing was written to disk either.
    assert json.loads(_snapshot_path(env).read_text(encoding="utf-8")) == before_disk

    async with _client(env.bench) as client:
        response = await client.get(
            f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder",
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 1
        assert response.json()["manual_text"] == "old text"

    # A later unrelated snapshot must not resurrect the failed text, not even
    # after a restart from the same data dir.
    fail_snapshot_write.enabled = False
    env.run.tasks["T2"]["prev_output"] = "unrelated write"
    env.bench._persist_snapshot(env.run)
    assert "failed text" not in _snapshot_path(env).read_text(encoding="utf-8")
    await env.bench.close()
    restored = _bench(env.tmp_path)
    try:
        restored_memory = restored.runs[env.run.id].tasks["T1"]["role_memory"]["coder"]
        assert (restored_memory["revision"], restored_memory["manual_text"]) == (1, "old text")
        restored_view = await read_task_role_memory(restored, env.leader, env.run.id, "T1", "coder")
        assert (restored_view["revision"], restored_view["manual_text"]) == (1, "old text")
    finally:
        await restored.close()


async def test_failed_delete_keeps_memory_disk_and_revision(env, fail_snapshot_write) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "keep me")
    task = env.run.tasks["T1"]
    frozen_meta = freeze_role_meta(env.bench, env.run, "T1")
    task["attempt"] = {"attempt_id": "A-before-delete", "status": "started", **frozen_meta}
    before_task = copy.deepcopy(task)
    before_disk = json.loads(_snapshot_path(env).read_text(encoding="utf-8"))

    fail_snapshot_write.enabled = True
    with pytest.raises(OSError):
        await delete_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1)

    assert fail_snapshot_write.calls == 1
    assert env.run.tasks["T1"] is task
    assert task == before_task
    assert task["role_memory"]["coder"]["manual_text"] == "keep me"
    assert task["role_memory"]["coder"]["revision"] == 1
    assert task["attempt"] == before_task["attempt"]
    assert json.loads(_snapshot_path(env).read_text(encoding="utf-8")) == before_disk

    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (1, "keep me")

    # Restored persistence: a delete clears only the current text; the frozen
    # attempt hash/source metadata survives untouched.
    fail_snapshot_write.enabled = False
    deleted = await delete_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1)
    assert deleted["revision"] == 2
    assert deleted["manual_text"] == ""
    assert deleted["manual_section"] is None
    assert deleted["frozen"] is True
    assert deleted["frozen_context"]["manual_revision"] == 1
    assert task["attempt"] == before_task["attempt"]

    stored = _disk_task(env)
    assert (stored["role_memory"]["coder"]["revision"], stored["role_memory"]["coder"]["manual_text"]) == (
        2,
        "",
    )
    assert stored["attempt"] == before_task["attempt"]


async def test_same_revision_retry_after_persist_failure_commits_once(env, fail_snapshot_write) -> None:
    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "base")
    task = env.run.tasks["T1"]
    baseline_memory = copy.deepcopy(task["role_memory"]["coder"])

    fail_snapshot_write.enabled = True
    with pytest.raises(OSError):
        await save_task_role_manual(
            env.bench, env.leader, env.run.id, "T1", "coder", 1, "will be lost"
        )
    assert task["role_memory"]["coder"] == baseline_memory
    stored = _disk_task(env)
    assert stored["role_memory"]["coder"]["manual_text"] == "base"
    assert stored["role_memory"]["coder"]["revision"] == 1

    # Restore persistence: the same expected revision now commits exactly once.
    fail_snapshot_write.enabled = False
    recovered = await save_task_role_manual(
        env.bench, env.leader, env.run.id, "T1", "coder", 1, "recovered"
    )
    assert (recovered["revision"], recovered["manual_text"]) == (2, "recovered")

    with pytest.raises(TaskMemoryConflict) as stale:
        await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 1, "stale")
    _conflict(stale, "revision_conflict")

    stored = _disk_task(env)
    assert (stored["role_memory"]["coder"]["revision"], stored["role_memory"]["coder"]["manual_text"]) == (
        2,
        "recovered",
    )
    view = await read_task_role_memory(env.bench, env.member, env.run.id, "T1", "coder")
    assert (view["revision"], view["manual_text"]) == (2, "recovered")
    assert "will be lost" not in _snapshot_path(env).read_text(encoding="utf-8")

    _context, meta = env.bench._build_task_context(env.run, "T1", _card("T1", "coder"))
    env.bench._begin_attempt(env.run, task, "T1", context_meta=meta)
    attempt = task["attempt"]
    assert attempt["manual_revision"] == 2
    assert attempt["memory_context_hash"] == recovered["context_hash"]


async def test_persist_snapshot_tasks_override_keeps_live_run_untouched(env) -> None:
    env.run.revision = 7
    before_tasks = copy.deepcopy(env.run.tasks)
    override = copy.deepcopy(env.run.tasks)
    override["T1"]["role_memory"] = {
        "coder": {
            "revision": 5,
            "manual_text": "staged only",
            "manual_updated_by": None,
            "manual_updated_at": None,
            "frozen_context": {},
        }
    }

    env.bench._persist_snapshot(env.run, tasks_override=override)

    assert env.run.tasks == before_tasks
    payload = json.loads(_snapshot_path(env).read_text(encoding="utf-8"))
    assert payload["revision"] == 7
    assert payload["tasks"]["T1"]["role_memory"]["coder"]["manual_text"] == "staged only"
    assert payload["tasks"]["T2"] == json.loads(json.dumps(env.run.tasks["T2"]))


# --- service: snapshot persistence and frozen attempts ----------------------


async def test_snapshot_persistence_and_frozen_attempt_context(env) -> None:
    meta = freeze_role_meta(env.bench, env.run, "T1")
    assert meta["role"] == "coder"
    assert meta["manual_revision"] == 0
    assert len(meta["context_hash"]) == 64

    task = env.run.tasks["T1"]
    task["attempt"] = {"attempt_id": "A-1", "status": "started", **meta}

    initial = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert initial["frozen"] is True
    assert initial["frozen_context"]["context_hash"] == meta["context_hash"]
    assert initial["effective"] == "current"

    saved = await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "changed")
    assert saved["revision"] == 1
    assert saved["frozen"] is True
    assert saved["frozen_context"]["context_hash"] == meta["context_hash"]
    assert saved["frozen_context"]["manual_revision"] == 0
    assert saved["effective"] == "next_attempt"

    env.bench._persist_snapshot(env.run)
    snapshot_path = env.tmp_path / "runs" / env.run.id / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stored = snapshot["tasks"]["T1"]
    assert stored["role_memory"]["coder"]["manual_text"] == "changed"
    assert stored["role_memory"]["coder"]["revision"] == 1
    assert stored["role_memory"]["coder"]["manual_updated_by"] == env.leader
    assert stored["attempt"]["context_hash"] == meta["context_hash"]
    assert stored["attempt"]["role"] == "coder"

    await env.bench.close()
    restored = _bench(env.tmp_path)
    try:
        restored_task = restored.runs[env.run.id].tasks["T1"]
        assert restored_task["role_memory"]["coder"]["manual_text"] == "changed"
        assert restored_task["attempt"]["context_hash"] == meta["context_hash"]
        view = await read_task_role_memory(restored, env.leader, env.run.id, "T1", "coder")
        assert view["revision"] == 1
        assert view["manual_text"] == "changed"
        assert view["frozen"] is True
        assert view["frozen_context"]["context_hash"] == meta["context_hash"]
        assert view["effective"] == "next_attempt"
    finally:
        await restored.close()


# --- service: deterministic role context / sections -------------------------


async def test_role_source_and_hash_are_deterministic(env) -> None:
    first = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    second = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert first["context_hash"] == second["context_hash"]
    assert first["role_section"] == second["role_section"]
    assert first["role_snapshot"] == second["role_snapshot"]

    card = env.run.tasks["T1"]["card"]
    reordered = dict(reversed(list(card.items())))
    assert canonical_task_card(reordered) == canonical_task_card(card)
    assert first["role_snapshot"]["sources"][0]["sha256"] == hashlib.sha256(
        canonical_task_card(card).encode("utf-8")
    ).hexdigest()

    source_a = role_source(env.run, "T1")
    source_b = role_source(env.run, "T1")
    assert source_a == source_b
    text = source_a["text"]
    assert "Task T1" in text
    assert "Desc for T1" in text
    assert "src/T1.py" in text
    assert "python -m pytest" in text
    assert "ok" in text
    assert env.leader not in text
    assert source_a["sources"][1]["sha256"] == hashlib.sha256(
        (CONFIG_DIR / "roles.yaml").read_bytes()
    ).hexdigest()


async def test_build_task_role_sections_order_and_no_mutation(env) -> None:
    before = copy.deepcopy(env.run.tasks["T1"])
    sections, meta = build_task_role_sections(env.bench, env.run, "T1")
    assert env.run.tasks["T1"] == before
    assert "role_memory" not in env.run.tasks["T1"]
    assert [section.kind for section in sections] == ["task_role"]
    assert set(meta) == {
        "role",
        "role_hash",
        "manual_revision",
        "context_hash",
        "memory_context_hash",
    }
    assert meta["memory_context_hash"] == meta["context_hash"]
    assert meta["role"] == "coder"
    assert meta["manual_revision"] == 0
    assert meta["role_hash"] == sections[0].sha256
    assert meta["context_hash"] == context_hash_for_sections(sections)

    view = await read_task_role_memory(env.bench, env.leader, env.run.id, "T1", "coder")
    assert meta["context_hash"] == view["context_hash"]
    assert sections[0].text == view["role_section"]["text"]

    await save_task_role_manual(env.bench, env.leader, env.run.id, "T1", "coder", 0, "manual body")
    sections, meta = build_task_role_sections(env.bench, env.run, "T1")
    assert [section.kind for section in sections] == ["task_role", "task_manual"]
    assert sections[1].text == "manual body"
    assert sections[1].source_version == "1"
    assert meta["manual_revision"] == 1
    assert meta["role_hash"] == sections[0].sha256
    assert meta["context_hash"] == context_hash_for_sections(sections)
    assert freeze_role_meta(env.bench, env.run, "T1") == meta
    after = copy.deepcopy(env.run.tasks["T1"])
    build_task_role_sections(env.bench, env.run, "T1")
    assert env.run.tasks["T1"] == after


# --- HTTP routes -------------------------------------------------------------


async def test_routes_require_header_and_map_permissions(env) -> None:
    base = f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder"
    async with _client(env.bench) as client:
        response = await client.get(base)
        assert response.status_code == 400
        assert response.json()["error_category"] == "validation_error"

        response = await client.get(base, headers={"X-Bot-Id": env.outsider})
        assert response.status_code == 403
        assert response.json()["error_category"] == "forbidden"

        response = await client.get(base, headers={"X-Bot-Id": env.leader})
        assert response.status_code == 200
        assert response.json()["revision"] == 0

        response = await client.get(
            "/api/runs/missing/tasks/T1/role-memory/coder", headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 404
        assert response.json()["error_category"] == "task_memory_not_found"

        response = await client.get(
            f"/api/runs/{env.run.id}/tasks/T1/role-memory/reviewer",
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 422
        assert response.json()["error_category"] == "validation_error"

        response = await client.put(
            base, json={"expected_revision": 0, "manual_text": "nope"}, headers={"X-Bot-Id": env.member}
        )
        assert response.status_code == 403

        response = await client.put(
            base, json={"expected_revision": 0, "manual_text": "hello"}, headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 200
        assert response.json()["manual_text"] == "hello"
        assert response.json()["revision"] == 1

        response = await client.put(
            base, json={"expected_revision": 0, "manual_text": "stale"}, headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 409
        assert response.json()["error_category"] == "revision_conflict"

        response = await client.put(
            f"/api/runs/{env.run.id}/tasks/T1/role-memory/tester",
            json={"expected_revision": 0, "manual_text": "wrong role"},
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 409
        assert response.json()["error_category"] == "role_mismatch"

        response = await client.put(
            base,
            json={"expected_revision": 1, "manual_text": "x" * (MAX_MANUAL_CHARS + 1)},
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 422
        assert response.json()["error_category"] == "validation_error"

        response = await client.put(
            base,
            json={"expected_revision": 1, "manual_text": "use sk-abcdef123456"},
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 422

        response = await client.delete(base, headers={"X-Bot-Id": env.leader})
        assert response.status_code == 422
        response = await client.delete(
            base, params={"expected_revision": "abc"}, headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 422
        response = await client.delete(
            base, params={"expected_revision": 1}, headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 2
        assert response.json()["manual_text"] == ""

        response = await client.get(base, headers={"X-Bot-Id": env.leader})
        assert response.status_code == 200
        assert response.json()["revision"] == 2

@pytest.mark.asyncio
async def test_replan_materialization_preserves_role_memory(env) -> None:
    await save_task_role_manual(
        env.bench, env.leader, env.run.id, "T1", "coder", 0, "durable note"
    )
    env.run.artifacts["plan"] = {"tasks": [_card("T1", "coder").model_dump()]}
    env.bench._materialize_tasks(env.run)
    memory = env.run.tasks["T1"]["role_memory"]["coder"]
    assert memory["manual_text"] == "durable note"
    assert memory["revision"] == 1


@pytest.mark.asyncio
async def test_oversize_role_text_is_clipped_not_dropped(env) -> None:
    card = _card("T4", "coder").model_dump()
    card["description"] = "x" * 3000
    env.run.tasks["T4"] = {
        "id": f"{env.run.id}:T4",
        "code": "T4",
        "state": "ready",
        "revision": 1,
        "card": card,
        "repair_rounds": 0,
        "signatures": [],
        "evidence": [],
        "paused": False,
        "locked_by": "",
        "tokens_used": 0,
        "prev_output": "",
        "review_issues": [],
    }
    sections, _meta = build_task_role_sections(env.bench, env.run, "T4")
    assert len(sections[0].text) <= 2000
    assert "已截断" in sections[0].text


@pytest.mark.asyncio
async def test_run_busy_fails_fast_without_waiting_for_execution(env) -> None:
    """M2: a memory write must not queue behind a running execution batch."""

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_run_lock() -> None:
        async with env.bench._run_locks.write_scope(env.run.id):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold_run_lock())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        before = copy.deepcopy(env.run.tasks["T1"])
        started = asyncio.get_running_loop().time()
        with pytest.raises(TaskMemoryConflict) as excinfo:
            await save_task_role_manual(
                env.bench, env.leader, env.run.id, "T1", "coder", 0, "blocked"
            )
        elapsed = asyncio.get_running_loop().time() - started
        _conflict(excinfo, "run_busy")
        assert elapsed < 2.0, "the write must fail fast, not wait for the batch"
        assert env.run.tasks["T1"] == before
    finally:
        release.set()
        await holder

    # The retry after the batch is accepted with the same expected revision.
    view = await save_task_role_manual(
        env.bench, env.leader, env.run.id, "T1", "coder", 0, "after busy"
    )
    assert (view["revision"], view["manual_text"]) == (1, "after busy")


@pytest.mark.asyncio
async def test_run_busy_returns_retryable_409(env) -> None:
    """M2: the HTTP layer exposes ``run_busy`` as a retryable 409."""

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_run_lock() -> None:
        async with env.bench._run_locks.write_scope(env.run.id):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold_run_lock())
    client = _client(env.bench)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        async with client:
            base = f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder"
            response = await client.put(
                base,
                json={"expected_revision": 0, "manual_text": "blocked"},
                headers={"X-Bot-Id": env.leader},
            )
            assert response.status_code == 409
            assert response.json()["error_category"] == "run_busy"
            read = await client.get(base, headers={"X-Bot-Id": env.leader})
            assert read.status_code == 200
            assert (read.json()["revision"], read.json()["manual_text"]) == (0, "")
    finally:
        release.set()
        await holder

    async with _client(env.bench) as client:
        base = f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder"
        response = await client.put(
            base,
            json={"expected_revision": 0, "manual_text": "after busy"},
            headers={"X-Bot-Id": env.leader},
        )
        assert response.status_code == 200, response.text
        assert (response.json()["revision"], response.json()["manual_text"]) == (1, "after busy")
