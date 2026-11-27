from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.memory.injection import build_memory_slot
from app.memory.store import MemoryStore
from app.schemas.memory import MemoryCreate
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import MemoryRecordRow


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


async def _add_member(client: AsyncClient, project_id: str, bot_id: str) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": False},
    )
    assert res.status_code == 201, res.text


def _headers(bot_id: str) -> dict[str, str]:
    return {"X-Bot-Id": bot_id}


def _record_body(owner: str, **overrides) -> dict:
    body = {
        "owner_bot_id": owner,
        "visibility": "private",
        "sources": [],
        "body": {"text": "hello"},
        "title": "note",
    }
    body.update(overrides)
    return body


async def _memory_count(bench) -> int:
    async with bench.db_session() as session:
        return (
            await session.execute(select(func.count()).select_from(MemoryRecordRow))
        ).scalar_one()


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_owner_creates_and_lists_private_memory(app) -> None:
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        created = await client.post(
            "/api/memory/records",
            json=_record_body(owner, title="private-note"),
            headers=_headers(owner),
        )
        listed = await client.get("/api/memory/records", headers=_headers(owner))
    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1
    assert created.json()["status"] == "pending"
    assert created.json()["mem_id"] in [item["mem_id"] for item in listed.json()["items"]]


@pytest.mark.asyncio
async def test_other_bot_cannot_read_private_memory(app) -> None:
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        other = await _create_bot(client, "Other")
        created = await client.post(
            "/api/memory/records", json=_record_body(owner), headers=_headers(owner)
        )
    mem_id = created.json()["mem_id"]
    async with _client(app) as client:
        by_id = await client.get(f"/api/memory/records/{mem_id}", headers=_headers(other))
        by_filter = await client.get(
            f"/api/memory/records?owner_bot_id={owner}&visibility=private",
            headers=_headers(other),
        )
    assert by_id.status_code == 403
    assert by_id.json()["error_category"] == "memory_forbidden"
    assert by_filter.status_code == 403
    assert by_filter.json()["error_category"] == "memory_forbidden"


