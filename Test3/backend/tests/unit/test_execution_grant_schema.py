from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.execution.grant_policy import grant_stale_reason
from app.schemas.execution_grant import ExecutionGrant, ExecutionGrantCreate


def _create(**overrides) -> dict:
    body = {
        "execution_profile": "granted_v1",
        "task_codes": ["T-01"],
        "approved_baseline_hashes": {"PLAN": "aaa"},
        "repo_remote": "origin",
        "repo_owner": "WaterProMax",
        "repo_name": "HexaGraph",
        "base_branch": "teamwork-001",
        "feature_branch": "feat-p1-demo",
        "allowed_tool_refs": [],
    }
    body.update(overrides)
    return body


def test_valid_create_keeps_task_codes() -> None:
    model = ExecutionGrantCreate.model_validate(_create())
    assert model.task_codes == ["T-01"]
    assert model.execution_profile == "granted_v1"


def test_empty_task_codes_is_rejected_at_model_layer() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ExecutionGrantCreate.model_validate(_create(task_codes=[]))
    assert any("task_codes" in [str(part) for part in error["loc"]] for error in excinfo.value.errors())


def test_legacy_profile_is_rejected_at_model_layer() -> None:
    with pytest.raises(ValidationError):
        ExecutionGrantCreate.model_validate(_create(execution_profile="legacy"))


def test_model_can_be_passed_to_grant_policy() -> None:
    grant = ExecutionGrant(
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
        status="active",
        created_at="2026-11-19T00:00:00+00:00",
    )
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes={"T-01"}) is None
    assert (
        grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "bbb"}, requested_task_codes={"T-01"})
        == "baseline_changed:PLAN"
    )