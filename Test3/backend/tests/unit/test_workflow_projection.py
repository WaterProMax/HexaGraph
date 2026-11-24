"""Card 1: internal workflow stage projection (pure, read-only)."""

from __future__ import annotations

import pytest

from app.discussion.models import DecisionPackage, DiscussionBudget, DiscussionSession
from app.services.runtime import RunState
from app.workflow.projection import find_run_for_session, project_workflow_projection


def _package(session_id: str = "S1") -> DecisionPackage:
    return DecisionPackage(
        decision_id="D1",
        session_id=session_id,
        requirement_snapshot_hash="h" * 64,
        proposal_ids=["p1"],
        dissent_items=[],
        hard_gate_summary={"coverage": True},
        body_md="# 需求",
        sha256="d" * 64,
    )


def _session(status: str, *, project_id: str = "P1", package: bool | None = None) -> DiscussionSession:
    if package is None:
        package = status in {"approved", "converged_pending_human"}
    return DiscussionSession(
        session_id="S1",
        project_id=project_id,
        leader_bot_id="B1",
        participant_bot_ids=["B1", "B2"],
        status=status,  # type: ignore[arg-type]
        current_round=1,
        budget=DiscussionBudget(),
        requirement_snapshot_hash="h" * 64,
        decision_package=_package() if package else None,
    )


def _run(*, project_id: str = "P1", session_id: str | None = "S1", gates=None) -> RunState:
    run = RunState(id="R1", project_id=project_id, idea="idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.artifacts["baseline_provenance"] = "fixture"
    if session_id is not None:
        run.artifacts["discussion_session_id"] = session_id
    run.gates.extend(gates or [])
    return run


def _gate(kind: str, status: str = "pending") -> dict:
    return {"id": "G1", "kind": kind, "status": status, "payload": {}}


@pytest.mark.parametrize(
    "status, expected",
    [
        ("draft", "discussing"),
        ("grouping", "discussing"),
        ("round1_independent", "discussing"),
        ("cross_review", "discussing"),
        ("round_n_revise", "discussing"),
        ("converged_pending_human", "spec_pending"),
        ("approved", "spec_approved"),
        ("rejected", "blocked"),
        ("terminated", "blocked"),
        ("budget_exhausted", "blocked"),
    ],
)
def test_discussion_status_maps_to_internal_stage(status: str, expected: str) -> None:
    projection = project_workflow_projection(discussion=_session(status))
    assert projection.stage == expected
    assert projection.status == status


def test_spec_approved_with_pending_plan_gate_is_plan_pending() -> None:
    projection = project_workflow_projection(
        discussion=_session("approved"), run=_run(gates=[_gate("PLAN基线确认")])
    )
    assert projection.stage == "plan_pending"
    assert projection.spec_approved is True
    assert projection.plan_approved is False


def test_approved_plan_without_tasks_is_plan_approved() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    projection = project_workflow_projection(run=run)
    assert projection.stage == "plan_approved"
    assert projection.plan_approved is True


def test_ready_tasks_without_grant_is_authorization_pending() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.tasks["T-01"] = {"state": "ready", "code": "T-01", "card": {}}
    projection = project_workflow_projection(run=run, grants=[])
    assert projection.stage == "authorization_pending"


def test_running_task_is_executing() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.tasks["T-01"] = {"state": "running", "code": "T-01", "card": {}}
    projection = project_workflow_projection(run=run)
    assert projection.stage == "executing"


def test_acceptance_gate_is_verifying() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved"), _gate("验收确认")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.tasks["T-01"] = {"state": "done", "code": "T-01", "card": {}}
    projection = project_workflow_projection(run=run)
    assert projection.stage == "verifying"


def test_done_run_is_accepted() -> None:
    run = _run()
    run.status = "done"
    projection = project_workflow_projection(run=run, discussion=_session("approved"))
    assert projection.stage == "accepted"


def test_cross_project_run_is_blocked() -> None:
    projection = project_workflow_projection(
        discussion=_session("approved", project_id="P1"),
        run=_run(project_id="P2"),
    )
    assert projection.stage == "blocked"
    assert "cross_project_mismatch" in {item["code"] for item in projection.blocked}


def test_cross_session_run_is_blocked() -> None:
    projection = project_workflow_projection(
        discussion=_session("approved"),
        run=_run(session_id="OTHER"),
    )
    assert projection.stage == "blocked"
    assert "cross_project_mismatch" in {item["code"] for item in projection.blocked}


def test_paused_run_is_blocked_but_keeps_legacy_status() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.paused = True
    projection = project_workflow_projection(run=run)
    assert projection.stage == "blocked"
    assert projection.status == "active"
    assert "run_paused" in {item["code"] for item in projection.blocked}


def test_projection_is_serializable_and_bound_to_ids() -> None:
    projection = project_workflow_projection(
        discussion=_session("approved"), run=_run(gates=[_gate("PLAN基线确认")])
    )
    payload = projection.to_dict()
    assert payload["project_id"] == "P1"
    assert payload["session_id"] == "S1"
    assert payload["run_id"] == "R1"
    assert payload["stage"] == "plan_pending"
    assert isinstance(payload["blocked"], list)


def test_find_run_for_session_ignores_other_sessions() -> None:
    matching = _run()
    other = _run(session_id="S2")
    other.id = "R2"
    found = find_run_for_session({"R1": matching, "R2": other}, "S1")
    assert found is matching

def test_active_grant_is_not_reported_as_authorization_pending() -> None:
    from types import SimpleNamespace

    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    run.tasks["T-01"] = {"state": "ready", "code": "T-01", "card": {}}
    grant = SimpleNamespace(status="active", task_codes=["T-01"])
    projection = project_workflow_projection(run=run, grants=[grant])
    assert projection.stage == "plan_approved"
