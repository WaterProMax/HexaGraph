from __future__ import annotations

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion import driver
from app.discussion.messages import LOG
from app.discussion.session_store import DiscussionSessionStore
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _bot_body(name: str) -> dict:
    return {
        "display_name": name,
        "role_template": "developer",
        "provider_ref": "dashscope",
        "model": "qwen-plus",
        "slot": "coder",
        "secret_ref": "DASHSCOPE_API_KEY",
    }


def _headers(bot_id: str) -> dict[str, str]:
    return {"X-Bot-Id": bot_id}


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    return app


async def _setup(app, names: list[str]):
    bench = app.state.workbench
    project_id = bench.create_project("P1")["id"]
    client = _client(app)
    bots = []
    for name in names:
        res = await client.post("/api/bots", json=_bot_body(name))
        assert res.status_code == 201, res.text
        bots.append(res.json()["bot_id"])
    for index, bot_id in enumerate(bots):
        res = await client.post(
            f"/api/projects/{project_id}/memberships",
            json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": index == 0},
        )
        assert res.status_code == 201, res.text
    created = await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json={
            "leader_bot_id": bots[0],
            "participant_bot_ids": bots,
            "requirement_snapshot": "做一个期末周自习座位预约系统",
        },
        headers=_headers(bots[0]),
    )
    assert created.status_code == 201, created.text
    return client, bots, created.json()["session_id"]


async def _get(bench, session_id: str):
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _messages(bench, session_id: str) -> list[dict]:
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
        return [{"kind": row.kind, "payload": row.payload or {}} for row in rows]


async def _wait(bench, session_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while driver.is_running(bench, session_id) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_control_requires_header_leader_and_existing_session(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        missing = await client.post(f"/api/discussion-sessions/{session_id}/run")
        assert missing.status_code == 400
        assert missing.json()["error_category"] == "validation_error"

        not_found = await client.post(
            "/api/discussion-sessions/nope/run", headers=_headers(bots[0])
        )
        assert not_found.status_code == 404
        assert not_found.json()["error_category"] == "session_not_found"

        for action in ("run", "pause", "resume"):
            res = await client.post(
                f"/api/discussion-sessions/{session_id}/{action}",
                headers=_headers(bots[1]),
            )
            assert res.status_code == 403, res.text
            assert res.json()["error_category"] == "forbidden"

        terminate = await client.post(
            f"/api/discussion-sessions/{session_id}/terminate",
            json={"confirm": True},
            headers=_headers(bots[1]),
        )
        assert terminate.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_run_returns_409_for_terminal_state(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get(session_id)
            await store.save(record.model_copy(update={"status": "approved"}))
            await session.commit()
        res = await client.post(
            f"/api/discussion-sessions/{session_id}/run", headers=_headers(bots[0])
        )
    finally:
        await client.aclose()

    assert res.status_code == 409
    assert res.json()["error_category"] == "invalid_status"


@pytest.mark.asyncio
async def test_run_then_pause_stops_the_driver(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        ran = await client.post(
            f"/api/discussion-sessions/{session_id}/run", headers=_headers(bots[0])
        )
        assert ran.status_code == 200, ran.text
        assert ran.json()["running"] is True
        assert ran.json()["session"]["session_id"] == session_id

        paused = await client.post(
            f"/api/discussion-sessions/{session_id}/pause", headers=_headers(bots[0])
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["paused"] is True
        await _wait(bench, session_id)
        assert not driver.is_running(bench, session_id)
    finally:
        await client.aclose()

    messages = await _messages(bench, session_id)
    assert any(m["payload"].get("event") == "paused" for m in messages)


@pytest.mark.asyncio
async def test_resume_skips_bot_and_terminate_requires_confirm(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Bob", "Alice"])
    bench = app.state.workbench
    try:
        await driver.pause_session(bench, session_id)
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"skip_bot_ids": [bots[2]]},
            headers=_headers(bots[0]),
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["paused"] is False
        assert resumed.json()["participant_bot_ids"] == [bots[0], bots[1]]
        await _wait(bench, session_id)

        missing_confirm = await client.post(
            f"/api/discussion-sessions/{session_id}/terminate",
            json={},
            headers=_headers(bots[0]),
        )
        assert missing_confirm.status_code == 400
        assert missing_confirm.json()["error_category"] == "validation_error"

        false_confirm = await client.post(
            f"/api/discussion-sessions/{session_id}/terminate",
            json={"confirm": False},
            headers=_headers(bots[0]),
        )
        assert false_confirm.status_code == 400

        terminated = await client.post(
            f"/api/discussion-sessions/{session_id}/terminate",
            json={"confirm": True},
            headers=_headers(bots[0]),
        )
        assert terminated.status_code == 200, terminated.text
        assert terminated.json()["status"] == "terminated"

        again = await client.post(
            f"/api/discussion-sessions/{session_id}/terminate",
            json={"confirm": True},
            headers=_headers(bots[0]),
        )
        assert again.status_code == 200
        assert again.json()["status"] == "terminated"
    finally:
        await client.aclose()

    messages = await _messages(bench, session_id)
    skipped = [m for m in messages if m["payload"].get("event") == "bot_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["payload"]["bot_id"] == bots[2]
    terminated_events = [
        m for m in messages if m["payload"].get("event") == "terminated"
    ]
    assert len(terminated_events) == 1
    record = await _get(bench, session_id)
    assert record is not None
    assert record.status == "terminated"


@pytest.mark.asyncio
async def test_resume_below_two_participants_terminates(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"skip_bot_ids": [bots[1]]},
            headers=_headers(bots[0]),
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "terminated"
        assert resumed.json()["participant_bot_ids"] == [bots[0]]
    finally:
        await client.aclose()

    messages = await _messages(bench, session_id)
    assert any(
        m["payload"].get("event") == "bot_skipped" for m in messages
    )
    assert any(
        m["payload"].get("event") == "terminated" for m in messages
    )
    assert not driver.is_running(bench, session_id)

@pytest.mark.asyncio
async def test_run_resumes_a_paused_session(app) -> None:
    client, bots, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        await driver.pause_session(bench, session_id)
        res = await client.post(
            f"/api/discussion-sessions/{session_id}/run", headers=_headers(bots[0])
        )
        assert res.status_code == 200, res.text
        assert res.json()["session"]["paused"] is False
        await _wait(bench, session_id)
        await driver.terminate_session(bench, session_id)
    finally:
        await client.aclose()
