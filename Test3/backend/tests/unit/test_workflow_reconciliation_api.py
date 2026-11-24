"""F1/F4: restart blocks unknown attempts; accept_evidence proves task work."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.runtime import _git_head
from app.workspace.gitops import _git_sync, commit, init_repo_sync
from tests.p1_support import install_plan, make_bench


def _seed(tmp_path: Path, *, with_work: bool):
    bench = make_bench(tmp_path)
    project = bench.create_project("reconcile-api")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    task = run.tasks["T-01"]
    bench._set_state(run, task, "scheduled")
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    branch = ""
    if with_work:
        _git_sync(repo, "checkout", "-b", "task/T-01")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
        _git_sync(repo, "add", "src/T-01.py")
        commit(repo, "task T-01")
        branch = "task/T-01"
    head = _git_head(repo)
    attempt = {
        "attempt_id": "A-1",
        "intent": "execute",
        "status": "finished_ok",
        "baseline_hashes": {},
        "repo": str(repo),
        "repo_identity": str(repo.resolve()),
        "worktree": str(bench.data_dir / "runs" / run.id / "wt" / "T-01"),
        "branch": branch,
        "write_set": ["src/T-01.py"],
        "target_branch": "HEAD",
        "commit": head,
        "task_code": "T-01",
        "run_id": run.id,
        "project_id": run.project_id,
    }
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    task["needs_reconciliation"] = True
    task["paused"] = True
    bench._persist_snapshot(run)
    return bench, run, repo


@pytest.mark.asyncio
async def test_restart_flags_task_with_started_attempt_history(tmp_path) -> None:
    bench, run, _repo = _seed(tmp_path, with_work=False)
    run_id = run.id
    await bench.close()
    restored = make_bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert task["needs_reconciliation"] is True
    assert await restored.schedule_once(restored.runs[run_id]) == []


@pytest.mark.asyncio
async def test_accept_evidence_rejects_readme_head(tmp_path) -> None:
    bench, run, _repo = _seed(tmp_path, with_work=False)
    task = run.tasks["T-01"]
    with pytest.raises(Exception) as exc:
        await bench.resolve_reconciliation(
            run, "T-01", "accept_evidence", task["revision"], actor="leader"
        )
    assert "completion_not_proven" in str(exc.value)
    assert task["needs_reconciliation"] is True


@pytest.mark.asyncio
async def test_accept_evidence_with_real_branch_commit(tmp_path) -> None:
    bench, run, _repo = _seed(tmp_path, with_work=True)
    task = run.tasks["T-01"]
    report = await bench.resolve_reconciliation(
        run, "T-01", "accept_evidence", task["revision"], actor="leader", reason="verified"
    )
    assert task["state"] == "done"
    assert task["needs_reconciliation"] is False
    assert task["completion_proof"]["ok"] is True
    assert report["needs_reconciliation"] is False


@pytest.mark.asyncio
async def test_mark_failed_requires_scope_and_risk_acceptance(tmp_path) -> None:
    bench, run, _repo = _seed(tmp_path, with_work=False)
    task = run.tasks["T-01"]
    with pytest.raises(Exception) as exc:
        await bench.resolve_reconciliation(
            run, "T-01", "mark_failed_safe_retry", task["revision"], actor="leader", reason="r"
        )
    assert "verified_safe_scope" in str(exc.value)
    await bench.resolve_reconciliation(
        run,
        "T-01",
        "mark_failed_safe_retry",
        task["revision"],
        actor="leader",
        reason="safe retry",
        verified_safe_scope="tmp repo only; no remote push observed",
        risk_accepted=True,
    )
    assert task["state"] == "failed"
    assert task["reconciliation_history"][-1]["risk_accepted"] is True


@pytest.mark.asyncio
async def test_continue_keeps_block(tmp_path) -> None:
    bench, run, _repo = _seed(tmp_path, with_work=False)
    task = run.tasks["T-01"]
    report = await bench.resolve_reconciliation(
        run, "T-01", "continue_reconcile", task["revision"], actor="leader"
    )
    assert report["needs_reconciliation"] is True
    assert task["needs_reconciliation"] is True


@pytest.mark.asyncio
async def test_http_reconciliation_requires_actor_and_cas(tmp_path) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    bench, run, _repo = _seed(tmp_path, with_work=False)
    task = run.tasks["T-01"]
    app = create_app()
    app.state.workbench = bench
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    missing = await client.post(
        f"/api/runs/{run.id}/reconcile/T-01",
        json={"decision": "continue_reconcile", "expected_revision": task["revision"]},
    )
    assert missing.status_code == 400
    stale = await client.post(
        f"/api/runs/{run.id}/reconcile/T-01",
        json={"decision": "continue_reconcile", "expected_revision": 999},
        headers={"X-Bot-Id": "leader"},
    )
    assert stale.status_code == 409
    ok = await client.post(
        f"/api/runs/{run.id}/reconcile/T-01",
        json={"decision": "continue_reconcile", "expected_revision": task["revision"]},
        headers={"X-Bot-Id": "leader"},
    )
    assert ok.status_code == 200
    assert ok.json()["needs_reconciliation"] is True
    await client.aclose()