@pytest.mark.asyncio
async def test_published_project_memory_reaches_member_slot(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        member = await _create_bot(client, "Member")
        await _add_member(client, p1, owner)
        await _add_member(client, p1, member)
        created = await client.post(
            "/api/memory/records",
            json=_record_body(
                owner,
                project_id=p1,
                visibility="project",
                title="project-note",
            ),
            headers=_headers(owner),
        )
        published = await client.post(
            f"/api/memory/records/{created.json()['mem_id']}/publish",
            json={"expected_version": 1},
            headers=_headers(owner),
        )
        listed = await client.get("/api/memory/records", headers=_headers(member))
    assert created.status_code == 201, created.text
    assert published.status_code == 200, published.text
    slot = await build_memory_slot(member, project_id=p1, run_id=None, db_path=bench.db_path)
    assert "project-note" in [item["title"] for item in slot]
    assert "project-note" in [item["title"] for item in listed.json()["items"]]


@pytest.mark.asyncio
async def test_other_private_title_never_enters_slot_or_list(app) -> None:
    bench = app.state.workbench
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        other = await _create_bot(client, "Other")
        await client.post(
            "/api/memory/records",
            json=_record_body(owner, title="secret-note"),
            headers=_headers(owner),
        )
        listed = await client.get("/api/memory/records", headers=_headers(other))
    slot = await build_memory_slot(other, project_id=None, run_id=None, db_path=bench.db_path)
    assert "secret-note" not in [item["title"] for item in slot]
    assert "secret-note" not in [item["title"] for item in listed.json()["items"]]


@pytest.mark.asyncio
async def test_secret_body_is_rejected_without_row(app) -> None:
    bench = app.state.workbench
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        res = await client.post(
            "/api/memory/records",
            json=_record_body(owner, body={"api_key": "sk-leak"}),
            headers=_headers(owner),
        )
    assert res.status_code == 400
    assert res.json()["error_category"] == "secret_in_body"
    assert await _memory_count(bench) == 0


@pytest.mark.asyncio
async def test_concurrent_publish_has_one_winner(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        await _add_member(client, p1, owner)
        created = await client.post(
            "/api/memory/records",
            json=_record_body(owner, project_id=p1, visibility="project"),
            headers=_headers(owner),
        )
    mem_id = created.json()["mem_id"]
    async with _client(app) as first, _client(app) as second:
        left, right = await asyncio.gather(
            first.post(
                f"/api/memory/records/{mem_id}/publish",
                json={"expected_version": 1},
                headers=_headers(owner),
            ),
            second.post(
                f"/api/memory/records/{mem_id}/publish",
                json={"expected_version": 1},
                headers=_headers(owner),
            ),
        )
    assert sorted([left.status_code, right.status_code]) == [200, 409]
    conflict = left if left.status_code == 409 else right
    assert conflict.json()["error_category"] == "memory_version_conflict"


@pytest.mark.asyncio
async def test_membership_removal_through_http_keeps_private_history(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        b1 = await _create_bot(client, "B1")
        b2 = await _create_bot(client, "B2")
        await _add_member(client, p1, b1)
        await _add_member(client, p1, b2)
        project = await client.post(
            "/api/memory/records",
            json=_record_body(b1, project_id=p1, visibility="project", title="project-note"),
            headers=_headers(b1),
        )
    async with bench.db_session() as session:
        store = MemoryStore(session)
        private = await store.create(
            MemoryCreate(
                owner_bot_id=b1,
                visibility="private",
                sources=[],
                body={"text": "private-v1"},
                title="private-note",
            )
        )
        await store.append_version(private.mem_id, 1, body={"text": "private-v2"})
        await session.commit()
    before = await _memory_count(bench)

    async with _client(app) as client:
        removed = await client.delete(f"/api/projects/{p1}/memberships/{b1}")
        first = await client.get(
            f"/api/memory/records/{private.mem_id}?version=1", headers=_headers(b1)
        )
        latest = await client.get(f"/api/memory/records/{private.mem_id}", headers=_headers(b1))
        project_denied = await client.get(
            f"/api/memory/records/{project.json()['mem_id']}", headers=_headers(b1)
        )
        bot = await client.get(f"/api/bots/{b1}")
        b2_project = await client.get(
            f"/api/memory/records/{project.json()['mem_id']}", headers=_headers(b2)
        )
    assert removed.status_code == 204
    assert first.status_code == 200 and first.json()["body"] == {"text": "private-v1"}
    assert latest.status_code == 200 and latest.json()["body"] == {"text": "private-v2"}
    assert project_denied.status_code == 403
    assert project_denied.json()["error_category"] == "memory_forbidden"
    assert b2_project.status_code == 200
    assert bot.status_code == 200
    assert await _memory_count(bench) == before


@pytest.mark.asyncio
async def test_missing_bot_header_is_400(app) -> None:
    async with _client(app) as client:
        created = await client.post("/api/memory/records", json=_record_body("x"))
        listed = await client.get("/api/memory/records")
    assert created.status_code == 400
    assert created.json()["error_category"] == "validation_error"
    assert listed.status_code == 400
    assert listed.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_route_error_mapping(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        stranger = await _create_bot(client, "Stranger")
        await _add_member(client, p1, owner)
        unknown_actor = await client.get(
            "/api/memory/records", headers=_headers("no-such-bot")
        )
        unknown_owner = await client.post(
            "/api/memory/records",
            json=_record_body("no-such-bot"),
            headers=_headers(owner),
        )
        missing_project = await client.post(
            "/api/memory/records",
            json=_record_body(owner, project_id="no-such-project", visibility="project"),
            headers=_headers(owner),
        )
        bad_visibility = await client.get(
            "/api/memory/records?visibility=global", headers=_headers(owner)
        )
        created = await client.post(
            "/api/memory/records",
            json=_record_body(owner, project_id=p1, visibility="project"),
            headers=_headers(owner),
        )
        non_member_list = await client.get(
            f"/api/memory/records?project_id={p1}", headers=_headers(stranger)
        )
        bad_version = await client.get(
            f"/api/memory/records/{created.json()['mem_id']}?version=abc",
            headers=_headers(owner),
        )
        bad_expected = await client.post(
            f"/api/memory/records/{created.json()['mem_id']}/publish",
            json={"expected_version": 99},
            headers=_headers(owner),
        )
    assert unknown_actor.status_code == 404
    assert unknown_actor.json()["error_category"] == "bot_not_found"
    assert unknown_owner.status_code == 404
    assert unknown_owner.json()["error_category"] == "bot_not_found"
    assert missing_project.status_code == 404
    assert missing_project.json()["error_category"] == "project_not_found"
    assert bad_visibility.status_code == 400
    assert bad_visibility.json()["error_category"] == "validation_error"
    assert non_member_list.status_code == 403
    assert non_member_list.json()["error_category"] == "memory_forbidden"
    assert bad_version.status_code == 400
    assert bad_version.json()["error_category"] == "validation_error"
    assert bad_expected.status_code == 409
    assert bad_expected.json()["error_category"] == "memory_version_conflict"


@pytest.mark.asyncio
async def test_supersede_http_keeps_old_body_and_returns_pending(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        owner = await _create_bot(client, "Owner")
        await _add_member(client, p1, owner)
        created = await client.post(
            "/api/memory/records",
            json=_record_body(owner, project_id=p1, visibility="project", body={"text": "v1"}),
            headers=_headers(owner),
        )
        mem_id = created.json()["mem_id"]
        await client.post(
            f"/api/memory/records/{mem_id}/publish",
            json={"expected_version": 1},
            headers=_headers(owner),
        )
        superseded = await client.post(
            f"/api/memory/records/{mem_id}/supersede",
            json={"expected_version": 1, "body": {"text": "v2"}, "sources": []},
            headers=_headers(owner),
        )
        old = await client.get(f"/api/memory/records/{mem_id}?version=1", headers=_headers(owner))
        latest = await client.get(f"/api/memory/records/{mem_id}", headers=_headers(owner))
    assert superseded.status_code == 200, superseded.text
    assert superseded.json()["version"] == 2
    assert superseded.json()["status"] == "pending"
    assert old.json()["status"] == "superseded"
    assert old.json()["body"] == {"text": "v1"}
    assert latest.json()["body"] == {"text": "v2"}