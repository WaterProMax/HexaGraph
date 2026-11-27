"""Card 1: phase admission — server-side gates before plan/schedule/accept."""

from __future__ import annotations

import pytest

from app.discussion.models import DecisionPackage, DiscussionBudget, DiscussionSession
from app.services.runtime import RunState
from app.workflow.admission import WorkflowRejected, assert_phase_admission


def _session(status: str, *, project_id: str = "P1", package: bool | None = None) -> DiscussionSession:
    if package is None:
        package = status == "approved"
    return DiscussionSession(
        session_id="S1",
        project_id=project_id,
        leader_bot_id="B1",
        participant_bot_ids=["B1"],
        status=status,  # type: ignore[arg-type]
        current_round=1,
        budget=DiscussionBudget(),
        requirement_snapshot_hash="h" * 64,
        decision_package=(
            DecisionPackage(
                decision_id="D1",
                session_id="S1",
                requirement_snapshot_hash="h" * 64,
                proposal_ids=[],
                dissent_items=[],
                hard_gate_summary={},
                body_md="# 需求",
                sha256="d" * 64,
            )
            if package
            else None
        ),
    )


def _run(*, project_id: str = "P1", session_id: str | None = "S1", gates=None) -> RunState:
    run = RunState(id="R1", project_id=project_id, idea="idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    if session_id is not None:
        run.artifacts["discussion_session_id"] = session_id
    run.gates.extend(gates or [])
    return run


def _gate(kind: str, status: str = "pending") -> dict:
    return {"id": "G1", "kind": kind, "status": status, "payload": {}}


def test_plan_requires_approved_spec() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("plan", discussion=_session("converged_pending_human"))
    assert exc.value.status_code == 409
    assert exc.value.category == "invalid_status"
    assert exc.value.blocked_reason == "spec_not_approved"


def test_plan_requires_decision_package_even_when_approved() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("plan", discussion=_session("approved", package=False))
    assert exc.value.blocked_reason == "spec_not_approved"


def test_plan_passes_for_approved_session_with_approved_design() -> None:
    run = _run(gates=[_gate("DESIGN基线确认", "approved")])
    del run.artifacts["plan"]
    assert_phase_admission("plan", discussion=_session("approved"), run=run)


def test_plan_requires_design_run_first() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("plan", discussion=_session("approved"))
    assert exc.value.status_code == 409
    assert exc.value.blocked_reason == "design_not_approved"


def test_plan_requires_design_baseline_approval() -> None:
    run = _run(gates=[_gate("DESIGN基线确认")])
    del run.artifacts["plan"]
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("plan", discussion=_session("approved"), run=run)
    assert exc.value.blocked_reason == "design_not_approved"


def test_plan_idempotent_when_plan_already_exists() -> None:
    # 旧讨论运行没有 DESIGN 关卡，但已有计划：重复 /plan 是幂等读取。
    assert_phase_admission("plan", discussion=_session("approved"), run=_run())


def test_design_passes_for_approved_session() -> None:
    assert_phase_admission("design", discussion=_session("approved"))


def test_design_requires_approved_spec() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("design", discussion=_session("converged_pending_human"))
    assert exc.value.blocked_reason == "spec_not_approved"


def test_plan_rejects_cross_project_run() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission(
            "plan", discussion=_session("approved"), run=_run(project_id="P2")
        )
    assert exc.value.blocked_reason == "cross_project_mismatch"


def test_schedule_rejects_pending_plan_gate() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("schedule", run=_run(gates=[_gate("PLAN基线确认")]))
    assert exc.value.status_code == 409
    assert exc.value.blocked_reason == "plan_not_approved"


def test_schedule_passes_after_plan_approval() -> None:
    run = _run(gates=[_gate("PLAN基线确认", "approved")])
    run.approved_baseline_hashes = {"PLAN": "p" * 64}
    assert_phase_admission("schedule", run=run)


def test_schedule_keeps_legacy_fixture_runs_working() -> None:
    # A run with a plan but no gate is the legacy/fabricated path used by
    # existing tests; it must not be turned into a false "plan_not_approved".
    assert_phase_admission("schedule", run=_run(session_id=None))


def test_confirm_plan_requires_pending_gate() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("confirm_plan", run=_run(gates=[]))
    assert exc.value.blocked_reason == "plan_gate_missing"


def test_accept_rejects_pending_plan_gate() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission("accept", run=_run(gates=[_gate("PLAN基线确认")]))
    assert exc.value.blocked_reason == "plan_not_approved"


def test_cross_project_run_rejected_for_execution() -> None:
    with pytest.raises(WorkflowRejected) as exc:
        assert_phase_admission(
            "execute",
            discussion=_session("approved", project_id="P1"),
            run=_run(project_id="P2", gates=[_gate("PLAN基线确认", "approved")]),
        )
    assert exc.value.blocked_reason == "cross_project_mismatch"