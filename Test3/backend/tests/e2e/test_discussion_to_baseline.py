from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
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


def _review_body(reviewer: str, proposal_id: str, *, dissent: list[str] | None = None) -> dict:
    return {
        "reviewer_bot_id": reviewer,
        "proposal_id": proposal_id,
        "scores": {"coverage": 4},
        "score_justification": {"coverage": "ok"},
        "hard_gate_results": {
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        "dissent_items": list(dissent or []),
    }


@pytest.mark.asyncio
async def test_discussion_to_baseline_end_to_end(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path)
    bench = app.state.workbench
    project_id = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = (await client.post("/api/bots", json=_bot_body("Leader"))).json()["bot_id"]
        alice = (await client.post("/api/bots", json=_bot_body("Alice"))).json()["bot_id"]
        bob = (await client.post("/api/bots", json=_bot_body("Bob"))).json()["bot_id"]
        for bot_id, is_leader in ((leader, True), (alice, False), (bob, False)):
            await client.post(
                f"/api/projects/{project_id}/memberships",
                json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": is_leader},
            )
        created = await client.post(
            f"/api/projects/{project_id}/discussion-sessions",
            json={
                "leader_bot_id": leader,
                "participant_bot_ids": [alice, bob],
                "requirement_snapshot": "string requirement",
            },
            headers={"X-Bot-Id": leader},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        grouped = await client.post(
            f"/api/discussion-sessions/{session_id}/group",
            json={"participant_bot_ids": [alice, bob]},
            headers={"X-Bot-Id": leader},
        )
        assert grouped.status_code == 200, grouped.text
        started = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={},
            headers={"X-Bot-Id": leader},
        )
        assert started.status_code == 200, started.text
        alice_proposal = await client.post(
            f"/api/discussion-sessions/{session_id}/proposals",
            json={"author_bot_id": alice, "body_md": "Alice-plan"},
            headers={"X-Bot-Id": alice},
        )
        bob_proposal = await client.post(
            f"/api/discussion-sessions/{session_id}/proposals",
            json={"author_bot_id": bob, "body_md": "Bob-plan"},
            headers={"X-Bot-Id": bob},
        )
        assert alice_proposal.status_code == 201 and bob_proposal.status_code == 201
        first_review = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(bob, alice_proposal.json()["proposal_id"], dissent=["风险X"]),
            headers={"X-Bot-Id": bob},
        )
        second_review = await client.post(
            f"/api/discussion-sessions/{session_id}/reviews",
            json=_review_body(alice, bob_proposal.json()["proposal_id"]),
            headers={"X-Bot-Id": alice},
        )
        assert first_review.status_code == 201 and second_review.status_code == 201
        converged = await client.post(
            f"/api/discussion-sessions/{session_id}/converge",
            json={},
            headers={"X-Bot-Id": leader},
        )
        assert converged.status_code == 200, converged.text
        assert converged.json()["action"] == "submit_human"
        package = await client.post(
            f"/api/discussion-sessions/{session_id}/submit-decision",
            json={"body_md": "# Decision", "dissent_items": ["风险X"]},
            headers={"X-Bot-Id": leader},
        )
        assert package.status_code == 201, package.text
        run = bench.create_run(project_id, "idea")

        async def boom(*args, **kwargs):
            raise AssertionError("approved decision must not schedule or execute")

        monkeypatch.setattr(bench, "schedule_once", boom)
        monkeypatch.setattr(bench, "execute_task", boom)
        resolved = await client.post(
            f"/api/discussion-sessions/{session_id}/resolve",
            json={"decision": "approved", "run_id": run.id},
            headers={"X-Bot-Id": leader},
        )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "approved"
    assert run.approved_baseline_hashes["DecisionPackage"] == package.json()["sha256"]
    assert bench.execution_safety_ready is False
    assert bench.gateway.provider.calls == []