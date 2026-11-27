"""Card 1: model mode is not executor capability."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import GrantRejected
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.p1_support import install_plan


def _bench(tmp_path: Path, policy: ExecutionPolicy | None = None) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=policy,
    )


def _run(bench: Workbench):
    project = bench.create_project("capability")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    return run


@pytest.mark.asyncio
async def test_scripted_model_alone_does_not_authorize_local_execution(tmp_path, monkeypatch) -> None:
    bench = _bench(tmp_path)  # product default policy
    run = _run(bench)
    calls = {"worktree": 0, "repo": 0, "command": 0}

    import app.services.runtime as runtime_module

    monkeypatch.setattr(
        runtime_module, "create_worktree", lambda *a, **k: calls.__setitem__("worktree", calls["worktree"] + 1)
    )
    monkeypatch.setattr(
        runtime_module, "init_repo_sync", lambda *a, **k: calls.__setitem__("repo", calls["repo"] + 1)
    )
    monkeypatch.setattr(
        runtime_module, "run_command", lambda *a, **k: calls.__setitem__("command", calls["command"] + 1)
    )

    with pytest.raises(GrantRejected) as exc:
        await bench.schedule_once(run)

    assert exc.value.category == "profile_not_granted_v1"
    assert calls == {"worktree": 0, "repo": 0, "command": 0}
    assert run.tasks["T-01"]["state"] == "ready"
    assert not (bench.data_dir / "runs" / run.id / "wt").exists()
    assert not (bench.data_dir / "runs" / run.id / "repo").exists()


@pytest.mark.asyncio
async def test_scripted_model_with_simulated_executor_has_no_side_effects(tmp_path) -> None:
    bench = _bench(tmp_path, ExecutionPolicy(simulated=True))
    run = _run(bench)

    started = await bench.schedule_once(run)

    assert started == ["T-01"]
    assert run.tasks["T-01"]["state"] == "done"
    evidence = run.tasks["T-01"]["evidence"]
    assert evidence and evidence[-1]["kind"] == "simulated"
    assert not (bench.data_dir / "runs" / run.id / "wt").exists()
    assert not (bench.data_dir / "runs" / run.id / "repo").exists()


@pytest.mark.asyncio
async def test_explicit_test_policy_authorizes_legacy_executor_only_in_tests(tmp_path) -> None:
    bench = _bench(tmp_path, ExecutionPolicy(local_execution_authorized=True))
    run = _run(bench)
    assert bench.execution_policy.local_execution_authorized is True
    # The authorization decision is the only difference; real product default
    # remains ExecutionPolicy(local_execution_authorized=False).
    from app.execution.authorization import decide_execution

    assert decide_execution(bench, run, "schedule").allowed is True