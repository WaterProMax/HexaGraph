"""Card 4: planning / approval / schedule idempotency and durable bindings."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agents.runtime import RoleRegistry
from app.discussion import planning
from app.discussion.models import DecisionPackage, DiscussionBudget, DiscussionSession
from app.discussion.session_store import DiscussionSessionStore
from app.errors import ValidationFailed
from app.execution.baseline import canonical_artifact_bytes, hash_artifact
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import RunState, Workbench
from app.settings import load_models, load_roles


def _bench(tmp_path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])), RoleRegistry(load_roles()), tmp_path
    )


def _record(*, project_id: str = "P1", session_id: str = "S-1") -> DiscussionSession:
    return DiscussionSession(
        session_id=session_id,
        project_id=project_id,
        leader_bot_id="B1",
        participant_bot_ids=["B1"],
        status="approved",
        current_round=1,
        budget=DiscussionBudget(),
        requirement_snapshot_hash="h" * 64,
        requirement_text="需求",
        decision_package=DecisionPackage(
            decision_id="D-1",
            session_id=session_id,
            requirement_snapshot_hash="h" * 64,
            proposal_ids=[],
            dissent_items=[],
            hard_gate_summary={},
            body_md="# 需求",
            sha256="d" * 64,
        ),
    )


class _Doc:
    def model_dump(self) -> dict:
        return {}


def _stub_generate(monkeypatch) -> dict:
    calls = {"n": 0}

    async def fake_generate(bench, record, **_kwargs):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return SimpleNamespace(spec=_Doc(), design=_Doc(), plan=_Doc())

    monkeypatch.setattr(planning, "generate", fake_generate)
    return calls


async def _seed(bench: Workbench, record: DiscussionSession) -> None:
    async with bench.db_session() as session:
        await DiscussionSessionStore(session).create(record)
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_plan_creates_one_run(tmp_path, monkeypatch) -> None:
    calls = _stub_generate(monkeypatch)
    bench = _bench(tmp_path)
    record = _record()
    await _seed(bench, record)

    first, second = await asyncio.gather(
        planning.prepare_run(bench, record), planning.prepare_run(bench, record)
    )

    assert first == second == planning.run_id_for(record.session_id)
    assert calls["n"] == 1
    assert list(bench.runs) == [first]


@pytest.mark.asyncio
async def test_restart_reuses_persisted_plan_run(tmp_path, monkeypatch) -> None:
    calls = _stub_generate(monkeypatch)
    bench = _bench(tmp_path)
    record = _record()
    await _seed(bench, record)
    run_id = await planning.prepare_run(bench, record)
    await bench.close()

    restored = _bench(tmp_path)
    again = await planning.prepare_run(restored, record)

    assert again == run_id
    assert calls["n"] == 1
    assert run_id in restored.runs
    assert restored.runs[run_id].artifacts["discussion_session_id"] == record.session_id


@pytest.mark.asyncio
async def test_existing_run_for_another_project_is_rejected(tmp_path, monkeypatch) -> None:
    _stub_generate(monkeypatch)
    bench = _bench(tmp_path)
    record = _record(project_id="P1")
    await _seed(bench, record)
    bench.runs[planning.run_id_for(record.session_id)] = RunState(
        id=planning.run_id_for(record.session_id), project_id="P2", idea="other"
    )

    with pytest.raises(ValidationFailed):
        await planning.prepare_run(bench, record)


@pytest.mark.asyncio
async def test_plan_approval_records_actor_and_bindings(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = bench.create_run("P1", "idea")
    run.artifacts["discussion_session_id"] = "S-1"
    run.artifacts["design"] = {}
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.engine.current = "6"
    gate = {"id": "G-P", "kind": "PLAN基线确认", "status": "pending", "payload": {}}
    run.gates.append(gate)

    await bench.resolve_gate(run, "G-P", "approve", {}, actor="leader-bot")

    assert gate["resolved_by"] == "leader-bot"
    assert gate["resolved_at"]
    approval = run.artifacts["approvals"][-1]
    assert approval["kind"] == "PLAN基线确认"
    assert approval["actor"] == "leader-bot"
    assert approval["project_id"] == "P1"
    assert approval["run_id"] == run.id
    assert approval["session_id"] == "S-1"
    assert approval["approved_baseline_hashes"]["PLAN"] == hash_artifact(run.artifacts["plan"])


@pytest.mark.asyncio
async def test_concurrent_gate_resolve_advances_once(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = bench.create_run("P1", "idea")
    run.artifacts["design"] = {}
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.engine.current = "6"
    run.gates.append({"id": "G-P", "kind": "PLAN基线确认", "status": "pending", "payload": {}})

    results = await asyncio.gather(
        bench.resolve_gate(run, "G-P", "approve", {}, actor="a"),
        bench.resolve_gate(run, "G-P", "approve", {}, actor="b"),
        return_exceptions=True,
    )

    assert sum(1 for item in results if isinstance(item, ValidationFailed)) == 1
    assert len(run.artifacts["approvals"]) == 1


@pytest.mark.asyncio
async def test_concurrent_schedule_dispatches_once(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = bench.create_run("P1", "idea")
    run.artifacts["plan"] = {
        "tasks": [
            {
                "code": "T-01",
                "title": "t",
                "kind": "impl",
                "module": "M1",
                "sources": ["F1"],
                "description": "d",
                "write_set": ["a.py"],
                "outputs": ["a.py"],
                "acceptance": [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": "F1"}],
                "depends_on": [],
                "points": 1,
                "priority": "P0",
                "role": "coder",
                "budget": {},
            }
        ],
        "work_packages": [],
    }
    bench._materialize_tasks(run)
    calls = {"n": 0}

    async def fake_execute(run_state, code):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        run_state.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)

    await asyncio.gather(bench.schedule_once(run), bench.schedule_once(run))

    assert calls["n"] == 1


def test_baseline_hash_is_stable_and_canonical() -> None:
    left = {"b": 1, "a": [1, 2, {"y": True, "x": None}]}
    right = {"a": [1, 2, {"x": None, "y": True}], "b": 1}
    assert hash_artifact(left) == hash_artifact(left)
    assert hash_artifact(left) == hash_artifact(right)
    assert canonical_artifact_bytes(left) == canonical_artifact_bytes(right)
    assert json.loads(canonical_artifact_bytes(left)) == left