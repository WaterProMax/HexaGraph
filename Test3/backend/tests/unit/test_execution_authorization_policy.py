"""Card 3: one execution-authorization policy for every entry point."""

from __future__ import annotations

from pathlib import Path

from app.agents.runtime import RoleRegistry
from app.execution.authorization import decide_execution
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


class _RealProvider:
    def __init__(self) -> None:
        self.calls = []


def _bench(tmp_path: Path, provider) -> Workbench:
    return Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)


def _run(bench: Workbench, *, plan_status: str = "approved"):
    project = bench.create_project("authz")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    run.artifacts["baseline_provenance"] = "fixture"
    run.gates.append({"id": "G-P", "kind": "PLAN基线确认", "status": plan_status, "payload": {}})
    if plan_status == "approved":
        run.approved_baseline_hashes = {"PLAN": "p" * 64}
        run.artifacts["approved_baseline_hashes"] = {"PLAN": "p" * 64}
    return run


def test_pending_plan_blocks_schedule_in_every_mode(tmp_path: Path) -> None:
    for provider in (ScriptedProvider([]), _RealProvider()):
        bench = _bench(tmp_path / type(provider).__name__, provider)
        run = _run(bench, plan_status="pending")
        decision = decide_execution(bench, run, "schedule")
        assert decision.allowed is False
        assert decision.blocked_reason == "plan_not_approved"


def test_scripted_provider_does_not_authorize_legacy_execution(tmp_path: Path) -> None:
    real_bench = _bench(tmp_path / "real", _RealProvider())
    real_run = _run(real_bench)
    denied = decide_execution(real_bench, real_run, "schedule")
    assert denied.allowed is False
    assert denied.error_category == "profile_not_granted_v1"
    assert denied.detail

    fake_bench = _bench(tmp_path / "scripted", ScriptedProvider([]))
    fake_run = _run(fake_bench)
    also_denied = decide_execution(fake_bench, fake_run, "schedule")
    assert also_denied.allowed is False
    assert also_denied.error_category == "profile_not_granted_v1"

    simulated_bench = Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path / "simulated",
        execution_policy=ExecutionPolicy(simulated=True),
    )
    simulated_run = _run(simulated_bench)
    allowed = decide_execution(simulated_bench, simulated_run, "schedule")
    assert allowed.allowed is True
    assert allowed.simulated is True


def test_unspecified_profile_fails_closed(tmp_path: Path) -> None:
    bench = _bench(tmp_path, ScriptedProvider([]))
    run = _run(bench)
    run.execution_profile = ""
    run.artifacts.pop("execution_profile", None)
    decision = decide_execution(bench, run, "schedule")
    assert decision.allowed is False
    assert decision.error_category == "profile_unspecified"


def test_granted_real_requires_safety_gate(tmp_path: Path) -> None:
    bench = _bench(tmp_path, _RealProvider())
    run = _run(bench)
    run.execution_profile = "granted_v1"
    run.artifacts["execution_profile"] = "granted_v1"
    bench.execution_safety_ready = False

    denied = decide_execution(bench, run, "execute")
    assert denied.allowed is False
    assert denied.error_category == "execution_safety_not_ready"

    bench.execution_safety_ready = True
    allowed = decide_execution(bench, run, "execute")
    assert allowed.allowed is True
    assert allowed.simulated is False


def test_granted_scripted_still_needs_safety_or_simulated_executor(tmp_path: Path) -> None:
    bench = _bench(tmp_path, ScriptedProvider([]))
    run = _run(bench)
    run.execution_profile = "granted_v1"
    run.artifacts["execution_profile"] = "granted_v1"

    denied = decide_execution(bench, run, "schedule")
    assert denied.allowed is False
    assert denied.error_category == "execution_safety_not_ready"

    simulated = Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path / "sim",
        execution_policy=ExecutionPolicy(simulated=True),
    )
    sim_run = _run(simulated)
    sim_run.execution_profile = "granted_v1"
    sim_run.artifacts["execution_profile"] = "granted_v1"
    assert decide_execution(simulated, sim_run, "schedule").allowed is True


def test_accept_uses_the_same_policy(tmp_path: Path) -> None:
    real_bench = _bench(tmp_path / "real", _RealProvider())
    real_run = _run(real_bench)
    assert decide_execution(real_bench, real_run, "accept").allowed is False

    fake_bench = _bench(tmp_path / "scripted", ScriptedProvider([]))
    fake_run = _run(fake_bench)
    assert decide_execution(fake_bench, fake_run, "accept").allowed is False

    simulated = Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path / "sim-accept",
        execution_policy=ExecutionPolicy(simulated=True),
    )
    sim_run = _run(simulated)
    assert decide_execution(simulated, sim_run, "accept").allowed is True


def test_cross_project_is_rejected_before_mode(tmp_path: Path) -> None:
    from app.discussion.models import DiscussionBudget, DiscussionSession

    bench = _bench(tmp_path, ScriptedProvider([]))
    run = _run(bench)
    discussion = DiscussionSession(
        session_id="S-other",
        project_id="another-project",
        leader_bot_id="B1",
        participant_bot_ids=["B1"],
        status="approved",
        current_round=1,
        budget=DiscussionBudget(),
        requirement_snapshot_hash="h" * 64,
    )
    decision = decide_execution(bench, run, "schedule", discussion=discussion)
    assert decision.allowed is False
    assert decision.blocked_reason == "cross_project_mismatch"