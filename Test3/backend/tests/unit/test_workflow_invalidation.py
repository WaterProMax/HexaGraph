"""Card 5: approved-baseline changes invalidate grants, pause execution, keep history."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import GrantRejected
from app.execution.baseline import hash_artifact
from app.execution.run_profile import run_approved_baseline_hashes
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.execution_grant import ExecutionGrant
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workflow.invalidation import baseline_drift, baseline_provenance
from app.workflow.projection import project_workflow_projection
from tests.p1_support import install_plan, make_grant


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])), RoleRegistry(load_roles()), tmp_path
    )


async def _prepared(tmp_path: Path, monkeypatch) -> tuple[Workbench, object]:
    bench = _bench(tmp_path)
    bench.execution_safety_ready = True
    project = bench.create_project("invalidation")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    install_plan(bench, run, ["T-01"])
    hashes = {"PLAN": hash_artifact(run.artifacts["plan"])}
    run.artifacts["approvals"] = [{"kind": "PLAN基线确认", "actor": "leader"}]
    await bench.persist_run_execution_state(run.id, "granted_v1", hashes)
    run.artifacts["baseline_provenance"] = "approved"
    await bench.add_grant(make_grant(run.id, ["T-01"], hashes=hashes))

    async def boom(*_args, **_kwargs):
        raise AssertionError("drifted baseline must not execute")

    monkeypatch.setattr(bench, "execute_task", boom)
    return bench, run


def test_baseline_drift_is_keyed_and_empty_when_matching(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("drift")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.artifacts["approvals"] = [{"kind": "PLAN基线确认"}]
    run.approved_baseline_hashes = {"PLAN": hash_artifact(run.artifacts["plan"])}
    assert baseline_drift(run) == []
    run.artifacts["plan"]["tasks"].append({"code": "X"})
    assert baseline_drift(run) == ["PLAN"]


@pytest.mark.asyncio
async def test_plan_change_pauses_run_and_marks_grant_stale(tmp_path, monkeypatch) -> None:
    bench, run = await _prepared(tmp_path, monkeypatch)
    run.artifacts["plan"]["tasks"][0]["title"] = "人工直接改动"

    with pytest.raises(GrantRejected) as exc:
        await bench.schedule_once(run)

    assert exc.value.category == "baseline_stale"
    assert run.paused is True
    records = run.artifacts["workflow_invalidations"]
    assert records[-1]["keys"] == ["PLAN"]
    assert records[-1]["reason"]
    grants = await bench.grants_for_run(run.id)
    assert grants and all(grant.status == "stale" for grant in grants)
    assert project_workflow_projection(run=run).stage == "invalidated"


@pytest.mark.asyncio
async def test_reapproval_allows_new_grant_but_never_revives_old_one(tmp_path, monkeypatch) -> None:
    bench, run = await _prepared(tmp_path, monkeypatch)
    run.artifacts["plan"]["tasks"][0]["title"] = "人工直接改动"
    with pytest.raises(GrantRejected):
        await bench.schedule_once(run)

    gate = next(
        item
        for item in reversed(run.gates)
        if item["kind"] == "PLAN基线确认" and item["status"] == "pending"
    )
    assert gate["payload"].get("candidate") is True
    await bench.resolve_gate(run, gate["id"], "approve", {}, actor="leader")
    assert baseline_drift(run) == []
    assert run.paused is False
    assert "workflow_candidate" not in run.artifacts
    assert run.artifacts["workflow_adopted_candidates"]
    new_hashes = run_approved_baseline_hashes(run)
    old_grants = await bench.grants_for_run(run.id)
    assert all(grant.status == "stale" for grant in old_grants)

    fresh = ExecutionGrant(
        grant_id="G-fresh",
        run_id=run.id,
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes=dict(new_hashes),
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/reverify",
        allowed_tool_refs=[],
        created_at="2026-11-24T00:00:00+00:00",
    )
    await bench.add_grant(fresh)

    async def fake_execute(run_state, code):
        run_state.tasks[code]["state"] = "done"
        return {"state": "done"}

    monkeypatch.setattr(bench, "execute_task", fake_execute)
    started = await bench.schedule_once(run, task_codes={"T-01"})

    assert started == ["T-01"]
    # Invalidation history is append-only; re-approval does not erase it.
    assert len(run.artifacts["workflow_invalidations"]) == 1
    statuses = {grant.grant_id: grant.status for grant in await bench.grants_for_run(run.id)}
    assert statuses["G-fresh"] == "active"
    assert all(status == "stale" for gid, status in statuses.items() if gid != "G-fresh")


@pytest.mark.asyncio
async def test_concurrent_schedule_after_drift_still_rejects(tmp_path, monkeypatch) -> None:
    bench, run = await _prepared(tmp_path, monkeypatch)
    run.artifacts["plan"]["tasks"][0]["title"] = "changed"
    results = await asyncio.gather(bench.schedule_once(run), bench.schedule_once(run), return_exceptions=True)
    assert all(isinstance(item, GrantRejected) for item in results)
    assert len(run.artifacts["workflow_invalidations"]) == 1

def test_historical_hash_with_resolved_gate_is_checked(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("historical")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    install_plan(bench, run, ["T-01"])
    plan = run.artifacts["plan"]
    run.approved_baseline_hashes = {"PLAN": hash_artifact(plan)}
    run.artifacts["approved_baseline_hashes"] = dict(run.approved_baseline_hashes)
    # Upgrade-era run: resolved gate, no artifacts.approvals array.
    run.gates.append({"id": "G-old", "kind": "PLAN基线确认", "status": "approved", "payload": {}})
    assert baseline_provenance(run) == "approved"
    assert baseline_drift(run) == []
    plan["tasks"][0]["title"] = "changed"
    assert baseline_drift(run) == ["PLAN"]


def test_hash_only_without_provenance_is_not_trusted(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("unverifiable")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.execution_profile = "granted_v1"
    run.artifacts["execution_profile"] = "granted_v1"

    from app.execution.authorization import decide_execution

    assert baseline_provenance(run) == "unknown"
    decision = decide_execution(bench, run, "schedule")
    assert decision.allowed is False
    assert decision.error_category == "baseline_unverifiable"
    assert baseline_drift(run) == []
    assert "approvals" not in run.artifacts


def test_pending_gate_does_not_count_as_approved_baseline(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    project = bench.create_project("pending")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.gates.append({"id": "G-p", "kind": "PLAN基线确认", "status": "pending", "payload": {}})
    assert baseline_provenance(run) == "none"
    assert baseline_drift(run) == []
