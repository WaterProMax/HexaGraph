"""P6 read-only GETs added for the front-end workstation.

These are the only backend additions in P6: listing defects/acceptances and the
discussion session/review reads the workbench needs.  No writes, no gate change.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import DiscussionReviewRow

EVIDENCE = "file://logs/t06.log"


def _card(code: str) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": code,
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "d",
            "write_set": [f"src/{code.lower()}.py"],
            "outputs": [f"src/{code.lower()}.py"],
            "acceptance": [
                AcceptanceCheck(
                    cmd=["python", "-m", "pytest", f"tests/test_{code.lower()}.py", "-q"],
                    pass_criteria="ok",
                    from_criterion="F1",
                )
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


@pytest.fixture
async def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    await app.state.workbench._ensure_db()
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _headers(bot_id: str) -> dict[str, str]:
    return {"X-Bot-Id": bot_id}


def _run(app) -> str:
    bench = app.state.workbench
    project = bench.create_project("p6-get")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01")]).model_dump()
    bench._materialize_tasks(run)
    task = run.tasks["T-01"]
    task["state"] = "done"
    task["evidence"] = [{"kind": "command", "summary": "ok", "path": EVIDENCE}]
    return run.id


async def _create_bot(client: AsyncClient, name: str) -> str:
    res = await client.post(
        "/api/bots",
        json={
            "display_name": name,
            "role_template": "developer",
            "provider_ref": "dashscope",
            "model": "qwen-plus",
            "slot": "coder",
            "secret_ref": "DASHSCOPE_API_KEY",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


async def _add_member(client: AsyncClient, project_id: str, bot_id: str, *, leader: bool = False) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": leader},
    )
    assert res.status_code == 201, res.text


async def _session(app, client: AsyncClient) -> tuple[str, str, str, str]:
    bench = app.state.workbench
    project = bench.create_project("p6-discussion")
    project_id = project["id"]
    leader = await _create_bot(client, "Leader L")
    peer = await _create_bot(client, "Peer P")
    await _add_member(client, project_id, leader, leader=True)
    await _add_member(client, project_id, peer)
    res = await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json={
            "leader_bot_id": leader,
            "participant_bot_ids": [leader, peer],
            "requirement_snapshot": {"text": "requirement"},
        },
        headers=_headers(leader),
    )
    assert res.status_code == 201, res.text
    return project_id, res.json()["session_id"], leader, peer


@pytest.mark.asyncio
async def test_defects_and_acceptances_are_listed(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        created_acceptance = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json={
                "module_id": "M1",
                "task_codes": ["T-01"],
                "status": "accepted",
                "evidence_uris": [EVIDENCE],
                "reviewer": "bot-r",
            },
            headers=_headers("bot-r"),
        )
        assert created_acceptance.status_code == 201, created_acceptance.text
        created_defect = await client.post(
            f"/api/runs/{run_id}/defects",
            json={"task_code": "T-01", "module_id": "M1", "evidence_uris": [EVIDENCE], "detail": "缺回归"},
            headers=_headers("bot-r"),
        )
        assert created_defect.status_code == 201, created_defect.text

        defects = await client.get(f"/api/runs/{run_id}/defects", headers=_headers("bot-r"))
        acceptances = await client.get(f"/api/runs/{run_id}/module-acceptances", headers=_headers("bot-r"))

    assert defects.status_code == 200, defects.text
    assert [item["defect_id"] for item in defects.json()["items"]] == [created_defect.json()["defect_id"]]
    assert acceptances.status_code == 200, acceptances.text
    assert [item["acceptance_id"] for item in acceptances.json()["items"]] == [
        created_acceptance.json()["acceptance_id"]
    ]


@pytest.mark.asyncio
async def test_defect_listing_requires_header_and_existing_run(app) -> None:
    async with _client(app) as client:
        missing = await client.get("/api/runs/whatever/defects")
        unknown = await client.get("/api/runs/whatever/defects", headers=_headers("bot-r"))
    assert missing.status_code == 400
    assert missing.json()["error_category"] == "validation_error"
    assert unknown.status_code == 404
    assert unknown.json()["error_category"] == "run_not_found"


@pytest.mark.asyncio
async def test_discussion_session_reads(app) -> None:
    async with _client(app) as client:
        project_id, session_id, leader, peer = await _session(app, client)
        listed = await client.get(f"/api/projects/{project_id}/discussion-sessions", headers=_headers(leader))
        found = await client.get(f"/api/discussion-sessions/{session_id}", headers=_headers(peer))
        missing_header = await client.get(f"/api/discussion-sessions/{session_id}")
        unknown = await client.get("/api/discussion-sessions/nope", headers=_headers(leader))
        outsider = await client.get(f"/api/discussion-sessions/{session_id}", headers=_headers("outsider"))
        unknown_project = await client.get(
            "/api/projects/no-such-project/discussion-sessions", headers=_headers(leader)
        )

    assert listed.status_code == 200, listed.text
    assert [item["session_id"] for item in listed.json()["items"]] == [session_id]
    assert found.status_code == 200, found.text
    assert found.json()["session_id"] == session_id
    assert missing_header.status_code == 400
    assert unknown.status_code == 404
    assert unknown.json()["error_category"] == "session_not_found"
    assert outsider.status_code == 403
    assert outsider.json()["error_category"] == "not_participant"
    assert unknown_project.status_code == 404
    assert unknown_project.json()["error_category"] == "project_not_found"


@pytest.mark.asyncio
async def test_review_listing_requires_participant(app) -> None:
    async with _client(app) as client:
        _, session_id, leader, peer = await _session(app, client)
        empty = await client.get(f"/api/discussion-sessions/{session_id}/reviews", headers=_headers(peer))
        outsider = await client.get(f"/api/discussion-sessions/{session_id}/reviews", headers=_headers("outsider"))

        async with app.state.workbench.db_session() as session:
            session.add(
                DiscussionReviewRow(
                    review_id="review-1",
                    session_id=session_id,
                    reviewer_bot_id=peer,
                    proposal_id="proposal-1",
                    payload={
                        "reviewer_bot_id": peer,
                        "proposal_id": "proposal-1",
                        "scores": {"coverage": 3},
                        "score_justification": {"coverage": "覆盖了主路径"},
                        "hard_gate_results": {
                            "coverage": True,
                            "conflicts_closed_or_recorded": True,
                            "evidence_complete": False,
                        },
                        "dissent_items": ["缺边界用例"],
                    },
                )
            )
            await session.commit()
        filled = await client.get(f"/api/discussion-sessions/{session_id}/reviews", headers=_headers(leader))

    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert outsider.status_code == 403
    assert outsider.json()["error_category"] == "not_participant"
    assert filled.status_code == 200, filled.text
    assert filled.json()["items"][0]["dissent_items"] == ["缺边界用例"]
    # Blind-round safety: the reviews payload never carries proposal body text.
    assert "body_md" not in filled.json()["items"][0]