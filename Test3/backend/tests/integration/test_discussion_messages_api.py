from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.api import routes_discussion_events as events
from app.discussion.messages import LOG
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _bot_body(name: str) -> dict:
    return {
        "display_name": name,
        "role_template": "developer",
        "provider_ref": "dashscope",
        "model": "qwen-plus",
        "slot": "coder",
        "secret_ref": "DASHSCOPE_API_KEY",
    }


async def _create_bot(client: AsyncClient, name: str) -> str:
    res = await client.post("/api/bots", json=_bot_body(name))
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


async def _add_member(client: AsyncClient, project_id: str, bot_id: str, *, leader: bool = False) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": leader},
    )
    assert res.status_code == 201, res.text


async def _create_session(client: AsyncClient, project_id: str, leader: str, participants: list[str]) -> str:
    res = await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json={
            "leader_bot_id": leader,
            "participant_bot_ids": participants,
            "requirement_snapshot": {"text": "requirement"},
        },
        headers={"X-Bot-Id": leader},
    )
    assert res.status_code == 201, res.text
    return res.json()["session_id"]


async def _setup(app) -> tuple[str, str, str, str]:
    bench = app.state.workbench
    project_id = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, project_id, leader, leader=True)
        await _add_member(client, project_id, alice)
        await _add_member(client, project_id, bob)
        session_id = await _create_session(client, project_id, leader, [leader, alice, bob])
    return session_id, leader, alice, bob


async def _append(
    bench,
    session_id: str,
    kind: str,
    *,
    bot_id: str | None = None,
    round_no: int = 0,
    payload: dict | None = None,
) -> int:
    async with bench.db_session() as session:
        row = await LOG.append(
            session, session_id, kind, bot_id=bot_id, round_no=round_no, payload=payload
        )
        seq = row.seq
        await session.commit()
    return seq


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_messages_empty_list(app) -> None:
    session_id, leader, _, _ = await _setup(app)
    async with _client(app) as client:
        res = await client.get(
            f"/api/discussion-sessions/{session_id}/messages", headers={"X-Bot-Id": leader}
        )
    assert res.status_code == 200, res.text
    assert res.json() == {"items": []}


@pytest.mark.asyncio
async def test_messages_after_filter(app) -> None:
    session_id, leader, alice, _ = await _setup(app)
    bench = app.state.workbench
    await _append(bench, session_id, "system", payload={"event": "session_started"})
    await _append(bench, session_id, "proposal", bot_id=alice, round_no=1, payload={"proposal_id": "p1"})
    await _append(bench, session_id, "review", bot_id=leader, round_no=1, payload={"total": 12})
    async with _client(app) as client:
        all_items = await client.get(
            f"/api/discussion-sessions/{session_id}/messages?after=0", headers={"X-Bot-Id": leader}
        )
        tail = await client.get(
            f"/api/discussion-sessions/{session_id}/messages?after=2", headers={"X-Bot-Id": alice}
        )
    assert [item["seq"] for item in all_items.json()["items"]] == [1, 2, 3]
    assert [item["kind"] for item in all_items.json()["items"]] == ["system", "proposal", "review"]
    first = all_items.json()["items"][0]
    assert first["session_id"] == session_id
    assert first["payload"] == {"event": "session_started"}
    assert all_items.json()["items"][2]["round"] == 1
    assert [item["seq"] for item in tail.json()["items"]] == [3]


@pytest.mark.asyncio
async def test_messages_invalid_after_is_treated_as_zero(app) -> None:
    session_id, leader, _, _ = await _setup(app)
    bench = app.state.workbench
    for kind in ("system", "proposal"):
        await _append(bench, session_id, kind)
    async with _client(app) as client:
        negative = await client.get(
            f"/api/discussion-sessions/{session_id}/messages?after=-4", headers={"X-Bot-Id": leader}
        )
        garbage = await client.get(
            f"/api/discussion-sessions/{session_id}/messages?after=abc", headers={"X-Bot-Id": leader}
        )
    assert [item["seq"] for item in negative.json()["items"]] == [1, 2]
    assert [item["seq"] for item in garbage.json()["items"]] == [1, 2]


@pytest.mark.asyncio
async def test_messages_auth_and_not_found(app) -> None:
    session_id, _, _, _ = await _setup(app)
    async with _client(app) as client:
        missing = await client.get(f"/api/discussion-sessions/{session_id}/messages")
        outsider = await client.get(
            f"/api/discussion-sessions/{session_id}/messages", headers={"X-Bot-Id": "ghost"}
        )
        unknown = await client.get(
            "/api/discussion-sessions/no-such/messages", headers={"X-Bot-Id": "ghost"}
        )
    assert missing.status_code == 400
    assert missing.json()["error_category"] == "validation_error"
    assert outsider.status_code == 403
    assert outsider.json()["error_category"] == "not_participant"
    assert unknown.status_code == 404
    assert unknown.json()["error_category"] == "session_not_found"


@pytest.mark.asyncio
async def test_frame_shape_is_strict(app) -> None:
    session_id, _, alice, _ = await _setup(app)
    bench = app.state.workbench
    await _append(bench, session_id, "review", bot_id=alice, round_no=2, payload={"total": 9})
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
    frame = events._frame(rows[0])
    assert frame.endswith("\n\n")
    lines = frame[: -2].split("\n")
    assert lines[0] == "id: 1"
    assert lines[1] == "event: message"
    assert lines[2].startswith("data: ")
    data = json.loads(lines[2][len("data: ") :])
    assert data["seq"] == 1 and data["kind"] == "review" and data["payload"] == {"total": 9}


