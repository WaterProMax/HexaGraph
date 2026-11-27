"""Card 6: automatic-loop rejections are observable and de-duplicated."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.p1_support import install_plan


@pytest.mark.asyncio
async def test_loop_emits_one_rejection_event_per_reason(tmp_path: Path) -> None:
    bench = Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    project = bench.create_project("loop")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    bench.schedule_interval = 0.01
    bench.start_loop()
    try:
        await asyncio.sleep(0.08)
    finally:
        await bench.stop_loop()

    rejected = [event for event in run.events if event["kind"] == "schedule.rejected"]
    assert len(rejected) == 1
    assert rejected[0]["payload"]["category"] == "profile_not_granted_v1"
    assert run.tasks["T-01"]["state"] == "ready"