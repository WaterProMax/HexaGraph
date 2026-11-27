from __future__ import annotations

import asyncio
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion import driver
from app.discussion.decision import resolve_decision
from app.discussion.messages import LOG, message_item
from app.discussion.session_store import DiscussionSessionStore
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

LEADER_BODY = "LEADER-BODY-MARKER 目标用户是期末周找不到座位的学生。"
ALICE_BODY = "ALICE-BODY-MARKER 目标用户是图书馆管理员。"


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


def _review(
    value: int = 4,
    feasibility: int = 4,
    testability: int = 4,
    clarity: int = 4,
    *,
    gates: bool = True,
    dissent: list[str] | None = None,
) -> dict:
    return {
        "scores": {
            "value": value,
            "feasibility": feasibility,
            "testability": testability,
            "clarity": clarity,
        },
        "score_justification": {
            "value": "痛点明确，范围聚焦。",
            "feasibility": "依赖座位数据，资料没有说明来源。",
            "testability": "验收要点可判定。",
            "clarity": "编号连续，结构完整。",
        },
        "hard_gate_results": {
            "coverage": gates,
            "conflicts_closed_or_recorded": gates,
            "evidence_complete": gates,
        },
        "dissent_items": dissent or [],
    }


def _uneven_review(score: int) -> dict:
    review = _review(
        value=score, feasibility=score, testability=score, clarity=score
    )
    review["hard_gate_results"]["evidence_complete"] = False
    return review


def _leader_reply(
    *, ok: bool = True, reason: str = "六个部分齐全。", dissent: list[str] | None = None
) -> str:
    spec = (
        "## 概述\n自习座位预约系统，解决期末周抢座问题。\n\n"
        "## 功能列表\n- F-01 座位查询：来源：方案 Leader 的 F-01。\n"
        "- F-02 预约：来源：方案 Alice 的 F-02。\n\n"
        "## 本版不做\n不做跨校区。\n\n"
        "## 验收标准\n给定空闲座位，当用户预约，则生成预约记录。\n\n"
        "## 非功能需求\n本版不承诺额外非功能指标。\n\n"
        "## 还没定的问题\n座位数据来源待定。\n"
    )
    verdict = {
        "ok": ok,
        "reason": reason,
        "dissent_items": dissent or [],
    }
    return spec + "\n```json\n" + json.dumps(verdict, ensure_ascii=False) + "\n```"


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


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


async def _create_bot(client: AsyncClient, name: str) -> str:
    res = await client.post("/api/bots", json=_bot_body(name))
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


async def _add_member(client: AsyncClient, project_id: str, bot_id: str, leader: bool = False) -> None:
    res = await client.post(
        f"/api/projects/{project_id}/memberships",
        json={"bot_id": bot_id, "role_in_project": "dev", "is_leader": leader},
    )
    assert res.status_code == 201, res.text


async def _create_session(
    client: AsyncClient,
    project_id: str,
    leader: str,
    participants: list[str],
    **overrides,
):
    body = {
        "leader_bot_id": leader,
        "participant_bot_ids": participants,
        "requirement_snapshot": "做一个期末周自习座位预约系统",
    }
    body.update(overrides)
    return await client.post(
        f"/api/projects/{project_id}/discussion-sessions",
        json=body,
        headers=_headers(leader),
    )


async def _setup(app, names: list[str], *, budget: dict | None = None):
    bench = app.state.workbench
    project_id = bench.create_project("P1")["id"]
    client = _client(app)
    bots = [await _create_bot(client, name) for name in names]
    await _add_member(client, project_id, bots[0], leader=True)
    for bot_id in bots[1:]:
        await _add_member(client, project_id, bot_id)
    overrides = {"budget": budget} if budget is not None else {}
    created = await _create_session(client, project_id, bots[0], bots, **overrides)
    assert created.status_code == 201, created.text
    return client, bots, project_id, created.json()["session_id"]


async def _get(bench, session_id: str):
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _messages(bench, session_id: str) -> list[dict]:
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
        return [message_item(row) for row in rows]


