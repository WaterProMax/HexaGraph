from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.runtime import RoleRegistry
from app.discussion.session_store import DiscussionSessionStore
from app.execution.baseline import hash_artifact
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import DiscussionSessionRow


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


async def _add_member(
    client: AsyncClient, project_id: str, bot_id: str, *, leader: bool = False
) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": leader},
    )
    assert res.status_code == 201, res.text


def _headers(bot_id: str) -> dict[str, str]:
    return {"X-Bot-Id": bot_id}


def _session_body(leader: str, participants: list[str], **overrides) -> dict:
    body = {
        "leader_bot_id": leader,
        "participant_bot_ids": participants,
        "requirement_snapshot": {"text": "requirement"},
    }
    body.update(overrides)
    return body


async def _create_session(
    client: AsyncClient,
    project_id: str,
    leader: str,
    participants: list[str],
    **overrides,
):
    return await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json=_session_body(leader, participants, **overrides),
        headers=_headers(leader),
    )


async def _start_round(client: AsyncClient, session_id: str, actor: str):
    return await client.post(
        f"/api/discussion-sessions/{session_id}/rounds/start",
        json={},
        headers=_headers(actor),
    )


async def _submit_proposal(
    client: AsyncClient, session_id: str, actor: str, author: str, body_md: str
):
    return await client.post(
        f"/api/discussion-sessions/{session_id}/proposals",
        json={"author_bot_id": author, "body_md": body_md},
        headers=_headers(actor),
    )


