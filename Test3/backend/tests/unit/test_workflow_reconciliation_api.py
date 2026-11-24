"""Card 3: controlled reconciliation; no automatic replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.runtime import _git_head
from app.workspace.gitops import init_repo_sync
from tests.p1_support import install_plan, make_bench


def _seed(tmp_path: Path, *, evidence: bool):
    bench = make_bench(tmp_path)
    project = bench.create_project("reconcile-api")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    task = run.tasks["T-01"]
    bench._set_state(run, task, "scheduled")
    if evidence:
        task["evidence"] = [{"kind": "command", "summary": "pytest ran", "path": "log"}]
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    head = _git_head(repo)
    task["attempt"] = {
        "attempt_id": "A-1",
        "intent": "execute",
        "status": "done",
        "baseline_hashes": {},
        "repo": str(repo),
        "commit": head,
        "task_code": "T-01",
    }
    bench._persist_snapshot(run)
    return bench, run


@pytest.mark.asyncio
async def test_restart_flags_running_task_even_with_evidence(tmp_path) -> None:
    bench, run = _seed(tmp_path, evidence=True)
    run_id = run.id
    await bench.close()
    restored = make_bench(tmp_path)
    task = restored.runs[run_id].tasks["T-01"]
    assert task["needs_reconciliation"] is True
    assert task["paused"] is True
    assert await restored.schedule_once(restored.runs[run_id]) == []


@pytest.mark.asyncio
async def test_accept_evidence_requires_matching_commit_and_baseline(tmp_path) -> None:
    bench, run = _seed(tmp_path, evidence=True)
    task = run.tasks["T-01"]
    task["needs_reconciliation"] = True
    task["paused"] = True
    report = await bench.resolve_reconciliation(
        run, "T-01", "accept_evidence", task["revision"], actor="leader", reason="verified commit"
    )
    assert task["state"] == "done"
    assert task["needs_reconciliation"] is False
    assert report["needs_reconciliation"] is False
    assert task["reconciliation_history"][-1]["decision"] == "accept_evidence"

    task_copy = dict(task)
    task_copy["state"] = "running"
    task_copy["needs_reconciliation"] = True
    task_copy["paused"] = True
    task_copy["attempt"] = dict(task["attempt"], commit="deadbeef")
    run.tasks["T-01"] = task_copy
    from app.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        await bench.resolve_reconciliation(
            run, "T-01", "accept_evidence", task_copy["revision"], actor="leader"
        )


@pytest.mark.asyncio
async def test_mark_failed_safe_retry_and_continue(tmp_path) -> None:
    bench, run = _seed(tmp_path, evidence=False)
    task = run.tasks["T-01"]
    task["needs_reconciliation"] = True
    task["paused"] = True
    report = await bench.resolve_reconciliation(
        run, "T-01", "continue_reconcile", task["revision"], actor="leader"
    )
    assert task["state"] == "running"
    assert report["needs_reconciliation"] is True

    await bench.resolve_reconciliation(
        run, "T-01", "mark_failed_safe_retry", task["revision"], actor="leader", reason="safe retry"
    )
    assert task["state"] == "failed"
    assert task["needs_reconciliation"] is False

    # A retry after reconciliation still goes through the execution authorization.
    task["state"] = "failed"
    task["revision"] = 1
    run.execution_profile = ""
    run.artifacts.pop("execution_profile", None)
    from app.errors import GrantRejected

    with pytest.raises(GrantRejected):
        await bench.control_task(run, "T-01", "retry", 1, "retry", actor="owner")

@pytest.mark.asyncio
async def test_http_reconciliation_requires_actor_and_cas(tmp_path) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    bench, run = _seed(tmp_path, evidence=False)
    task = run.tasks["T-01"]
    task["needs_reconciliation"] = True
    task["paused"] = True
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
    assert ok.status_code == 200, ok.text
    assert ok.json()["needs_reconciliation"] is True
    await client.aclose()
