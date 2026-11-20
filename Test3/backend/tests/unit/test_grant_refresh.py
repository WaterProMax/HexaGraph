from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import GrantRejected
from app.execution.baseline import hash_artifact, write_approved_baseline_hash
from app.execution.grant_refresh import refresh_grant_status
from app.schemas.execution_grant import ExecutionGrant
from tests.p1_support import install_plan, make_bench, make_grant


def _grant(status: str = "active") -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id="run-1",
        execution_profile="granted_v1",
        task_codes=["T-01", "T-02"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat-p1-demo",
        allowed_tool_refs=[],
        status=status,  # type: ignore[arg-type]
        created_at="2026-11-19T00:00:00+00:00",
    )


def test_matching_baseline_stays_active() -> None:
    assert refresh_grant_status(_grant(), approved_baseline_hashes={"PLAN": "aaa"}).status == "active"


def test_changed_baseline_marks_stale() -> None:
    updated = refresh_grant_status(_grant(), approved_baseline_hashes={"PLAN": "bbb"})
    assert updated.status == "stale"


def test_refresh_signature_has_no_revision_parameter() -> None:
    params = set(inspect.signature(refresh_grant_status).parameters)
    assert params == {"grant", "approved_baseline_hashes"}
    assert not any("revision" in name for name in params)


def test_hash_artifact_uses_raw_bytes() -> None:
    assert hash_artifact(b"plan-v1") == hashlib.sha256(b"plan-v1").hexdigest()


def test_write_hash_records_key_on_run() -> None:
    run = SimpleNamespace(artifacts={})
    digest = write_approved_baseline_hash(run, "PLAN", b"plan-v1")
    assert run.artifacts["approved_baseline_hashes"]["PLAN"] == digest

async def _granted_bench(tmp_path: Path):
    """Production F-04 enable path: approve PLAN, enable, bind an active Grant."""
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev09")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    plan_hash = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    await bench.enable_granted_execution(run.id, {"PLAN": plan_hash})
    await bench.add_grant(
        make_grant(run.id, ["T-01"], hashes={"PLAN": plan_hash}, allowed_tool_refs=["python -m pytest"])
    )
    return bench, run, plan_hash


@pytest.mark.asyncio
async def test_real_run_revision_bump_does_not_stale_active_grant(tmp_path: Path) -> None:
    bench, run, plan_hash = await _granted_bench(tmp_path)
    try:
        task = run.tasks["T-01"]
        run_before = run.revision
        task_before = task["revision"]
        run.revision += 5
        task["revision"] += 3

        grant, spec = await bench._authorize_granted_execution(run, "T-01")

        assert run.revision == run_before + 5
        assert task["revision"] == task_before + 3
        assert grant.status == "active"
        assert spec["approved_baseline_hashes"]["PLAN"] == plan_hash
        assert refresh_grant_status(grant, approved_baseline_hashes={"PLAN": plan_hash}).status == "active"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_real_run_revision_bump_does_not_hide_a_changed_baseline(tmp_path: Path) -> None:
    bench, run, _plan_hash = await _granted_bench(tmp_path)
    try:
        run.revision += 2
        run.tasks["T-01"]["revision"] += 1
        run.artifacts["plan"]["tasks"][0]["title"] = "changed after approval"
        with pytest.raises(GrantRejected) as excinfo:
            await bench._authorize_granted_execution(run, "T-01")
        assert excinfo.value.category == "baseline_stale"
    finally:
        await bench.close()
