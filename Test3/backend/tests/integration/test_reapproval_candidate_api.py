"""F2: immutable candidate adoption via the real gate-resolve HTTP API."""

from __future__ import annotations

import asyncio
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
    project = bench.create_project("candidate")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["spec"] = {"features": [], "nonfunc": [], "scenarios": [], "chapters": []}
    run.artifacts["design"] = {"modules": [], "interfaces": [], "decisions": []}
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    for key, value in (
        ("SPEC", run.artifacts["spec"]),
        ("DESIGN", run.artifacts["design"]),
        ("PLAN", run.artifacts["plan"]),
    ):
        bench._record_approved_baseline(run, key, value)
    return run


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _candidate_gate(run):
    return next(
        gate
        for gate in reversed(run.gates)
        if gate["kind"] == "PLAN基线确认"
        and gate["status"] == "pending"
        and (gate.get("payload") or {}).get("candidate_id")
    )


@pytest.mark.asyncio
async def test_old_gate_adopts_bound_candidate_not_live_artifacts(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate_plan = {"tasks": [{"code": "CANDIDATE"}], "work_packages": []}
    bench._create_candidate(
        run, {"plan": candidate_plan}, ["PLAN"], source_kind="cr", mode="cr"
    )
    gate = _candidate_gate(run)
    # Live artifacts change after the candidate was frozen.
    run.artifacts["plan"] = {"tasks": [{"code": "LIVE"}], "work_packages": []}

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )

    assert res.status_code == 200, res.text
    assert run.artifacts["plan"] == candidate_plan
    assert run.artifacts["plan"] != {"tasks": [{"code": "LIVE"}], "work_packages": []}
    assert run.artifacts["workflow_adopted_candidates"][-1]["status"] == "adopted"


@pytest.mark.asyncio
async def test_candidate_resolve_requires_expected_revision(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    bench._create_candidate(run, {"plan": {"tasks": [], "work_packages": []}}, ["PLAN"], source_kind="cr")
    gate = _candidate_gate(run)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(f"/api/gates/{gate['id']}/resolve", json={"decision": "approve"})
    assert res.status_code == 400
    assert "expected_revision" in res.text
    assert gate["status"] == "pending"


@pytest.mark.asyncio
async def test_new_candidate_supersedes_old_gate(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    bench._create_candidate(run, {"plan": {"tasks": [{"code": "C1"}], "work_packages": []}}, ["PLAN"], source_kind="cr")
    old_gate = _candidate_gate(run)
    bench._create_candidate(run, {"plan": {"tasks": [{"code": "C2"}], "work_packages": []}}, ["PLAN"], source_kind="cr")
    new_gate = _candidate_gate(run)
    assert old_gate["status"] == "superseded"

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        stale = await client.post(
            f"/api/gates/{old_gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
        fresh = await client.post(
            f"/api/gates/{new_gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert stale.status_code == 409, stale.text
    assert fresh.status_code == 200, fresh.text
    assert run.artifacts["plan"]["tasks"][0]["code"] == "C2"


@pytest.mark.asyncio
async def test_spec_change_needs_explicit_acknowledgement(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    new_spec = {"features": [{"code": "F9"}], "nonfunc": [], "scenarios": [], "chapters": []}
    bench._create_candidate(run, {"spec": new_spec}, ["SPEC"], source_kind="cr")
    gate = _candidate_gate(run)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        denied = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
        allowed = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={
                "decision": "approve",
                "expected_revision": run.revision,
                "payload": {
                    "candidate": True,
                    "candidate_id": gate["payload"]["candidate_id"],
                    "candidate_hash": gate["payload"]["candidate_hash"],
                    "acknowledge_spec_change": True,
                    "reason": "human approved spec change",
                },
            },
        )
    assert denied.status_code == 400
    assert "spec_reapproval_required" in denied.text
    assert allowed.status_code == 200, allowed.text
    assert run.artifacts["spec"] == new_spec


@pytest.mark.asyncio
async def test_manual_pause_survives_adoption_and_resume_is_blocked(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    run.paused = True
    run.artifacts.pop("baseline_pause_owned", None)
    bench._create_candidate(run, {"plan": {"tasks": [], "work_packages": []}}, ["PLAN"], source_kind="cr")
    gate = _candidate_gate(run)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        blocked_resume = await client.post(f"/api/runs/{run.id}/resume")
        resolved = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert blocked_resume.status_code == 400
    assert "baseline_reapproval_required" in blocked_resume.text
    assert resolved.status_code == 200, resolved.text
    assert run.paused is True


@pytest.mark.asyncio
async def test_concurrent_adoption_has_one_winner(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    bench._create_candidate(run, {"plan": {"tasks": [], "work_packages": []}}, ["PLAN"], source_kind="cr")
    gate = _candidate_gate(run)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post(
                f"/api/gates/{gate['id']}/resolve",
                json={"decision": "approve", "expected_revision": run.revision},
            ),
            client.post(
                f"/api/gates/{gate['id']}/resolve",
                json={"decision": "approve", "expected_revision": run.revision},
            ),
        )
    assert sorted([first.status_code, second.status_code])[0] == 200
    assert sorted([first.status_code, second.status_code])[1] in {400, 409}