@pytest.mark.asyncio
async def test_event_stream_replays_after_and_pushes_live(app) -> None:
    session_id, leader, _, _ = await _setup(app)
    bench = app.state.workbench
    for kind in ("system", "proposal", "review"):
        await _append(bench, session_id, kind)

    stream = events.event_stream(bench, session_id, 2)
    try:
        assert await stream.__anext__() == ": ping\n\n"
        frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert "id: 3\n" in frame
        assert "id: 1\n" not in frame and "id: 2\n" not in frame

        pending = asyncio.create_task(stream.__anext__())
        await _append(bench, session_id, "leader", bot_id=leader, payload={"action": "submit"})
        live = await asyncio.wait_for(pending, timeout=1)
        assert "id: 4\n" in live and "leader" in live
    finally:
        await stream.aclose()
    assert not LOG._subs.get(session_id)


@pytest.mark.asyncio
async def test_event_stream_replays_from_start(app) -> None:
    session_id, _, _, _ = await _setup(app)
    bench = app.state.workbench
    for kind in ("system", "proposal", "review"):
        await _append(bench, session_id, kind)

    stream = events.event_stream(bench, session_id, 0)
    try:
        assert await stream.__anext__() == ": ping\n\n"
        frames = [await asyncio.wait_for(stream.__anext__(), timeout=1) for _ in range(3)]
    finally:
        await stream.aclose()
    assert [frame.split("\n", 1)[0] for frame in frames] == ["id: 1", "id: 2", "id: 3"]
    for seq, frame in enumerate(frames, start=1):
        assert "event: message\n" in frame
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        assert json.loads(data_line[len("data: ") :])["seq"] == seq


@pytest.mark.asyncio
async def test_event_stream_heartbeat_when_idle(app, monkeypatch) -> None:
    session_id, _, _, _ = await _setup(app)
    bench = app.state.workbench
    monkeypatch.setattr(events, "HEARTBEAT_SECONDS", 0.02)
    stream = events.event_stream(bench, session_id, 0)
    try:
        assert await stream.__anext__() == ": ping\n\n"
        assert await asyncio.wait_for(stream.__anext__(), timeout=1) == ": ping\n\n"
    finally:
        await stream.aclose()
    assert not LOG._subs.get(session_id)


def _short_stream(monkeypatch) -> None:
    real = events.event_stream

    async def finite(bench, session_id: str, after_seq: int = 0):
        agen = real(bench, session_id, after_seq)
        try:
            for _ in range(3):
                yield await agen.__anext__()
        finally:
            await agen.aclose()

    monkeypatch.setattr(events, "event_stream", finite)
    monkeypatch.setattr(events, "HEARTBEAT_SECONDS", 0.02)


@pytest.mark.asyncio
async def test_events_bot_id_query_and_last_event_id(app, monkeypatch) -> None:
    session_id, leader, alice, _ = await _setup(app)
    bench = app.state.workbench
    for kind in ("system", "proposal", "review"):
        await _append(bench, session_id, kind)
    _short_stream(monkeypatch)
    async with _client(app) as client:
        by_query = await client.get(
            f"/api/discussion-sessions/{session_id}/events?bot_id={alice}",
            headers={"Last-Event-ID": "2"},
        )
        by_header = await client.get(
            f"/api/discussion-sessions/{session_id}/events",
            headers={"X-Bot-Id": leader, "Last-Event-ID": "3"},
        )
        garbage = await client.get(
            f"/api/discussion-sessions/{session_id}/events?bot_id={alice}",
            headers={"Last-Event-ID": "not-a-number"},
        )
    assert by_query.status_code == 200, by_query.text
    assert by_query.headers["content-type"].startswith("text/event-stream")
    assert by_query.text.startswith(": ping\n\n")
    assert "id: 3\n" in by_query.text and "event: message\n" in by_query.text
    assert "id: 1\n" not in by_query.text and "id: 2\n" not in by_query.text
    data_line = next(line for line in by_query.text.splitlines() if line.startswith("data: "))
    assert json.loads(data_line[len("data: ") :])["seq"] == 3
    assert by_header.status_code == 200, by_header.text
    assert "id: 1\n" not in by_header.text
    assert garbage.status_code == 200, garbage.text
    assert "id: 1\n" in garbage.text and "id: 2\n" in garbage.text


@pytest.mark.asyncio
async def test_events_auth_and_not_found(app) -> None:
    session_id, _, _, _ = await _setup(app)
    async with _client(app) as client:
        missing = await client.get(f"/api/discussion-sessions/{session_id}/events")
        outsider = await client.get(
            f"/api/discussion-sessions/{session_id}/events?bot_id=ghost"
        )
        unknown = await client.get("/api/discussion-sessions/no-such/events?bot_id=ghost")
    assert missing.status_code == 400
    assert missing.json()["error_category"] == "validation_error"
    assert outsider.status_code == 403
    assert outsider.json()["error_category"] == "not_participant"
    assert unknown.status_code == 404
    assert unknown.json()["error_category"] == "session_not_found"


def test_parse_seq_and_resolve_actor() -> None:
    assert events._parse_seq(None) == 0
    assert events._parse_seq("-3") == 0
    assert events._parse_seq("7") == 7
    assert events._parse_seq("garbage") == 0
    assert events._resolve_actor(" header-bot ", "query-bot") == "header-bot"
    assert events._resolve_actor("", " query-bot ") == "query-bot"
    assert events._resolve_actor(None, None) is None