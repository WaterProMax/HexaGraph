"""Card 2: honest evidence levels (scripted vs real model vs real execution)."""

from __future__ import annotations

from pathlib import Path

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workflow.evidence import evidence_for_run


class _DummyRealProvider:
    """Not a ScriptedProvider/ReplayProvider: stands in for a paid provider."""

    def __init__(self) -> None:
        self.calls = []


def _bench(tmp_path: Path, provider) -> Workbench:
    return Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)


def _run(bench: Workbench, *, done: bool = True):
    project = bench.create_project("evidence")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = {"tasks": [], "work_packages": []}
    if done:
        run.tasks["T-01"] = {"state": "done", "code": "T-01", "card": {}}
        run.artifacts["acceptance"] = {"features": [], "nonfunc": [], "matrix": []}
        run.gates.append(
            {"id": "G-A", "kind": "验收确认", "status": "approved", "payload": {"pass": True}}
        )
    return run


def test_scripted_run_never_claims_real_execution(tmp_path: Path) -> None:
    bench = _bench(tmp_path, ScriptedProvider([]))
    run = _run(bench)

    evidence = evidence_for_run(bench, run)

    assert evidence["level"] == "scripted"
    assert evidence["model_mode"] == "scripted"
    assert evidence["execution_mode"] == "simulated"
    assert evidence["verification_status"] == "passed"
    assert "脚本" in evidence["verification_label"]
    assert "真实" not in evidence["verification_label"]
    assert evidence["project_id"] == run.project_id
    assert evidence["run_id"] == run.id


def test_real_model_without_execution_is_not_real_execution(tmp_path: Path) -> None:
    provider = _DummyRealProvider()
    bench = _bench(tmp_path, provider)
    run = _run(bench, done=False)
    bench.gateway.stats["calls"] = 1

    evidence = evidence_for_run(bench, run)

    assert evidence["level"] == "real_model"
    assert evidence["model_mode"] == "real"
    assert evidence["execution_mode"] == "not_run"
    assert evidence["verification_status"] == "not_run"
    assert "未真实执行" in evidence["verification_label"]


def test_real_execution_requires_passed_verification(tmp_path: Path) -> None:
    provider = _DummyRealProvider()
    bench = _bench(tmp_path, provider)
    run = _run(bench, done=True)
    bench.gateway.stats["calls"] = 1

    evidence = evidence_for_run(bench, run)

    assert evidence["level"] == "real_execution"
    assert evidence["execution_mode"] == "real"
    assert evidence["verification_status"] == "passed"
    assert evidence["verification_label"] == "真实执行验收"


def test_pending_acceptance_is_unknown_not_passed(tmp_path: Path) -> None:
    bench = _bench(tmp_path, ScriptedProvider([]))
    run = _run(bench, done=False)
    run.tasks["T-01"] = {"state": "done", "code": "T-01", "card": {}}
    run.gates.append({"id": "G-A", "kind": "验收确认", "status": "pending", "payload": {}})

    evidence = evidence_for_run(bench, run)

    assert evidence["verification_status"] == "unknown"
    assert evidence["level"] == "scripted"