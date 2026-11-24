"""Card A: candidate reapproval gates reject without rewriting active plans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def _run(bench: Workbench):
    project = bench.create_project("candidate-reject")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    run.artifacts["spec"] = {"features": [], "nonfunc": [], "scenarios": [], "chapters": []}
    run.artifacts["design"] = {"modules": [], "interfaces": [], "decisions": []}
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    for key in ("SPEC", "DESIGN", "PLAN"):
        bench._record_approved_baseline(run, key, run.artifacts[key.lower()])
    return run


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _candidate_gate(run, candidate_id: str):
    return next(
        gate
        for gate in run.gates
        if (gate.get("payload") or {}).get("candidate_id") == candidate_id
    )


def _candidate(bench: Workbench, run, code: str = "C1") -> dict:
    return bench._create_candidate(
        run,
        {"plan": {"tasks": [{"code": code}], "work_packages": []}},
        ["PLAN"],
        source_kind="cr",
        mode="cr",
    )


def _active_snapshot(run) -> str:
    return json.dumps(
        {
            "spec": run.artifacts.get("spec"),
            "design": run.artifacts.get("design"),
            "plan": run.artifacts.get("plan"),
            "hashes": run.artifacts.get("approved_baseline_hashes") or run.approved_baseline_hashes,
            "baseline_spec": run.artifacts.get("baseline_SPEC"),
            "baseline_design": run.artifacts.get("baseline_DESIGN"),
            "baseline_plan": run.artifacts.get("baseline_PLAN"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


@pytest.mark.asyncio
async def test_candidate_rejection_never_calls_run_plan(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _candidate_gate(run, candidate["candidate_id"])
    before = _active_snapshot(run)
    calls: list[str] = []

    async def spy_plan(_run):
        calls.append("run_plan")
        return {"status": "should-not-run"}

    monkeypatch.setattr(bench, "run_plan", spy_plan)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={
                "decision": "reject",
                "expected_revision": run.revision,
                "payload": {"reason": "candidate not acceptable"},
            },
        )

    assert res.status_code == 200, res.text
    assert calls == []
    assert gate["status"] == "rejected"
    assert candidate["status"] == "rejected"
    assert _active_snapshot(run) == before
    assert "plan_rewrite" not in run.artifacts


@pytest.mark.asyncio
async def test_candidate_rejection_survives_restart(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _candidate_gate(run, candidate["candidate_id"])
    before = _active_snapshot(run)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": run.revision, "payload": {"reason": "no"}},
        )
    assert res.status_code == 200, res.text
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    saved_gate = _candidate_gate(saved, candidate["candidate_id"])
    saved_candidate = saved.artifacts["workflow_candidates"][candidate["candidate_id"]]
    assert saved_gate["status"] == "rejected"
    assert saved_candidate["status"] == "rejected"
    assert _active_snapshot(saved) == before
    assert "plan_rewrite" not in saved.artifacts


@pytest.mark.asyncio
async def test_superseded_gate_cannot_reject_new_candidate(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    old = _candidate(bench, run, "OLD")
    old_gate = _candidate_gate(run, old["candidate_id"])
    new = _candidate(bench, run, "NEW")
    new_gate = _candidate_gate(run, new["candidate_id"])
    new_docs = json.dumps(new["documents"], sort_keys=True)
    assert old_gate["status"] == "superseded"

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        stale = await client.post(
            f"/api/gates/{old_gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": run.revision, "payload": {"reason": "old"}},
        )
    assert stale.status_code == 409, stale.text
    assert old["status"] == "superseded"
    assert new_gate["status"] == "pending"
    assert new["status"] == "pending"
    assert json.dumps(new["documents"], sort_keys=True) == new_docs


@pytest.mark.asyncio
async def test_candidate_rejection_keeps_manual_pause_and_clears_only_baseline_block(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    run.paused = True
    run.artifacts.pop("baseline_pause_owned", None)
    candidate = _candidate(bench, run)
    gate = _candidate_gate(run, candidate["candidate_id"])

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": run.revision, "payload": {"reason": "manual"}},
        )
        assert res.status_code == 200, res.text
        assert run.paused is True
        resumed = await client.post(f"/api/runs/{run.id}/resume")
    assert run.paused is False
    assert run.artifacts.get("workflow_blocks") == []
    assert resumed.status_code == 200, resumed.text


@pytest.mark.asyncio
async def test_rejecting_last_candidate_allows_a_new_one_and_resume(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    first = _candidate(bench, run, "FIRST")
    first_gate = _candidate_gate(run, first["candidate_id"])
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        rejected = await client.post(
            f"/api/gates/{first_gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": run.revision, "payload": {"reason": "retry"}},
        )
        assert rejected.status_code == 200, rejected.text
        assert "baseline_reapproval_required" not in (run.artifacts.get("workflow_blocks") or [])
        resumed = await client.post(f"/api/runs/{run.id}/resume")
        assert resumed.status_code == 200, resumed.text

        second = _candidate(bench, run, "SECOND")
        second_gate = _candidate_gate(run, second["candidate_id"])
        adopted = await client.post(
            f"/api/gates/{second_gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert adopted.status_code == 200, adopted.text
    assert run.artifacts["plan"]["tasks"][0]["code"] == "SECOND"


@pytest.mark.asyncio
async def test_candidate_rejection_requires_fresh_cas(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _candidate_gate(run, candidate["candidate_id"])
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        missing = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "payload": {"reason": "no revision"}},
        )
        stale = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": 999, "payload": {"reason": "stale"}},
        )
    assert missing.status_code == 400
    assert "expected_revision" in missing.text
    assert stale.status_code == 409
    assert gate["status"] == "pending"
    assert candidate["status"] == "pending"


@pytest.mark.asyncio
async def test_candidate_parent_baseline_drift_blocks_rejection(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _candidate_gate(run, candidate["candidate_id"])
    # A concurrent approval/baseline write moved the parent hashes after the
    # candidate was frozen.
    run.approved_baseline_hashes["PLAN"] = "0" * 64
    run.artifacts["approved_baseline_hashes"] = dict(run.approved_baseline_hashes)

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "expected_revision": run.revision, "payload": {"reason": "no"}},
        )
    assert res.status_code == 409, res.text
    assert "candidate_baseline_mismatch" in res.text
    assert gate["status"] == "pending"
    assert candidate["status"] == "pending"


@pytest.mark.asyncio
async def test_normal_plan_rejection_still_rewrites_plan(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    gate = bench._gate(run, "PLAN基线确认", {})["gate"]
    calls: list[str] = []

    async def fake_plan(_run):
        calls.append("run_plan")
        return {"status": "replanning"}

    monkeypatch.setattr(bench, "run_plan", fake_plan)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "reject", "payload": {"reason": "plan not acceptable"}},
        )
    assert res.status_code == 200, res.text
    assert calls == ["run_plan"]
    assert gate["status"] == "rejected"
    assert run.artifacts["plan_rewrite"]["reason"] == "plan not acceptable"