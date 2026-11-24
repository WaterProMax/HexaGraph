"""F3: simulated executor must not touch git/fs/subprocess in accept/takeover/submit/release."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.p1_support import install_plan


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(simulated=True),
    )


def _run(bench: Workbench):
    project = bench.create_project("sim-zero")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "8"
    run.artifacts["spec"] = {
        "features": [
            {
                "code": "F1",
                "kind": "功能",
                "title": "t",
                "scenario": "S1",
                "priority": "P0",
                "impact": "x",
                "acceptance": ["a"],
                "manual": [False],
                "sources": ["idea"],
            }
        ],
        "nonfunc": [],
        "scenarios": [{"code": "S1"}],
        "chapters": [],
    }
    run.artifacts["design"] = {"modules": [], "interfaces": [], "decisions": []}
    install_plan(bench, run, ["T-01"])
    return run


def _spies(monkeypatch) -> list[str]:
    calls: list[str] = []

    def spy(name):
        def record(*_a, **_k):
            calls.append(name)
            raise AssertionError(f"{name} must not be reached in simulation")

        return record

    monkeypatch.setattr("app.services.runtime.init_repo_sync", spy("init_repo_sync"))
    monkeypatch.setattr("app.services.runtime.create_worktree", spy("create_worktree"))
    monkeypatch.setattr("app.services.runtime.tag_build", spy("tag_build"))
    monkeypatch.setattr("app.services.runtime.merge", spy("merge"))
    monkeypatch.setattr("app.services.runtime.shutil.copytree", spy("copytree"))
    monkeypatch.setattr("app.services.runtime.run_command", spy("run_command"))
    return calls


@pytest.mark.asyncio
async def test_accept_and_release_have_zero_side_effects(tmp_path, monkeypatch) -> None:
    calls = _spies(monkeypatch)
    bench = _bench(tmp_path)
    run = _run(bench)
    await bench.schedule_once(run)
    assert run.tasks["T-01"]["state"] == "done"

    gate = await bench.accept(run)
    assert gate["gate"]["payload"]["pass"] is True
    done = await bench.resolve_gate(run, gate["gate"]["id"], "approve", {})
    assert done["status"] == "done"
    assert calls == []
    assert not (bench.data_dir / "runs" / run.id / "repo").exists()
    assert not (bench.data_dir / "runs" / run.id / "wt").exists()
    assert not (bench.data_dir / "runs" / run.id / "release" / "code").exists()
    assert run.artifacts["build_tag"].startswith("simulated-build-")


@pytest.mark.asyncio
async def test_takeover_and_submit_have_zero_side_effects(tmp_path, monkeypatch) -> None:
    calls = _spies(monkeypatch)
    bench = _bench(tmp_path)
    run = _run(bench)
    task = run.tasks["T-01"]
    task["state"] = "ready"
    task["revision"] = 1

    taken = await bench.control_task(run, "T-01", "takeover", 1, "manual", actor="owner")
    assert taken["takeover_workspace"].startswith("simulated://")
    submitted = await bench.control_task(
        run, "T-01", "submit-takeover", taken["revision"], "submit", actor="owner"
    )
    assert submitted["kind"] == "simulated"
    assert calls == []
    assert not (bench.data_dir / "runs" / run.id / "repo").exists()
    assert not (bench.data_dir / "runs" / run.id / "wt").exists()