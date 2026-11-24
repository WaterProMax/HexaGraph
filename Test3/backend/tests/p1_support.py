"""Shared offline fixtures for the P1 review-fix regression suite.

Everything here is local-only: scripted providers, temporary directories and
fake runners. No test in this module may reach the network or a real model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.execution.simulation import ExecutionPolicy
from app.schemas.execution_grant import ExecutionGrant
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def make_bench(data_dir: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        data_dir,
        # Test fixture policy: legacy executor is authorized only inside these
        # isolated tmp dirs. Product Workbench keeps the real default (denied).
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def make_card(
    code: str,
    *,
    write_set: list[str] | None = None,
    acceptance_cmd: list[str] | None = None,
) -> TaskCard:
    write_set = list(write_set or [f"tests/test_{code.lower().replace('-', '_')}.py"])
    acceptance = [
        AcceptanceCheck(
            cmd=list(acceptance_cmd or ["python", "-m", "pytest", "-q"]),
            pass_criteria="ok",
            from_criterion="F1",
        )
    ]
    return TaskCard.model_validate(
        {
            "code": code,
            "title": code,
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "d",
            "write_set": write_set,
            "outputs": write_set,
            "acceptance": acceptance,
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


def install_plan(bench: Workbench, run: Any, codes: list[str]) -> dict[str, Any]:
    cards = [make_card(code) for code in codes]
    run.artifacts["plan"] = TaskGraph(tasks=cards).model_dump()
    bench._materialize_tasks(run)
    return run


def make_grant(
    run_id: str,
    task_codes: list[str],
    *,
    status: str = "active",
    hashes: dict[str, str] | None = None,
    allowed_tool_refs: list[str] | None = None,
) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id=f"G-{'-'.join(task_codes)}-{status}",
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=list(task_codes),
        approved_baseline_hashes=dict(hashes or {"PLAN": "aaa"}),
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=list(allowed_tool_refs or []),
        status=status,  # type: ignore[arg-type]
        created_at="2026-11-19T00:00:00+00:00",
    )


async def persist_granted_profile(
    bench: Workbench,
    run: Any,
    hashes: dict[str, str] | None = None,
) -> None:
    """Use the durable server-side writer when present; fall back to the fixture setter.

    F-01 must reproduce on the pre-fix tree (setter only).  F-02 adds the durable
    writer and this helper then exercises persistence instead of the fixture.
    """
    payload = dict(hashes or {"PLAN": "aaa"})
    writer = getattr(bench, "persist_run_execution_state", None)
    if writer is not None:
        await writer(run.id, "granted_v1", payload)
        run.artifacts["baseline_provenance"] = "fixture"
        return
    from app.execution.run_profile import set_approved_baseline_hashes, set_run_execution_profile

    set_run_execution_profile(run, "granted_v1")
    set_approved_baseline_hashes(run, payload)


__all__ = [
    "install_plan",
    "make_bench",
    "make_card",
    "make_grant",
    "persist_granted_profile",
]