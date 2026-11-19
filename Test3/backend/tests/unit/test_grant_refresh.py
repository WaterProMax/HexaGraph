from __future__ import annotations

import hashlib
import inspect
from types import SimpleNamespace

from app.execution.baseline import hash_artifact, write_approved_baseline_hash
from app.execution.grant_refresh import refresh_grant_status
from app.schemas.execution_grant import ExecutionGrant


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


def test_revision_is_not_an_input() -> None:
    run_revision = 5  # bumped by gate/control; must not reach the refresh policy
    assert refresh_grant_status(_grant(), approved_baseline_hashes={"PLAN": "aaa"}).status == "active"
    assert run_revision == 5
    params = set(inspect.signature(refresh_grant_status).parameters)
    assert params == {"grant", "approved_baseline_hashes"}


def test_hash_artifact_uses_raw_bytes() -> None:
    assert hash_artifact(b"plan-v1") == hashlib.sha256(b"plan-v1").hexdigest()


def test_write_hash_records_key_on_run() -> None:
    run = SimpleNamespace(artifacts={})
    digest = write_approved_baseline_hash(run, "PLAN", b"plan-v1")
    assert run.artifacts["approved_baseline_hashes"]["PLAN"] == digest