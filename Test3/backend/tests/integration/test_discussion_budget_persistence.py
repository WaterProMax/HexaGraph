from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion import driver
from app.discussion.messages import LOG, message_item
from app.discussion.models import DiscussionSession
from app.discussion.session_store import (
    DiscussionSessionStore,
    retry_locked,
)
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import (
    DiscussionProposalRow,
    DiscussionReviewRow,
    DiscussionSessionRow,
)


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
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


@pytest.fixture
def app(tmp_path):
    provider = ScriptedProvider()
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), provider, data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    app.state.provider = provider
    return app


def _proposal(marker: str) -> str:
    return f"""### 1. 目标用户与痛点
{marker} 现有做法靠人工占座，体验不稳定。

### 2. 功能清单
- F-01 座位查询：查看空闲座位。验收要点：列表返回可用座位。

### 3. 验收标准
给定空闲座位，当用户预约，则生成一条预约记录。

### 4. 非功能需求
本版不承诺额外非功能指标。

### 5. 本版不做
不做跨校区。

### 6. 风险与待定
座位数据来源待定。
"""


def _review() -> dict:
    return {
        "scores": {
            "value": 4,
            "feasibility": 4,
            "testability": 4,
            "clarity": 4,
        },
        "score_justification": {
            "value": "痛点明确，范围聚焦。",
            "feasibility": "依赖座位数据，资料没有说明来源。",
            "testability": "验收要点可判定。",
            "clarity": "编号连续，结构完整。",
        },
        "hard_gate_results": {
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        "dissent_items": [],
    }


async def _setup(app, names: list[str], *, budget: dict | None = None):
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
            json={
                "bot_id": bot_id,
                "role_in_project": "dev",
                "is_leader": index == 0,
            },
        )
        assert res.status_code == 201, res.text
    created = await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json={
            "leader_bot_id": bots[0],
            "participant_bot_ids": bots,
            "requirement_snapshot": "做一个期末周自习座位预约系统",
            "budget": budget,
        },
        headers=_headers(bots[0]),
    )
    assert created.status_code == 201, created.text
    return client, bots, project_id, created.json()["session_id"]


async def _get(bench, session_id: str) -> DiscussionSession:
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _messages(bench, session_id: str) -> list[dict]:
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
        return [message_item(row) for row in rows]


async def _seed_cross_review(
    bench, session_id: str, bots: list[str], *, tokens_used: int
) -> None:
    """Persist a cross_review session with two proposals and one review left."""
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        locked = await store.get_locked(session_id)
        await store.save(
            locked.model_copy(
                update={
                    "status": "cross_review",
                    "tokens_used": tokens_used,
                }
            )
        )
        session.add(
            DiscussionProposalRow(
                proposal_id="proposal-leader",
                session_id=session_id,
                author_bot_id=bots[0],
                round=1,
                sealed=0,
                body_md=_proposal("LEADER"),
            )
        )
        session.add(
            DiscussionProposalRow(
                proposal_id="proposal-alice",
                session_id=session_id,
                author_bot_id=bots[1],
                round=1,
                sealed=0,
                body_md=_proposal("ALICE"),
            )
        )
        session.add(
            DiscussionReviewRow(
                review_id="review-leader-alice",
                session_id=session_id,
                reviewer_bot_id=bots[0],
                proposal_id="proposal-alice",
                payload={
                    **_review(),
                    "reviewer_bot_id": bots[0],
                    "proposal_id": "proposal-alice",
                },
            )
        )
        await session.commit()


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.asyncio
async def test_token_budget_survives_driver_restart(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(
        app,
        ["Leader", "Alice"],
        budget={"max_rounds": 3, "max_tokens": 1000, "score_gap_threshold": 2.0},
    )
    try:
        await _seed_cross_review(bench, session_id, bots, tokens_used=900)
        bench._discussion_driver_metrics = {}
        provider.push({**_review(), "tokens_in": 100, "tokens_out": 100})

        for _ in range(5):
            record = await _get(bench, session_id)
            if record.status in driver.TERMINAL_STATUSES:
                break
            await driver.step(bench, session_id)
        record = await _get(bench, session_id)
        messages = await _messages(bench, session_id)
    finally:
        await client.aclose()

    assert record.status == "budget_exhausted"
    assert record.tokens_used >= 1000
    assert any(
        message["kind"] == "system"
        and (message["payload"] or {}).get("event") == "budget_exhausted"
        for message in messages
    )


@pytest.mark.asyncio
async def test_elapsed_time_excludes_pause_but_survives_restart(
    app, monkeypatch
) -> None:
    bench = app.state.workbench
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    clock = _Clock(100.0)
    monkeypatch.setattr(driver, "time", SimpleNamespace(monotonic=clock))

    async def no_drive(_bench, _session_id: str) -> None:
        return None

    monkeypatch.setattr(driver, "_drive", no_drive)
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            locked = await store.get_locked(session_id)
            await store.save(locked.model_copy(update={"elapsed_seconds": 5}))
            await session.commit()

        await driver.run_session(bench, session_id)
        clock.advance(3)
        await driver.pause_session(bench, session_id)
        paused = await _get(bench, session_id)
        assert paused.paused is True
        assert paused.elapsed_seconds == 8

        clock.advance(100)
        await driver.resume_session(bench, session_id)
        clock.advance(2)
        assert await driver.step(bench, session_id) is True
        record = await _get(bench, session_id)
    finally:
        await client.aclose()

    assert record.paused is False
    assert record.elapsed_seconds == 10


@pytest.mark.asyncio
async def test_concurrent_pause_and_usage_writes_merge(app) -> None:
    bench = app.state.workbench
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        driver._metrics(bench)[session_id] = {
            "tokens": 123.0,
            "elapsed_base": 7.0,
            "started_at": driver.time.monotonic() + 100,
        }

        async def pause_write() -> None:
            async with bench.db_session() as session:
                store = DiscussionSessionStore(session)

                async def operation() -> None:
                    record = await store.get_locked(session_id)
                    await store.save(record.model_copy(update={"paused": True}))
                    await session.commit()

                await retry_locked(session, operation)

        await asyncio.gather(pause_write(), driver._persist_usage(bench, session_id))
        record = await _get(bench, session_id)
    finally:
        await client.aclose()

    assert record.paused is True
    assert record.tokens_used == 123
    assert record.elapsed_seconds == 7


@pytest.mark.asyncio
async def test_old_payload_defaults_to_zero_usage(app) -> None:
    bench = app.state.workbench
    payload = {
        "session_id": "legacy-session",
        "project_id": "project-1",
        "leader_bot_id": "leader",
        "participant_bot_ids": ["leader", "alice"],
        "status": "round1_independent",
        "current_round": 1,
        "budget": {"max_rounds": 3},
        "requirement_snapshot_hash": "snapshot-hash",
    }
    validated = DiscussionSession.model_validate(payload)
    assert validated.tokens_used == 0
    assert validated.elapsed_seconds == 0

    async with bench.db_session() as session:
        session.add(
            DiscussionSessionRow(
                session_id="legacy-session",
                project_id="project-1",
                status="round1_independent",
                payload=payload,
            )
        )
        await session.commit()
        stored = await DiscussionSessionStore(session).get("legacy-session")

    assert stored.tokens_used == 0
    assert stored.elapsed_seconds == 0