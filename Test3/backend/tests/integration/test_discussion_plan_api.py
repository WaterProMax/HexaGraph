"""Card 1: POST /discussion-sessions/{id}/plan behaviour and workflow projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion import planning
from app.discussion.models import DecisionPackage, DiscussionBudget, DiscussionSession
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


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    return app


async def _project_with_leader(app) -> tuple[AsyncClient, str, str]:
    bench = app.state.workbench
    project_id = bench.create_project("P1")["id"]
    client = _client(app)
    leader = (await client.post("/api/bots", json=_bot_body("Leader"))).json()["bot_id"]
    await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": leader, "role_in_project": "dev", "is_leader": True},
    )
    return client, project_id, leader


async def _seed_session(bench, project_id: str, leader: str, *, approved: bool) -> str:
    session = DiscussionSession(
        session_id="S-1",
        project_id=project_id,
        leader_bot_id=leader,
        participant_bot_ids=[leader],
        status="approved" if approved else "converged_pending_human",
        current_round=1,
        budget=DiscussionBudget(),
        requirement_snapshot_hash="h" * 64,
        requirement_text="做一个自习座位系统",
        decision_package=(
            DecisionPackage(
                decision_id="D-1",
                session_id="S-1",
                requirement_snapshot_hash="h" * 64,
                proposal_ids=["p1"],
                dissent_items=[],
                hard_gate_summary={"coverage": True},
                body_md="# 需求",
                sha256="d" * 64,
            )
            if approved
            else None
        ),
    )
    async with bench.db_session() as db:
        await DiscussionSessionStore(db).create(session)
        await db.commit()
    return session.session_id


def _stub_generate(monkeypatch) -> dict:
    calls = {"n": 0}

    class _Doc:
        def model_dump(self) -> dict:
            return {}

    async def fake_generate(bench, record, **_kwargs):
        calls["n"] += 1
        return SimpleNamespace(spec=_Doc(), design=_Doc(), plan=_Doc())

    monkeypatch.setattr(planning, "generate", fake_generate)
    return calls


@pytest.mark.asyncio
async def test_plan_rejected_without_approved_spec_and_creates_no_run(app, monkeypatch) -> None:
    calls = _stub_generate(monkeypatch)
    bench = app.state.workbench
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=False)

    res = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "invalid_status"
    assert "需先确认需求规格" in res.json()["detail"]
    assert bench.runs == {}
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_plan_is_idempotent_and_projects_plan_pending(app, monkeypatch) -> None:
    calls = _stub_generate(monkeypatch)
    bench = app.state.workbench
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=True)

    first = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )
    second = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    run_id = first.json()["run_id"]
    assert second.json()["run_id"] == run_id
    assert calls["n"] == 1
    assert run_id in bench.runs

    run_view = await client.get(f"/api/runs/{run_id}")
    assert run_view.json()["workflow"]["stage"] == "plan_pending"
    monitor = await client.get(f"/api/runs/{run_id}/monitor")
    assert monitor.json()["workflow"]["stage"] == "plan_pending"
    session_view = await client.get(
        f"/api/discussion-sessions/{session_id}", headers={"X-Bot-Id": leader}
    )
    assert session_view.json()["workflow"]["run_id"] == run_id
    assert session_view.json()["workflow"]["stage"] == "plan_pending"