async def _session_count(bench) -> int:
    async with bench.db_session() as session:
        return (
            await session.execute(select(func.count()).select_from(DiscussionSessionRow))
        ).scalar_one()


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.mark.asyncio
async def test_create_session_and_group(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        await _add_member(client, p1, bob)
        created = await _create_session(client, p1, leader, [leader, alice, bob])
        sid = created.json()["session_id"]
        grouped = await client.post(
            f"/api/discussion-sessions/{sid}/group",
            json={"participant_bot_ids": [leader, alice]},
            headers=_headers(leader),
        )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    assert created.json()["current_round"] == 0
    assert created.json()["budget"]["max_rounds"] == 3
    assert grouped.status_code == 200, grouped.text
    assert grouped.json()["status"] == "grouping"
    assert grouped.json()["participant_bot_ids"] == [leader, alice]


@pytest.mark.asyncio
async def test_non_leader_cannot_group(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        await _add_member(client, p1, bob)
        created = await _create_session(client, p1, leader, [leader, alice, bob])
        res = await client.post(
            f"/api/discussion-sessions/{created.json()['session_id']}/group",
            json={"participant_bot_ids": [alice]},
            headers=_headers(alice),
        )
    assert res.status_code == 403
    assert res.json()["error_category"] == "forbidden"


@pytest.mark.asyncio
async def test_leader_must_be_project_leader(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        res = await client.post(
            f"/api/projects/{p1}/discussion-sessions",
            json=_session_body(alice, [leader, alice]),
            headers=_headers(alice),
        )
    assert res.status_code == 409
    assert res.json()["error_category"] == "leader_not_in_project"
    assert await _session_count(bench) == 0


@pytest.mark.asyncio
async def test_non_member_participant_is_rejected(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        outsider = await _create_bot(client, "Outsider")
        await _add_member(client, p1, leader, leader=True)
        res = await client.post(
            f"/api/projects/{p1}/discussion-sessions",
            json=_session_body(leader, [leader, outsider]),
            headers=_headers(leader),
        )
    assert res.status_code in {400, 409}
    assert res.json()["error_category"] in {"validation_error", "invalid_participant"}
    assert await _session_count(bench) == 0


@pytest.mark.asyncio
async def test_five_participants_are_allowed(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        bots = [await _create_bot(client, name) for name in ["Leader", "Alice", "Bob", "Carol", "Dave"]]
        await _add_member(client, p1, bots[0], leader=True)
        for bot_id in bots[1:]:
            await _add_member(client, p1, bot_id)
        res = await _create_session(client, p1, bots[0], bots)
    assert res.status_code == 201, res.text
    assert res.json()["participant_bot_ids"] == bots


@pytest.mark.asyncio
async def test_missing_header_and_project_not_found(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        await _add_member(client, p1, leader, leader=True)
        missing = await client.post(
            f"/api/projects/{p1}/discussion-sessions",
            json=_session_body(leader, [leader]),
        )
        missing_project = await client.post(
            "/api/projects/no-such/discussion-sessions",
            json=_session_body(leader, [leader]),
            headers=_headers(leader),
        )
    assert missing.status_code == 400
    assert missing.json()["error_category"] == "validation_error"
    assert missing_project.status_code == 404
    assert missing_project.json()["error_category"] == "project_not_found"


@pytest.mark.asyncio
async def test_concurrent_group_leaves_one_complete_list(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        bots = [await _create_bot(client, name) for name in ["Leader", "Alice", "Bob", "Carol", "Dave"]]
        await _add_member(client, p1, bots[0], leader=True)
        for bot_id in bots[1:]:
            await _add_member(client, p1, bot_id)
        created = await _create_session(client, p1, bots[0], bots)
    sid = created.json()["session_id"]
    first = [bots[0], bots[1]]
    second = [bots[0], bots[2], bots[3], bots[4]]
    async with _client(app) as left, _client(app) as right:
        left_res, right_res = await asyncio.gather(
            left.post(
                f"/api/discussion-sessions/{sid}/group",
                json={"participant_bot_ids": first},
                headers=_headers(bots[0]),
            ),
            right.post(
                f"/api/discussion-sessions/{sid}/group",
                json={"participant_bot_ids": second},
                headers=_headers(bots[0]),
            ),
        )
    assert left_res.status_code == 200, left_res.text
    assert right_res.status_code == 200, right_res.text
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(sid)
    assert stored.status == "grouping"
    assert stored.participant_bot_ids in (first, second)

async def _grouped_session(app, budget=None):
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        bots = [await _create_bot(client, name) for name in ["Leader", "Alice", "Bob", "Outsider"]]
        await _add_member(client, p1, bots[0], leader=True)
        await _add_member(client, p1, bots[1])
        await _add_member(client, p1, bots[2])
        overrides = {"budget": budget} if budget is not None else {}
        created = await _create_session(client, p1, bots[0], bots[1:3], **overrides)
        grouped = await client.post(
            f"/api/discussion-sessions/{created.json()['session_id']}/group",
            json={"participant_bot_ids": bots[1:3]},
            headers=_headers(bots[0]),
        )
    assert created.status_code == 201, created.text
    assert grouped.status_code == 200, grouped.text
    return bench, p1, bots, created.json()["session_id"]


@pytest.mark.asyncio
async def test_start_round_and_blind_proposal_visibility(app) -> None:
    _bench, _p1, bots, session_id = await _grouped_session(app)
    leader, alice, bob, _outsider = bots
    async with _client(app) as client:
        started = await _start_round(client, session_id, leader)
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "round1_independent"
        first = await _submit_proposal(client, session_id, alice, alice, "Alice-plan")
        bob_view = await client.get(
            f"/api/discussion-sessions/{session_id}/proposals", headers=_headers(bob)
        )
        alice_view = await client.get(
            f"/api/discussion-sessions/{session_id}/proposals", headers=_headers(alice)
        )
        second = await _submit_proposal(client, session_id, bob, bob, "Bob-plan")
        both = await client.get(
            f"/api/discussion-sessions/{session_id}/proposals", headers=_headers(bob)
        )
    assert first.status_code == 201 and first.json()["sealed"] is True
    assert bob_view.json()["items"][0]["body_md"] is None
    assert "Alice-plan" not in bob_view.text
    assert alice_view.json()["items"][0]["body_md"] == "Alice-plan"
    assert second.status_code == 201 and second.json()["sealed"] is False
    assert {item["body_md"] for item in both.json()["items"]} == {"Alice-plan", "Bob-plan"}
    assert all(item["sealed"] is False for item in both.json()["items"])


@pytest.mark.asyncio
async def test_proposal_duplicate_author_mismatch_and_non_participant(app) -> None:
    _bench, _p1, bots, session_id = await _grouped_session(app)
    leader_bot, alice, bob, outsider = bots
    async with _client(app) as client:
        await _start_round(client, session_id, leader_bot)
        first = await _submit_proposal(client, session_id, alice, alice, "Alice-plan")
        duplicate = await _submit_proposal(client, session_id, alice, alice, "again")
        mismatch = await _submit_proposal(client, session_id, alice, bob, "stolen")
        non_participant = await _submit_proposal(
            client, session_id, outsider, outsider, "outsider"
        )
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error_category"] == "duplicate_proposal"
    assert mismatch.status_code == 403
    assert mismatch.json()["error_category"] == "forbidden"
    assert non_participant.status_code == 403
    assert non_participant.json()["error_category"] == "not_participant"


@pytest.mark.asyncio
async def test_list_proposals_before_start_is_invalid(app) -> None:
    _bench, _p1, bots, session_id = await _grouped_session(app)
    async with _client(app) as client:
        res = await client.get(
            f"/api/discussion-sessions/{session_id}/proposals", headers=_headers(bots[1])
        )
    assert res.status_code == 409
    assert res.json()["error_category"] == "invalid_status"


@pytest.mark.asyncio
async def test_non_leader_cannot_start_round(app) -> None:
    _bench, _p1, bots, session_id = await _grouped_session(app)
    async with _client(app) as client:
        res = await _start_round(client, session_id, bots[1])
    assert res.status_code == 403
    assert res.json()["error_category"] == "forbidden"


@pytest.mark.asyncio
async def test_budget_exhausted_http(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        await _add_member(client, p1, bob)
        created = await _create_session(
            client, p1, leader, [alice, bob], budget={"max_rounds": 1}
        )
        session_id = created.json()["session_id"]
        await client.post(
            f"/api/discussion-sessions/{session_id}/group",
            json={"participant_bot_ids": [alice, bob]},
            headers=_headers(leader),
        )
        await _start_round(client, session_id, leader)
        await _submit_proposal(client, session_id, alice, alice, "A")
        await _submit_proposal(client, session_id, bob, bob, "B")
        exhausted = await _start_round(client, session_id, leader)
    assert exhausted.status_code == 409
    assert exhausted.json()["error_category"] == "budget_exhausted"
    async with bench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.status == "budget_exhausted"


def _review_body(
    reviewer: str,
    proposal_id: str,
    *,
    dissent: list[str] | None = None,
    gates: dict | None = None,
) -> dict:
    return {
        "reviewer_bot_id": reviewer,
        "proposal_id": proposal_id,
        "scores": {"coverage": 4},
        "score_justification": {"coverage": "ok"},
        "hard_gate_results": gates
        or {
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        "dissent_items": list(dissent or []),
    }


async def _review(client: AsyncClient, session_id: str, actor: str, body: dict):
    return await client.post(
        f"/api/discussion-sessions/{session_id}/reviews",
        json=body,
        headers=_headers(actor),
    )


async def _cross_reviewed(app, *, dissent: list[str] | None = None):
    _bench, _p1, bots, session_id = await _grouped_session(app)
    leader, alice, bob, _outsider = bots
    async with _client(app) as client:
        await _start_round(client, session_id, leader)
        alice_proposal = await _submit_proposal(
            client, session_id, alice, alice, "Alice-plan"
        )
        bob_proposal = await _submit_proposal(client, session_id, bob, bob, "Bob-plan")
        await _review(
            client,
            session_id,
            bob,
            _review_body(bob, alice_proposal.json()["proposal_id"], dissent=dissent),
        )
        await _review(
            client,
            session_id,
            alice,
            _review_body(alice, bob_proposal.json()["proposal_id"]),
        )
    return app, bots, session_id


async def _converge(client: AsyncClient, session_id: str, actor: str, body=None):
    return await client.post(
        f"/api/discussion-sessions/{session_id}/converge",
        json=body or {},
        headers=_headers(actor),
    )


@pytest.mark.asyncio
async def test_converge_submit_human_returns_dissent(app) -> None:
    _app, bots, session_id = await _cross_reviewed(app, dissent=["风险X"])
    async with _client(app) as client:
        res = await _converge(client, session_id, bots[0])
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["action"] == "submit_human"
    assert "风险X" in payload["reason"]
    assert payload["dissent_items"] == ["风险X"]
    assert payload["session"]["status"] == "converged_pending_human"


@pytest.mark.asyncio
async def test_converge_outside_cross_review_is_409(app) -> None:
    _bench, _p1, bots, session_id = await _grouped_session(app)
    async with _client(app) as client:
        res = await _converge(client, session_id, bots[0])
    assert res.status_code == 409
    assert res.json()["error_category"] == "invalid_status"


@pytest.mark.asyncio
async def test_converge_concurrent_has_one_winner(app) -> None:
    _app, bots, session_id = await _cross_reviewed(app)
    async with _client(app) as first, _client(app) as second:
        left, right = await asyncio.gather(
            _converge(first, session_id, bots[0]),
            _converge(second, session_id, bots[0]),
        )
    assert sorted([left.status_code, right.status_code]) == [200, 409]
    async with app.state.workbench.db_session() as session:
        stored = await DiscussionSessionStore(session).get(session_id)
    assert stored.status == "converged_pending_human"


@pytest.mark.asyncio
async def test_converge_no_improvement_sets_pending_human(app) -> None:
    # 显式旧模式：阈值为 None 时才保留 no_improvement。
    _bench, _p1, bots, session_id = await _grouped_session(
        app, budget={"max_rounds": 3, "score_gap_threshold": None}
    )
    leader, alice, bob, _outsider = bots
    partial = {
        "coverage": True,
        "conflicts_closed_or_recorded": False,
        "evidence_complete": False,
    }
    async with _client(app) as client:
        await _start_round(client, session_id, leader)
        alice_proposal = await _submit_proposal(client, session_id, alice, alice, "A1")
        bob_proposal = await _submit_proposal(client, session_id, bob, bob, "B1")
        await _review(client, session_id, bob, _review_body(bob, alice_proposal.json()["proposal_id"], gates=partial))
        await _review(client, session_id, alice, _review_body(alice, bob_proposal.json()["proposal_id"], gates=partial))
        await _start_round(client, session_id, leader)
        alice_proposal = await _submit_proposal(client, session_id, alice, alice, "A2")
        bob_proposal = await _submit_proposal(client, session_id, bob, bob, "B2")
        await _review(client, session_id, bob, _review_body(bob, alice_proposal.json()["proposal_id"], gates=partial))
        await _review(client, session_id, alice, _review_body(alice, bob_proposal.json()["proposal_id"], gates=partial))
        res = await _converge(client, session_id, leader)
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "no_improvement"
    assert res.json()["session"]["status"] == "converged_pending_human"


@pytest.mark.asyncio
async def test_converge_token_budget_exhausted(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        await _add_member(client, p1, bob)
        created = await _create_session(
            client, p1, leader, [alice, bob], budget={"max_tokens": 10}
        )
        session_id = created.json()["session_id"]
        await client.post(
            f"/api/discussion-sessions/{session_id}/group",
            json={"participant_bot_ids": [alice, bob]},
            headers=_headers(leader),
        )
        await _start_round(client, session_id, leader)
        await _submit_proposal(client, session_id, alice, alice, "A")
        await _submit_proposal(client, session_id, bob, bob, "B")
        res = await _converge(client, session_id, leader, {"tokens_used": 10})
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "budget_exhausted"
    assert res.json()["session"]["status"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_create_session_accepts_string_requirement_snapshot(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader = await _create_bot(client, "Leader")
        alice = await _create_bot(client, "Alice")
        bob = await _create_bot(client, "Bob")
        await _add_member(client, p1, leader, leader=True)
        await _add_member(client, p1, alice)
        await _add_member(client, p1, bob)
        res = await client.post(
            f"/api/projects/{p1}/discussion-sessions",
            json={
                "leader_bot_id": leader,
                "participant_bot_ids": [alice, bob],
                "requirement_snapshot": "plain requirement",
            },
            headers=_headers(leader),
        )
    assert res.status_code == 201, res.text
    assert res.json()["requirement_snapshot_hash"] == hash_artifact("plain requirement")
    assert res.json()["requirement_text"] == "plain requirement"


async def _three_bots(client: AsyncClient, p1: str) -> tuple[str, str, str]:
    leader = await _create_bot(client, "Leader")
    alice = await _create_bot(client, "Alice")
    bob = await _create_bot(client, "Bob")
    await _add_member(client, p1, leader, leader=True)
    await _add_member(client, p1, alice)
    await _add_member(client, p1, bob)
    return leader, alice, bob


@pytest.mark.asyncio
async def test_create_session_default_budget_uses_score_threshold(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader, alice, bob = await _three_bots(client, p1)
        created = await _create_session(client, p1, leader, [alice, bob])
    assert created.status_code == 201, created.text
    budget = created.json()["budget"]
    assert budget["max_rounds"] == 3
    assert budget["score_gap_threshold"] == 2.0


@pytest.mark.asyncio
async def test_create_session_keeps_explicit_null_score_threshold(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader, alice, bob = await _three_bots(client, p1)
        created = await _create_session(
            client,
            p1,
            leader,
            [alice, bob],
            budget={"score_gap_threshold": None},
        )
    assert created.status_code == 201, created.text
    budget = created.json()["budget"]
    assert budget["max_rounds"] == 3
    assert budget["score_gap_threshold"] is None


@pytest.mark.asyncio
async def test_create_session_object_snapshot_serializes_requirement_text(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    snapshot = {"text": "中文需求", "scope": ["a", "b"]}
    async with _client(app) as client:
        leader, alice, bob = await _three_bots(client, p1)
        created = await _create_session(
            client, p1, leader, [alice, bob], requirement_snapshot=snapshot
        )
    assert created.status_code == 201, created.text
    assert created.json()["requirement_text"] == json.dumps(snapshot, ensure_ascii=False)
    assert "中文需求" in created.json()["requirement_text"]


@pytest.mark.asyncio
async def test_create_session_passes_previous_session_id(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader, alice, bob = await _three_bots(client, p1)
        first = await _create_session(client, p1, leader, [alice, bob])
        second = await _create_session(
            client,
            p1,
            leader,
            [alice, bob],
            requirement_snapshot="revised requirement",
            previous_session_id=first.json()["session_id"],
        )
    assert second.status_code == 201, second.text
    assert second.json()["previous_session_id"] == first.json()["session_id"]
    assert second.json()["requirement_text"] == "revised requirement"
    assert first.json()["previous_session_id"] is None


@pytest.mark.asyncio
async def test_create_session_needs_at_least_two_participants(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader, alice, _bob = await _three_bots(client, p1)
        single = await _create_session(client, p1, leader, [alice])
        duplicated = await _create_session(client, p1, leader, [alice, alice])
    assert single.status_code == 400
    assert single.json()["error_category"] == "validation_error"
    assert "至少需要 2 个 Bot" in single.json()["detail"]
    assert duplicated.status_code == 400
    assert "至少需要 2 个 Bot" in duplicated.json()["detail"]
    assert await _session_count(bench) == 0


@pytest.mark.asyncio
async def test_create_session_rejects_secret_in_requirement(app) -> None:
    bench = app.state.workbench
    p1 = bench.create_project("P1")["id"]
    async with _client(app) as client:
        leader, alice, bob = await _three_bots(client, p1)
        leaked = await _create_session(
            client,
            p1,
            leader,
            [alice, bob],
            requirement_snapshot="想法：用 sk-abc123 这把钥匙",
        )
        object_form = await _create_session(
            client,
            p1,
            leader,
            [alice, bob],
            requirement_snapshot={"text": "sk-abc123"},
        )
    assert leaked.status_code == 400
    assert leaked.json()["error_category"] == "secret_in_body"
    assert object_form.status_code == 400
    assert object_form.json()["error_category"] == "secret_in_body"
    assert await _session_count(bench) == 0
