"""Card D: reconciliation closures are attempt-bound and survive restarts."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import run_approved_baseline_hashes
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.docs import TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workspace.gitops import _git_sync, commit, create_worktree, init_repo_sync, merge
from tests.p1_support import make_bench, make_card


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _seed_started(tmp_path: Path, *, attempt_id: str = "A-1", state: str = "ready"):
    bench = make_bench(tmp_path)
    project = bench.create_project("reconcile-persist")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    card = make_card("T-01")
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    bench._materialize_tasks(run)
    bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    task = run.tasks["T-01"]
    attempt = {
        "attempt_id": attempt_id,
        "intent": "execute",
        "status": "started",
        "baseline_hashes": dict(run_approved_baseline_hashes(run)),
        "repo": str(bench.data_dir / "runs" / run.id / "repo"),
        "repo_identity": str((bench.data_dir / "runs" / run.id / "repo").resolve()),
        "branch": "task/T-01",
        "commit": "",
        "write_set": list(card.write_set),
        "task_code": "T-01",
        "run_id": run.id,
        "project_id": run.project_id,
    }
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    task["needs_reconciliation"] = True
    task["paused"] = True
    if state != "ready":
        bench._set_state(run, task, "scheduled")
    bench._persist_snapshot(run)
    return bench, run, task


def _seed_merged_accept(tmp_path: Path):
    bench = make_bench(tmp_path)
    project = bench.create_project("reconcile-accept")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    card = make_card("T-01", write_set=["src/T-01.py"])
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    bench._materialize_tasks(run)
    bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    base = _git_sync(repo, "rev-parse", "HEAD")[1].strip()
    ref = _git_sync(repo, "symbolic-ref", "-q", "HEAD")[1].strip()
    wt = bench.data_dir / "runs" / run.id / "wt" / "T-01"
    create_worktree(repo, wt, "task/T-01")
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    _git_sync(wt, "add", "-A")
    work = commit(wt, "task work")
    assert merge(repo, "task/T-01")["ok"] is True
    task = run.tasks["T-01"]
    attempt = {
        "attempt_id": "A-GOOD",
        "intent": "execute",
        "status": "finished_ok",
        "baseline_hashes": dict(run_approved_baseline_hashes(run)),
        "repo": str(repo),
        "repo_identity": str(repo.resolve()),
        "worktree": str(wt),
        "branch": "task/T-01",
        "base_commit": base,
        "integration_ref": ref,
        "integration_ref_sha": base,
        "target_branch": ref,
        "commit": work,
        "write_set": ["src/T-01.py"],
        "task_code": "T-01",
        "run_id": run.id,
        "project_id": run.project_id,
    }
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    task["needs_reconciliation"] = True
    task["paused"] = True
    bench._set_state(run, task, "scheduled")
    bench._persist_snapshot(run)
    return bench, run, task


@pytest.mark.asyncio
async def test_safe_retry_closes_only_that_attempt_and_survives_two_restarts(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    report = await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe retry",
        verified_safe_scope="tmp run repo only",
        risk_accepted=True,
    )
    assert report["needs_reconciliation"] is False
    assert task["state"] == "failed"
    assert task["needs_reconciliation"] is False
    assert [item["attempt_id"] for item in task["reconciliation_resolutions"]] == ["A-1"]
    assert task["attempt_history"][0]["status"] == "started"  # never rewritten

    run_id = run.id
    await bench.close()
    for _ in range(2):
        restored = _bench(tmp_path)
        saved = restored.runs[run_id]
        saved_task = saved.tasks["T-01"]
        assert saved_task.get("needs_reconciliation") is not True
        assert restored._tasks_requiring_reconciliation(saved, {}) == []
        assert saved_task["state"] == "failed"
        assert saved_task["attempt_history"][0]["status"] == "started"
        await restored.close()


@pytest.mark.asyncio
async def test_new_started_attempt_after_resolution_blocks_again(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe retry",
        verified_safe_scope="tmp run repo only",
        risk_accepted=True,
    )
    task["attempt"] = {
        "attempt_id": "A-2",
        "intent": "execute",
        "status": "started",
        "baseline_hashes": dict(run_approved_baseline_hashes(run)),
        "repo": str(bench.data_dir / "runs" / run.id / "repo"),
        "branch": "task/T-01",
        "commit": "",
        "write_set": ["tests/test_t_01.py"],
        "task_code": "T-01",
        "run_id": run.id,
        "project_id": run.project_id,
    }
    task["attempt_history"].append(dict(task["attempt"]))
    bench._persist_snapshot(run)
    run_id = run.id
    await bench.close()

    restored = _bench(tmp_path)
    saved = restored.runs[run_id]
    saved_task = saved.tasks["T-01"]
    assert saved_task["needs_reconciliation"] is True
    assert saved_task["paused"] is True
    assert restored._tasks_requiring_reconciliation(saved, {}) == ["T-01"]
    # The old resolution still exists; the new attempt is the reason to block.
    assert saved_task["reconciliation_resolutions"][0]["attempt_id"] == "A-1"
    with pytest.raises(Exception) as exc:
        await restored.schedule_once(saved, task_codes={"T-01"})
    assert getattr(exc.value, "category", "") == "needs_reconciliation"


@pytest.mark.asyncio
async def test_accept_evidence_persists_done_and_proof_across_restarts(tmp_path) -> None:
    bench, run, task = _seed_merged_accept(tmp_path)
    report = await bench.resolve_reconciliation(
        run, "T-01", "accept_evidence", task["revision"], actor="leader", reason="verified"
    )
    assert report["needs_reconciliation"] is False
    assert task["state"] == "done"
    assert task["completion_proof"]["ok"] is True
    proof = dict(task["completion_proof"])

    run_id = run.id
    await bench.close()
    for _ in range(2):
        restored = _bench(tmp_path)
        saved = restored.runs[run_id]
        saved_task = saved.tasks["T-01"]
        assert saved_task["state"] == "done"
        assert saved_task.get("needs_reconciliation") is not True
        assert saved_task["completion_proof"] == proof
        assert restored._tasks_requiring_reconciliation(saved, {}) == []
        await restored.close()


@pytest.mark.asyncio
async def test_partial_resolution_keeps_task_blocked(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path, attempt_id="A-1")
    task["attempt"] = dict(task["attempt"], attempt_id="A-2")
    task["attempt_history"].append(dict(task["attempt"]))
    bench._persist_snapshot(run)

    app = create_app()
    app.state.workbench = bench
    async with _client(app) as client:
        first = await client.post(
            f"/api/runs/{run.id}/reconcile/T-01",
            json={
                "decision": "mark_failed_safe_retry",
                "expected_revision": task["revision"],
                "attempt_id": "A-1",
                "reason": "first attempt safe",
                "verified_safe_scope": "tmp run repo only",
                "risk_accepted": True,
            },
            headers={"X-Bot-Id": "leader"},
        )
    assert first.status_code == 200, first.text
    assert task["state"] == "ready"
    assert task["needs_reconciliation"] is True
    assert [item["attempt_id"] for item in task["reconciliation_resolutions"]] == ["A-1"]

    async with _client(app) as client:
        second = await client.post(
            f"/api/runs/{run.id}/reconcile/T-01",
            json={
                "decision": "mark_failed_safe_retry",
                "expected_revision": task["revision"],
                "attempt_id": "A-2",
                "reason": "second attempt safe",
                "verified_safe_scope": "tmp run repo only",
                "risk_accepted": True,
            },
            headers={"X-Bot-Id": "leader"},
        )
    assert second.status_code == 200, second.text
    assert task["state"] == "failed"
    assert task["needs_reconciliation"] is False


@pytest.mark.asyncio
async def test_repeat_resolution_is_idempotent_and_conflicts_are_rejected(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    first = await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe",
        verified_safe_scope="tmp only",
        risk_accepted=True,
    )
    resolutions = [dict(item) for item in task["reconciliation_resolutions"]]
    revision = task["revision"]
    again = await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe",
        verified_safe_scope="tmp only",
        risk_accepted=True,
    )
    assert first == again
    assert task["reconciliation_resolutions"] == resolutions
    assert task["revision"] == revision

    with pytest.raises(Exception) as exc:
        await bench.resolve_reconciliation(
            run,
            "T-01",
            "accept_evidence",
            task["revision"],
            actor="leader",
            reason="different",
        )
    assert "attempt_already_resolved" in str(exc.value)


@pytest.mark.asyncio
async def test_wrong_attempt_cross_run_and_stale_cas_have_no_side_effects(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    original_revision = task["revision"]
    other_project = bench.create_project("other")
    other_run = bench.create_run(other_project["id"], "idea")
    other_task = {"attempt": {"attempt_id": "A-OTHER", "task_code": "T-01", "run_id": other_run.id}}
    other_run.tasks["T-01"] = other_task

    with pytest.raises(Exception) as wrong:
        await bench.resolve_reconciliation(
            run,
            "T-01",
            "mark_failed_safe_retry",
            task["revision"],
            actor="leader",
            reason="safe",
            verified_safe_scope="tmp only",
            risk_accepted=True,
            attempt_id="A-MISSING",
        )
    assert "attempt_not_found" in str(wrong.value)
    with pytest.raises(Exception) as cross:
        await bench.resolve_reconciliation(
            run,
            "T-01",
            "mark_failed_safe_retry",
            task["revision"],
            actor="leader",
            reason="safe",
            verified_safe_scope="tmp only",
            risk_accepted=True,
            attempt_id="A-OTHER",
        )
    assert "attempt_not_found" in str(cross.value)
    with pytest.raises(Exception) as stale:
        await bench.resolve_reconciliation(
            run,
            "T-01",
            "mark_failed_safe_retry",
            999,
            actor="leader",
            reason="safe",
            verified_safe_scope="tmp only",
            risk_accepted=True,
        )
    assert "revision" in str(stale.value)
    assert task["needs_reconciliation"] is True
    assert "reconciliation_resolutions" not in task
    assert task["revision"] == original_revision


@pytest.mark.asyncio
async def test_old_baseline_attempt_cannot_be_resolved(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    bench._record_approved_baseline(run, "PLAN", {"tasks": [], "work_packages": []})
    with pytest.raises(Exception) as exc:
        await bench.resolve_reconciliation(
            run,
            "T-01",
            "mark_failed_safe_retry",
            task["revision"],
            actor="leader",
            reason="safe",
            verified_safe_scope="tmp only",
            risk_accepted=True,
        )
    assert "attempt_baseline_mismatch" in str(exc.value)
    assert task["needs_reconciliation"] is True
    assert "reconciliation_resolutions" not in task


@pytest.mark.asyncio
async def test_continue_and_manual_pause_are_preserved(tmp_path) -> None:
    bench, run, task = _seed_started(tmp_path)
    run.paused = True
    report = await bench.resolve_reconciliation(
        run, "T-01", "continue_reconcile", task["revision"], actor="leader"
    )
    assert report["needs_reconciliation"] is True
    assert task["needs_reconciliation"] is True
    assert "reconciliation_resolutions" not in task

    await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe",
        verified_safe_scope="tmp only",
        risk_accepted=True,
    )
    assert run.paused is True


@pytest.mark.asyncio
async def test_safe_retry_never_executes_automatically(tmp_path, monkeypatch) -> None:
    bench, run, task = _seed_started(tmp_path)
    calls: list[str] = []

    async def spy(*_args, **_kwargs):
        calls.append("execute")
        raise AssertionError("resolution must not execute")

    monkeypatch.setattr(bench, "execute_task", spy)
    await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe",
        verified_safe_scope="tmp only",
        risk_accepted=True,
    )
    assert calls == []
    assert len(task["attempt_history"]) == 1