async def _wait(bench, session_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while driver.is_running(bench, session_id) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert not driver.is_running(bench, session_id), "driver did not finish"


def _payload_text(messages: list[dict]) -> str:
    return "\n".join(
        json.dumps(message.get("payload") or {}, ensure_ascii=False)
        for message in messages
    )


@pytest.mark.asyncio
async def test_one_round_converges_and_leader_submits(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        # Work items: leader reviews Alice, then Alice reviews Leader.
        provider.push(_review(value=4, feasibility=4, testability=4, clarity=4))
        provider.push(_review(value=4, feasibility=4, testability=3, clarity=4))
        provider.push(_leader_reply())

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    assert "功能列表" in record.decision_package.body_md
    assert record.participant_bot_ids == bots

    messages = await _messages(bench, session_id)
    kinds = [message["kind"] for message in messages]
    assert kinds.count("proposal") == 2
    assert kinds.count("review") == 2
    assert kinds.count("leader") == 1
    proposal_messages = [m for m in messages if m["kind"] == "proposal"]
    assert all(m["payload"]["truncated"] is False for m in proposal_messages)
    assert all(m["payload"]["round"] == 1 for m in proposal_messages)
    leader_message = next(m for m in messages if m["kind"] == "leader")
    assert leader_message["payload"]["action"] == "submit"

    payload_text = _payload_text(messages)
    assert "LEADER-BODY-MARKER" not in payload_text
    assert "ALICE-BODY-MARKER" not in payload_text

    leader_calls = [
        call
        for call in provider.calls
        if "需求规格综合与自查" in call["messages"][0]["content"]
    ]
    assert len(leader_calls) == 1
    synthesis_user = leader_calls[0]["messages"][-1]["content"]
    assert "LEADER-BODY-MARKER" in synthesis_user
    assert "ALICE-BODY-MARKER" in synthesis_user

@pytest.mark.asyncio
async def test_wide_spread_revises_then_converges_in_second_round(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        # Round 1: leader 19, Alice 12 -> spread 7 > 2, so another round.
        provider.push(_review(value=3, feasibility=3, testability=3, clarity=3))
        provider.push(_review(value=5, feasibility=5, testability=5, clarity=4))
        # Round 2 revised proposals.
        provider.push(_proposal(LEADER_BODY + " 第二版"))
        provider.push(_proposal(ALICE_BODY + " 第二版"))
        provider.push(_review(value=4, feasibility=4, testability=4, clarity=3))
        provider.push(_review(value=4, feasibility=4, testability=4, clarity=4))
        provider.push(_leader_reply())

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.current_round == 2
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None

    messages = await _messages(bench, session_id)
    rounds = [m["round"] for m in messages if m["kind"] == "proposal"]
    assert rounds == [1, 1, 2, 2]
    round_started = [
        m
        for m in messages
        if m["kind"] == "system" and m["payload"]["event"] == "round_started"
    ]
    assert [m["round"] for m in round_started] == [1, 2]

    revise_calls = [
        call
        for call in provider.calls
        if "修改轮" in call["messages"][0]["content"]
    ]
    assert revise_calls
    for call in revise_calls:
        user = call["messages"][-1]["content"]
        assert "你的上一版方案" in user
        assert "他人方案" in user
        assert "你收到的评审" in user


@pytest.mark.asyncio
async def test_stalled_threshold_mode_forces_submit_only_at_round_limit(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        for index in range(3):
            provider.push(_proposal(f"{LEADER_BODY} 第 {index + 1} 版"))
            provider.push(_proposal(f"{ALICE_BODY} 第 {index + 1} 版"))
            # Work order: Leader reviews Alice (low), Alice reviews Leader (high).
            provider.push(_uneven_review(2))
            provider.push(_uneven_review(5))
        provider.push(_leader_reply())

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.current_round == 3
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    assert record.decision_package.body_md.strip()
    assert any(
        "未达成一致" in item for item in record.decision_package.dissent_items
    )

    messages = await _messages(bench, session_id)
    round_started = [
        m["round"]
        for m in messages
        if m["kind"] == "system" and m["payload"]["event"] == "round_started"
    ]
    assert round_started == [1, 2, 3]

    convergence_events = {
        m["round"]: m["payload"]["event"]
        for m in messages
        if m["kind"] == "system"
        and m["payload"]["event"] in {"converged", "forced_submit"}
    }
    assert 1 not in convergence_events
    assert 2 not in convergence_events
    assert convergence_events[3] == "forced_submit"

    forced = [
        m for m in messages if m["payload"].get("event") == "forced_submit"
    ]
    assert len(forced) == 1
    assert "已达第 3 轮上限" in forced[0]["payload"]["text"]
    assert "未达成一致" in forced[0]["payload"]["text"]


@pytest.mark.asyncio
async def test_leader_requests_revision_until_round_limit_forces_submit(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        for index in range(3):
            provider.push(_proposal(f"{LEADER_BODY} 第 {index + 1} 版"))
            provider.push(_proposal(f"{ALICE_BODY} 第 {index + 1} 版"))
            provider.push(_review())
            provider.push(_review())
            provider.push(
                _leader_reply(
                    ok=False,
                    reason=f"第 {index + 1} 轮规格缺少来源标注",
                )
            )

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.current_round == 3
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    dissent = record.decision_package.dissent_items
    assert any("Leader 未满意" in item for item in dissent)

    messages = await _messages(bench, session_id)
    leader_actions = [
        m["payload"]["action"] for m in messages if m["kind"] == "leader"
    ]
    assert leader_actions == [
        "request_revision",
        "request_revision",
        "request_revision",
        "submit",
    ]
    system_events = [
        m["payload"]["event"] for m in messages if m["kind"] == "system"
    ]
    assert "forced_submit" in system_events

    record_before = await _get(bench, session_id)
    assert await driver.step(bench, session_id) is False
    record_after = await _get(bench, session_id)
    assert record_after.status == record_before.status


@pytest.mark.asyncio
async def test_rejected_session_feeds_previous_spec_and_comment_to_new_session(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, project_id, first_id = await _setup(app, ["Leader", "Alice"])
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        await driver.run_session(bench, first_id)
        await _wait(bench, first_id)

        async with bench.db_session() as session:
            rejected = await resolve_decision(
                first_id,
                "rejected",
                "请补充隐私与数据保留说明。",
                actor_bot_id=bots[0],
                bench=bench,
                session=session,
            )
            await session.commit()
        assert rejected.status == "rejected"

        created = await _create_session(
            client,
            project_id,
            bots[0],
            bots,
            previous_session_id=first_id,
        )
        assert created.status_code == 201, created.text
        second_id = created.json()["session_id"]
        assert created.json()["previous_session_id"] == first_id

        call_index = len(provider.calls)
        provider.push(_proposal(LEADER_BODY + " 第二次讨论"))
        provider.push(_proposal(ALICE_BODY + " 第二次讨论"))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        await driver.run_session(bench, second_id)
        await _wait(bench, second_id)
        second_calls = provider.calls[call_index:]
        second_record = await _get(bench, second_id)
    finally:
        await client.aclose()

    assert second_record is not None
    assert second_record.status == "converged_pending_human"
    assert second_record.decision_package is not None
    second_messages = await _messages(bench, second_id)
    assert any(
        message["payload"].get("event") == "restarted_after_rejection"
        for message in second_messages
    )
    assert len(second_calls) == 5
    proposal_calls = [
        call
        for call in second_calls
        if "独立写出一份完整方案" in call["messages"][-1]["content"]
    ]
    leader_calls = [
        call
        for call in second_calls
        if "需求规格综合与自查" in call["messages"][0]["content"]
    ]
    assert len(proposal_calls) == 2
    assert len(leader_calls) == 1
    for call in proposal_calls + leader_calls:
        user = call["messages"][-1]["content"]
        assert "上一版规格" in user
        assert "自习座位预约系统，解决期末周抢座问题" in user
        assert "用户意见" in user
        assert "请补充隐私与数据保留说明。" in user
        assert "做一个期末周自习座位预约系统" in user


@pytest.mark.asyncio
async def test_bot_failure_pauses_then_resume_skips_the_bot(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(
        app, ["Leader", "Bob", "Alice"]
    )
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        provider.push(RuntimeError("upstream boom"))
        provider.push(RuntimeError("upstream boom"))

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)

        paused = await _get(bench, session_id)
        assert paused is not None
        assert paused.paused is True
        assert paused.status == "round1_independent"
        messages = await _messages(bench, session_id)
        failed = [
            m for m in messages if m["payload"].get("event") == "bot_failed"
        ]
        assert len(failed) == 1
        assert failed[0]["payload"]["bot_id"] == bots[2]
        assert failed[0]["payload"]["category"]

        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        resumed = await driver.resume_session(
            bench, session_id, skip_bot_ids=[bots[2]]
        )
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    assert resumed.status in {"round1_independent", "cross_review", "converged_pending_human"}
    assert bots[2] not in resumed.participant_bot_ids
    assert len(resumed.participant_bot_ids) == 2

    record = await _get(bench, session_id)
    assert record is not None
    assert record.status == "converged_pending_human"
    assert record.participant_bot_ids == [bots[0], bots[1]]
    assert record.decision_package is not None

    messages = await _messages(bench, session_id)
    skipped = [m for m in messages if m["payload"].get("event") == "bot_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["payload"]["bot_id"] == bots[2]
    proposal_authors = [
        m["bot_id"] for m in messages if m["kind"] == "proposal"
    ]
    assert proposal_authors == [bots[0], bots[1]]


@pytest.mark.asyncio
async def test_invalid_review_json_abstains_without_crashing(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, _bots, _project_id, session_id = await _setup(
        app,
        ["Leader", "Alice"],
        budget={"max_rounds": 1, "score_gap_threshold": 2.0},
    )
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        provider.push("抱歉，我无法按 JSON 输出。")
        provider.push("还是不行。")
        provider.push(_review())
        provider.push(_leader_reply())

        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    messages = await _messages(bench, session_id)
    abstained = [
        m for m in messages if m["payload"].get("event") == "review_abstained"
    ]
    assert len(abstained) == 1
    assert abstained[0]["payload"]["proposal_id"]


@pytest.mark.asyncio
async def test_terminate_stops_the_driver_and_emits_one_message(app) -> None:
    bench = app.state.workbench
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        terminated = await driver.terminate_session(bench, session_id)
        assert terminated.status == "terminated"
        assert await driver.step(bench, session_id) is False
        again = await driver.terminate_session(bench, session_id)
        assert again.status == "terminated"
    finally:
        await client.aclose()

    messages = await _messages(bench, session_id)
    terminated_events = [
        m for m in messages if m["payload"].get("event") == "terminated"
    ]
    assert len(terminated_events) == 1


@pytest.mark.asyncio
async def test_overlong_proposals_are_rewritten_then_truncated(app, monkeypatch) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(
        app, ["Leader", "Bob", "Alice"]
    )
    compressed = _proposal(LEADER_BODY + " 压缩版")
    too_long = _proposal(ALICE_BODY) + "x" * 6100
    replies = {
        "Leader": iter([_proposal(LEADER_BODY) + "y" * 6100, compressed]),
        "Bob": iter([too_long, too_long]),
        "Alice": iter([_proposal(ALICE_BODY + " 正常版")]),
    }

    def reply_to_bot(_slot, messages, **_kwargs):
        name = messages[0]["content"].split("，", 1)[0].removeprefix("你是 ")
        return next(replies[name])

    monkeypatch.setattr(provider, "next_item", reply_to_bot)
    try:
        await driver.step(bench, session_id)
        await driver.step(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record is not None
    assert record.status == "cross_review"

    messages = await _messages(bench, session_id)
    by_author = {
        message["bot_id"]: message
        for message in messages
        if message["kind"] == "proposal"
    }
    assert by_author[bots[0]]["payload"]["truncated"] is False
    assert by_author[bots[0]]["payload"]["chars"] == len(compressed.strip())
    assert by_author[bots[1]]["payload"]["truncated"] is True
    assert by_author[bots[1]]["payload"]["chars"] == 6000
    payload_text = _payload_text(messages)
    assert "y" * 100 not in payload_text
    assert "LEADER-BODY-MARKER" not in payload_text
