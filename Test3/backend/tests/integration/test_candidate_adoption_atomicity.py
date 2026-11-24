"""Card B: candidate adoption validates first and commits once."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import run_approved_baseline_hashes, run_execution_profile
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.p1_support import make_grant, persist_granted_profile


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def _run(bench: Workbench):
    project = bench.create_project("atomic-candidate")
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


def _candidate(bench, run):
    return bench._create_candidate(
        run,
        {"plan": {"tasks": [], "work_packages": []}},
        ["PLAN"],
        source_kind="cr",
        mode="cr",
    )


def _gate(run, candidate_id: str):
    return next(g for g in run.gates if (g.get("payload") or {}).get("candidate_id") == candidate_id)


def _approved_count(run) -> int:
    return len(run.artifacts.get("approvals") or [])


@pytest.mark.asyncio
async def test_persist_failure_keeps_gate_pending_and_old_baseline(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    old_plan = dict(run.artifacts["plan"])
    old_hashes = dict(run.approved_baseline_hashes)
    approvals = _approved_count(run)

    def boom(_run):
        raise OSError("snapshot disk full")

    monkeypatch.setattr(bench, "_persist_snapshot", boom)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert res.status_code == 500
    # The live object is restored to the pre-commit state as well.
    assert gate["status"] == "pending"
    assert run.artifacts["plan"] == old_plan
    assert run.approved_baseline_hashes == old_hashes
    assert _approved_count(run) == approvals

    monkeypatch.undo()
    run_id = run.id
    await bench.close()
    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    saved_gate = _gate(saved, candidate["candidate_id"])
    saved_candidate = saved.artifacts["workflow_candidates"][candidate["candidate_id"]]
    assert saved_gate["status"] == "pending"
    assert saved_candidate["status"] == "pending"
    assert saved.artifacts["plan"] == old_plan
    assert saved.artifacts.get("approved_baseline_hashes") == old_hashes


@pytest.mark.asyncio
async def test_precommit_grant_failure_leaves_old_baseline_and_active_grant(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    await persist_granted_profile(bench, run, run.approved_baseline_hashes)
    grant = make_grant(run.id, ["T-01"], hashes=run.approved_baseline_hashes)
    await bench.add_grant(grant)
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    old_plan = dict(run.artifacts["plan"])
    old_hashes = dict(run.approved_baseline_hashes)

    async def boom(_run, _reason):
        raise OSError("grant store unavailable")

    monkeypatch.setattr(bench, "_mark_grants_stale", boom)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert res.status_code == 500
    assert gate["status"] == "pending"
    assert run.artifacts["plan"] == old_plan
    assert run.approved_baseline_hashes == old_hashes

    monkeypatch.undo()
    run_id = run.id
    await bench.close()
    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    assert _gate(saved, candidate["candidate_id"])["status"] == "pending"
    assert saved.artifacts["plan"] == old_plan
    grants = await restored.grants_for_run(run_id)
    assert grants[-1].status == "active"


@pytest.mark.asyncio
async def test_grant_stale_before_snapshot_failure_is_safe(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    await persist_granted_profile(bench, run, run.approved_baseline_hashes)
    await bench.add_grant(make_grant(run.id, ["T-01"], hashes=run.approved_baseline_hashes))
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    old_plan = dict(run.artifacts["plan"])

    def boom(_run):
        raise OSError("snapshot failed after grant refresh")

    monkeypatch.setattr(bench, "_persist_snapshot", boom)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert res.status_code == 500
    assert gate["status"] == "pending"
    assert run.artifacts["plan"] == old_plan

    monkeypatch.undo()
    run_id = run.id
    await bench.close()
    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    # No half-adoption: old baseline + pending gate.  The grant may already be
    # stale; that is the documented safe side of the chosen ordering.
    assert _gate(saved, candidate["candidate_id"])["status"] == "pending"
    assert saved.artifacts["plan"] == old_plan
    assert all(grant.status == "stale" for grant in await restored.grants_for_run(run_id))


@pytest.mark.asyncio
async def test_failed_adoption_is_retryable_with_same_cas(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])

    original = bench._persist_snapshot

    def fail_once(run_state):
        if (run_state.artifacts.get("workflow_candidates") or {}).get(candidate["candidate_id"], {}).get(
            "status"
        ) == "adopted":
            raise OSError("transient")
        return original(run_state)

    monkeypatch.setattr(bench, "_persist_snapshot", fail_once)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        failed = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert failed.status_code == 500
    assert gate["status"] == "pending"
    assert candidate["status"] == "pending"

    monkeypatch.undo()
    async with _client(app) as client:
        retried = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert retried.status_code == 200, retried.text
    assert candidate["status"] == "adopted"
    assert run.artifacts["plan"] == candidate["documents"]["plan"]


@pytest.mark.asyncio
async def test_adoption_is_idempotent_and_does_not_duplicate_approvals(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        first = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
        approvals = _approved_count(run)
        revision = run.revision
        second = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert first.status_code == 200, first.text
    assert second.status_code in {400, 409}
    assert _approved_count(run) == approvals
    assert run.revision == revision
    assert candidate["status"] == "adopted"


@pytest.mark.asyncio
async def test_concurrent_adoption_has_one_winner_and_one_approval(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
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
    assert _approved_count(run) == 1


@pytest.mark.asyncio
async def test_granted_adoption_survives_restart_with_new_hashes(tmp_path) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    await persist_granted_profile(bench, run, run.approved_baseline_hashes)
    await bench.add_grant(make_grant(run.id, ["T-01"], hashes=run.approved_baseline_hashes))
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        res = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert res.status_code == 200, res.text
    expected = run_approved_baseline_hashes(run)
    assert expected["PLAN"] == candidate["hashes"]["PLAN"]
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    assert run_execution_profile(saved) == "granted_v1"
    assert run_approved_baseline_hashes(saved) == expected
    assert "execution_state_recovered" not in saved.artifacts
    assert all(grant.status == "stale" for grant in await restored.grants_for_run(run_id))


@pytest.mark.asyncio
async def test_failed_snapshot_after_state_sync_recovers_old_baseline_and_retries(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)
    run = _run(bench)
    await persist_granted_profile(bench, run, run.approved_baseline_hashes)
    await bench.add_grant(make_grant(run.id, ["T-01"], hashes=run.approved_baseline_hashes))
    candidate = _candidate(bench, run)
    gate = _gate(run, candidate["candidate_id"])
    old_hashes = dict(run.approved_baseline_hashes)

    def boom(_run):
        raise OSError("snapshot interrupted after state sync")

    monkeypatch.setattr(bench, "_persist_snapshot", boom)
    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        failed = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": run.revision},
        )
    assert failed.status_code == 500
    monkeypatch.undo()
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    assert run_execution_profile(saved) == "granted_v1"
    assert run_approved_baseline_hashes(saved) == old_hashes
    assert _gate(saved, candidate["candidate_id"])["status"] == "pending"
    assert all(grant.status == "stale" for grant in await restored.grants_for_run(run_id))

    app2 = create_app()
    app2.state.workbench = restored
    async with _client(app2) as client:
        retried = await client.post(
            f"/api/gates/{gate['id']}/resolve",
            json={"decision": "approve", "expected_revision": saved.revision},
        )
    assert retried.status_code == 200, retried.text
    assert saved.artifacts["plan"] == candidate["documents"]["plan"]
    await restored.close()
    again = _bench(tmp_path)
    final = again.runs[run_id]
    assert run_execution_profile(final) == "granted_v1"
    assert run_approved_baseline_hashes(final)["PLAN"] == candidate["hashes"]["PLAN"]