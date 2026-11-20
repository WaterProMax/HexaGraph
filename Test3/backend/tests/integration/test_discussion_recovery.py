from __future__ import annotations

import asyncio
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion import driver
from app.discussion.messages import LOG, message_item
from app.discussion.models import (
    DecisionPackage,
    DiscussionBudget,
    DiscussionSession,
)
from app.discussion.session_store import DiscussionSessionStore
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

LEADER_BODY = "LEADER-BODY-MARKER 目标用户是期末周找不到座位的学生。"
ALICE_BODY = "ALICE-BODY-MARKER 目标用户是图书馆管理员。"
PAUSED_TEXT = "服务已重启，讨论已暂停。点击“继续”从中断处接着跑。"


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
def bench(tmp_path):
    return Workbench(
        Gateway(load_models(), ScriptedProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )


def _proposal(marker: str) -> str:
    return f"""### 1. 目标用户与痛点
{marker} 现有做法靠人工占座，体验不稳定。

### 2. 功能清单
- F-01 座位查询：查看空闲座位。验收要点：列表返回可用座位。
- F-02 预约：选定时间段预约。验收要点：冲突时拒绝。

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
        "scores": {"value": 4, "feasibility": 4, "testability": 4, "clarity": 4},
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


def _leader_reply() -> str:
    spec = (
        "## 概述\n自习座位预约系统，解决期末周抢座问题。\n\n"
        "## 功能列表\n- F-01 座位查询。\n- F-02 预约。\n\n"
        "## 本版不做\n不做跨校区。\n\n"
        "## 验收标准\n给定空闲座位，当用户预约，则生成一条预约记录。\n\n"
        "## 非功能需求\n本版不承诺额外非功能指标。\n\n"
        "## 还没定的问题\n座位数据来源待定。\n"
    )
    verdict = {"ok": True, "reason": "六个部分齐全。", "dissent_items": []}
    return spec + "\n```json\n" + json.dumps(verdict, ensure_ascii=False) + "\n```"


def _record(
    session_id: str,
    *,
    status: str = "round1_independent",
    paused: bool = False,
    decision_package: DecisionPackage | None = None,
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> DiscussionSession:
    return DiscussionSession(
        session_id=session_id,
        project_id="project-1",
        leader_bot_id="leader",
        participant_bot_ids=["leader", "alice"],
        status=status,
        current_round=1,
        budget=DiscussionBudget(max_rounds=3, score_gap_threshold=2.0),
        requirement_snapshot_hash="snapshot-hash",
        decision_package=decision_package,
        requirement_text="做一个期末周自习座位预约系统",
        paused=paused,
        created_at=created_at,
    )


def _decision_package(session_id: str) -> DecisionPackage:
    return DecisionPackage(
        decision_id=f"decision-{session_id}",
        session_id=session_id,
        requirement_snapshot_hash="snapshot-hash",
        proposal_ids=[],
        dissent_items=[],
        hard_gate_summary={},
        body_md="## 概述\n已收敛的规格。",
        sha256="0" * 64,
    )


async def _store_create(bench, record: DiscussionSession) -> None:
    async with bench.db_session() as session:
        await DiscussionSessionStore(session).create(record)
        await session.commit()


async def _store_save(bench, record: DiscussionSession) -> None:
    async with bench.db_session() as session:
        await DiscussionSessionStore(session).save(record)
        await session.commit()


async def _get(bench, session_id: str) -> DiscussionSession:
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _messages(bench, session_id: str) -> list[dict]:
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
        return [message_item(row) for row in rows]


def _paused_events(messages: list[dict]) -> list[dict]:
    return [
        message
        for message in messages
        if message["kind"] == "system"
        and (message["payload"] or {}).get("event") == "paused"
    ]


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


async def _wait(bench, session_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while driver.is_running(bench, session_id) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert not driver.is_running(bench, session_id), "driver did not finish"


@pytest.mark.asyncio
async def test_recovery_pauses_all_interrupted_sessions(bench) -> None:
    # Created out of order so the returned list proves (created_at, id) sorting.
    await _store_create(
        bench, _record("s2", status="cross_review", created_at="2026-01-01T00:00:02+00:00")
    )
    await _store_create(
        bench,
        _record(
            "s3",
            status="converged_pending_human",
            created_at="2026-01-01T00:00:03+00:00",
        ),
    )
    await _store_create(
        bench, _record("s1", status="round1_independent", created_at="2026-01-01T00:00:01+00:00")
    )

    recovered = await driver.recover_interrupted_sessions(bench)

    assert recovered == ["s1", "s2", "s3"]
    for session_id in recovered:
        record = await _get(bench, session_id)
        assert record.paused is True
        paused = _paused_events(await _messages(bench, session_id))
        assert len(paused) == 1
        payload = paused[0]["payload"]
        assert payload["reason"] == "server_restart"
        assert payload["text"] == PAUSED_TEXT
        assert paused[0]["round"] == 1

    counts = {
        session_id: len(await _messages(bench, session_id)) for session_id in recovered
    }
    assert await driver.recover_interrupted_sessions(bench) == []
    for session_id in recovered:
        assert len(await _messages(bench, session_id)) == counts[session_id]
        assert (await _get(bench, session_id)).paused is True


@pytest.mark.asyncio
async def test_recovery_leaves_terminal_paused_and_pending_approval(bench) -> None:
    statuses = ["approved", "rejected", "terminated", "budget_exhausted"]
    for index, status in enumerate(statuses):
        await _store_create(
            bench,
            _record(
                f"terminal-{status}",
                status=status,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ),
        )
    await _store_create(
        bench,
        _record(
            "already-paused",
            status="round1_independent",
            paused=True,
            created_at="2026-01-01T00:00:10+00:00",
        ),
    )
    await _store_create(
        bench,
        _record(
            "pending-approval",
            status="converged_pending_human",
            decision_package=_decision_package("pending-approval"),
            created_at="2026-01-01T00:00:11+00:00",
        ),
    )

    recovered = await driver.recover_interrupted_sessions(bench)

    assert recovered == []
    for status in statuses:
        record = await _get(bench, f"terminal-{status}")
        assert record.status == status
        assert record.paused is False
        assert _paused_events(await _messages(bench, f"terminal-{status}")) == []

    paused_record = await _get(bench, "already-paused")
    assert paused_record.status == "round1_independent"
    assert paused_record.paused is True
    assert _paused_events(await _messages(bench, "already-paused")) == []

    pending = await _get(bench, "pending-approval")
    assert pending.status == "converged_pending_human"
    assert pending.paused is False
    assert pending.decision_package is not None
    assert _paused_events(await _messages(bench, "pending-approval")) == []


@pytest.mark.asyncio
async def test_recovery_isolates_per_session_failures(bench, monkeypatch) -> None:
    for index, session_id in enumerate(("bad", "good-1", "good-2")):
        await _store_create(
            bench,
            _record(session_id, created_at=f"2026-01-01T00:00:0{index}+00:00"),
        )

    original_system = driver._system

    async def flaky_system(bench_, session_id, event, text, **kwargs):
        if session_id == "bad":
            raise RuntimeError("boom")
        return await original_system(bench_, session_id, event, text, **kwargs)

    monkeypatch.setattr(driver, "_system", flaky_system)

    recovered = await driver.recover_interrupted_sessions(bench)

    assert recovered == ["good-1", "good-2"]
    assert len(_paused_events(await _messages(bench, "good-1"))) == 1
    assert len(_paused_events(await _messages(bench, "good-2"))) == 1
    assert (await _get(bench, "good-1")).paused is True
    assert (await _get(bench, "good-2")).paused is True
    assert (await _get(bench, "bad")).paused is True
    assert _paused_events(await _messages(bench, "bad")) == []


@pytest.mark.asyncio
async def test_recovery_never_raises_to_the_lifespan_wrapper(bench, monkeypatch) -> None:
    await _store_create(bench, _record("s1"))

    async def exploding_system(*args, **kwargs):
        raise RuntimeError("system message failed")

    monkeypatch.setattr(driver, "_system", exploding_system)

    assert await driver.recover_interrupted_sessions(bench) == []
    assert (await _get(bench, "s1")).paused is True


@pytest.mark.asyncio
async def test_resume_after_restart_finishes_to_decision_package(tmp_path) -> None:
    models = load_models()
    provider1 = ScriptedProvider()
    bench1 = Workbench(
        Gateway(models, provider1, data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    app1 = create_app()
    app1.state.workbench = bench1
    client1, bots, session_id = await _setup(app1, ["Leader", "Alice"])
    try:
        provider1.push(_proposal(LEADER_BODY))
        provider1.push(_proposal(ALICE_BODY))
        assert await driver.step(bench1, session_id) is True
        assert await driver.step(bench1, session_id) is True
        record = await _get(bench1, session_id)
        assert record.status == "cross_review"
        assert provider1.queue == []
    finally:
        await client1.aclose()
        await bench1.close()

    provider2 = ScriptedProvider(queue=[_review(), _review(), _leader_reply()])
    bench2 = Workbench(
        Gateway(models, provider2, data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    app2 = create_app()
    app2.state.workbench = bench2
    client2 = _client(app2)
    try:
        recovered = await driver.recover_interrupted_sessions(bench2)
        assert recovered == [session_id]
        assert (await _get(bench2, session_id)).paused is True

        resumed = await client2.post(
            f"/api/discussion-sessions/{session_id}/resume", headers=_headers(bots[0])
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["paused"] is False

        await _wait(bench2, session_id)

        record = await _get(bench2, session_id)
        assert record.status == "converged_pending_human"
        assert record.decision_package is not None
        assert record.decision_package.body_md.strip()
        assert provider2.queue == []
    finally:
        await client2.aclose()
        await bench2.close()