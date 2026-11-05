from __future__ import annotations

import asyncio

import pytest

from app.events.bus import EventBus, rebuild_task_states
from app.storage.db import create_all, make_engine, session_factory, sqlite_url
from app.storage.models import EventRow, ProjectRow, RunRow
from app.storage.repos import EventRepo


@pytest.mark.asyncio
async def test_event_seq_concurrent(tmp_path) -> None:
    engine = make_engine(sqlite_url(tmp_path / "t.db"))
    await create_all(engine)
    factory = session_factory(engine)
    async with factory() as session:
        session.add(ProjectRow(id="p", name="p", profile="python-pytest"))
        session.add(RunRow(id="r", project_id="p", idea="x", limits_json="{}", status="active", current_stage="0", revision=1, paused=0))
        await session.commit()
    bus = EventBus()

    async def emit_one(i: int) -> None:
        async with factory() as session:
            await bus.emit(session, "r", "stage.started", str(i), {"i": i})
            await session.commit()

    await asyncio.gather(*[emit_one(i) for i in range(50)])
    async with factory() as session:
        rows = await EventRepo(session).after("r", 0)
    seqs = [row.seq for row in rows]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) == 50


@pytest.mark.asyncio
async def test_rebuild_task_states(tmp_path) -> None:
    events = [
        EventRow(run_id="r", seq=1, kind="task.state_changed", subject="T-01", payload_json='{"code":"T-01","event":"deps_met","from":"pending"}'),
        EventRow(run_id="r", seq=2, kind="task.state_changed", subject="T-01", payload_json='{"code":"T-01","event":"scheduled","from":"ready"}'),
        EventRow(run_id="r", seq=3, kind="task.state_changed", subject="T-01", payload_json='{"code":"T-01","event":"code_finished","from":"running"}'),
        EventRow(run_id="r", seq=4, kind="task.state_changed", subject="T-01", payload_json='{"code":"T-01","event":"accepted","from":"verifying"}'),
    ]
    assert rebuild_task_states(events, {"T-01": "pending"})["T-01"] == "done"
