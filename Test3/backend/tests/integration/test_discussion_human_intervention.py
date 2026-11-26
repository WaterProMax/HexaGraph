"""Human-in-the-loop controls for the discussion driver (H subsystem).

Covered here:
* cooperative pause during an in-flight review, then a same-session
  intervention that is injected into the prompts built after resuming;
* manual end-round (never a decision package / auto approval), its guards on
  resume/step/run and the explicit ``rounds/start`` re-open path;
* pause/end-round revision CAS races;
* restart persistence of paused/interventions/round_end_reason;
* the default 2.0 threshold boundary stays ``<=``;
* legacy session payload defaults, non-leader 403s and skip_bot_ids.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.runtime import RoleRegistry
from app.discussion import driver
from app.discussion.converge import should_converge
from app.discussion.messages import LOG, message_item
from app.discussion.models import (
    DiscussionBudget,
    DiscussionRoundState,
    DiscussionSession,
)
from app.discussion.session_store import DiscussionSessionStore, InvalidStatus
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import (
    DiscussionProposalRow,
    DiscussionReviewRow,
    DiscussionSessionRow,
    ExecutionGrantRow,
)

LEADER_BODY = "LEADER-BODY-MARKER 目标用户是期末周找不到座位的学生。"
ALICE_BODY = "ALICE-BODY-MARKER 目标用户是图书馆管理员。"
INTERVENTION = "请补充取消预约与爽约的规则，并写进验收标准。"
OLD_LEADER = "OLD-LEADER-GENERATION-MARKER"
OLD_ALICE = "OLD-ALICE-GENERATION-MARKER"
NEW_LEADER = "NEW-LEADER-GENERATION-MARKER"
NEW_ALICE = "NEW-ALICE-GENERATION-MARKER"


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


class BlockingProvider(ScriptedProvider):
    """Scripted provider that can block model calls offline.

    ``block_once`` blocks the first call matching an arbitrary matcher;
    ``block_key`` blocks an independent call by ``work_key`` so two concurrent
    proposal calls can be released in either order.
    """

    def __init__(self) -> None:
        super().__init__()
        self._matcher = None
        self._gate: asyncio.Event | None = None
        self._entered: asyncio.Event | None = None
        self._key_gates: dict[str, tuple[int, int, asyncio.Event, asyncio.Event]] = {}
        self._key_counts: dict[str, int] = {}
        # ``started`` records every gateway call entering the provider (even a
        # blocked one); ``finished`` records calls that actually returned a
        # response, which is what "a prompt built after resume" must be judged on.
        self.started: list[dict] = []
        self.finished: list[dict] = []

    def block_once(self, matcher):
        self._matcher = matcher
        self._gate = asyncio.Event()
        self._entered = asyncio.Event()
        return self._entered, self._gate

    def block_key(self, key: str, nth: int = 1):
        entered = asyncio.Event()
        gate = asyncio.Event()
        self._key_gates[key] = (nth, 0, entered, gate)
        return entered, gate

    async def complete(self, slot, messages, **kwargs):  # type: ignore[override]
        self.started.append(
            {"slot": slot, "messages": messages, "kwargs": dict(kwargs)}
        )
        matcher = self._matcher
        if matcher is not None and matcher(messages, kwargs):
            self._matcher = None
            assert self._entered is not None and self._gate is not None
            self._entered.set()
            await self._gate.wait()
        key = _provider_work_key(messages, kwargs)
        entry = self._key_gates.get(key)
        if entry is not None:
            nth, seen, entered, gate = entry
            seen += 1
            if seen >= nth:
                self._key_gates.pop(key, None)
                entered.set()
                await gate.wait()
            else:
                self._key_gates[key] = (nth, seen, entered, gate)
        self.finished.append(
            {"slot": slot, "messages": messages, "kwargs": dict(kwargs)}
        )
        return await super().complete(slot, messages, **kwargs)


def _operation_is(operation: str):
    def matcher(_messages, kwargs):
        return kwargs.get("discussion_operation") == operation

    return matcher


def _nth_operation(operation: str, nth: int):
    seen = {"count": 0}

    def matcher(_messages, kwargs):
        if kwargs.get("discussion_operation") != operation:
            return False
        seen["count"] += 1
        return seen["count"] == nth

    return matcher


def _provider_work_key(messages: list[dict], kwargs: dict) -> str:
    """Derive the driver work key from the rendered prompt, offline.

    The system prompt starts with ``你是 <display name>，一个担任...`` so the
    blocked call can be selected by bot + operation without touching internals.
    """
    system = ""
    for message in messages:
        if message.get("role") == "system":
            system = message.get("content") or ""
            break
    match = re.search(r"你是 (.+?)，一个担任", system)
    name = match.group(1) if match else ""
    return f"{kwargs.get('discussion_operation')}:{name}"


@pytest.fixture
def app(tmp_path):
    provider = BlockingProvider()
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), provider, data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    app.state.provider = provider
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
    return client, bots, project_id, created.json()["session_id"]


async def _get(bench, session_id: str) -> DiscussionSession:
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _messages(bench, session_id: str) -> list[dict]:
    async with bench.db_session() as session:
        rows = await LOG.after(session, session_id, 0)
        return [message_item(row) for row in rows]


async def _count(bench, row_model) -> int:
    async with bench.db_session() as session:
        return int(
            (await session.execute(select(func.count()).select_from(row_model))).scalar_one()
        )


async def _wait(bench, session_id: str, timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while driver.is_running(bench, session_id) and loop.time() < deadline:
        await asyncio.sleep(0.01)
    assert not driver.is_running(bench, session_id), "driver did not finish"


async def _wait_until(bench, session_id: str, predicate, timeout: float = 5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        record = await _get(bench, session_id)
        if predicate(record):
            return record
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def _interventions(messages: list[dict]) -> list[dict]:
    return [
        message
        for message in messages
        if message["kind"] == "user"
        and (message["payload"] or {}).get("event") == "intervention"
    ]


@pytest.mark.asyncio
async def test_pause_during_inflight_review_then_intervention_on_resume(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    entered, gate = provider.block_once(_operation_is("review"))
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    provider.push(_review())  # consumed by the in-flight review once released
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered.wait(), timeout=5)

        pause_task = asyncio.create_task(
            client.post(
                f"/api/discussion-sessions/{session_id}/pause",
                headers=_headers(bots[0]),
            )
        )
        await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        calls_before_release = len(provider.calls)
        assert calls_before_release == 2  # two proposals; the review is in flight
        gate.set()
        pause_response = await asyncio.wait_for(pause_task, timeout=10)
        assert pause_response.status_code == 200, pause_response.text
        paused = pause_response.json()
        assert paused["paused"] is True
        assert paused["pause_requested"] is False
        assert paused["checkpoint"]["phase"] == "review:after_response"
        assert paused["checkpoint"]["inflight_state"] == "response_received"

        # The in-flight review returned but must not have been persisted and no
        # further model call may start after the pause.
        await asyncio.sleep(0.05)
        assert len(provider.calls) == calls_before_release + 1
        assert await _count(bench, DiscussionReviewRow) == 0
        assert (await _get(bench, session_id)).decision_package is None

        revision = paused["control_revision"]
        intervention_response = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": revision, "text": INTERVENTION},
            headers=_headers(bots[0]),
        )
        assert intervention_response.status_code == 200, intervention_response.text
        intervention_body = intervention_response.json()
        assert intervention_body["interventions"][-1]["text"] == INTERVENTION
        assert intervention_body["control_revision"] == revision + 1

        # Resume: the discarded review runs again, then the second review and
        # the Leader synthesis; every prompt built after resume sees the block.
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"expected_revision": intervention_body["control_revision"]},
            headers=_headers(bots[0]),
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["paused"] is False
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    assert await _count(bench, DiscussionReviewRow) == 2

    resumed_calls = provider.calls[calls_before_release + 1 :]
    assert len(resumed_calls) == 3
    for call in resumed_calls:
        prompt = call["messages"][-1]["content"]
        assert "人工介入（后续生效）" in prompt
        assert INTERVENTION in prompt

    messages = await _messages(bench, session_id)
    logged = _interventions(messages)
    assert len(logged) == 1
    assert logged[0]["payload"]["text"] == INTERVENTION


@pytest.mark.asyncio
async def test_pause_cancel_bound_interrupts_inflight_call_as_unknown(
    app, monkeypatch
) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    monkeypatch.setattr(driver, "PAUSE_INFLIGHT_CANCEL_SECONDS", 0.2)
    entered, _gate = provider.block_once(_operation_is("review"))
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    provider.push(_review())
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered.wait(), timeout=5)
        requested = await driver.request_pause(bench, session_id)
        assert requested.pause_requested is True
        assert requested.paused is False

        record = await _wait_until(
            bench, session_id, lambda item: item.paused, timeout=5
        )
        assert record.pause_requested is False
        assert record.checkpoint["inflight_state"] == "interrupted_unknown"
        assert not driver.is_running(bench, session_id)
        assert await _count(bench, DiscussionReviewRow) == 0
        # No automatic replay: step/run do nothing while paused.
        assert await driver.step(bench, session_id) is False
        await driver.run_session(bench, session_id)
        await asyncio.sleep(0.05)
        assert not driver.is_running(bench, session_id)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_manual_end_with_large_spread_blocks_convergence_and_guards(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    # Round 1: proposals+reviews with a huge spread => the driver would start
    # round 2.  Block the first round-2 proposal call so the manual end lands
    # while the driver is in flight.
    entered, gate = provider.block_once(_nth_operation("proposal", 3))
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    provider.push(_review(value=3, feasibility=3, testability=3, clarity=3))  # 12
    provider.push(_review(value=5, feasibility=5, testability=5, clarity=4))  # 19
    provider.push(_proposal(LEADER_BODY + " 第二版"))
    provider.push(_proposal(ALICE_BODY + " 第二版"))
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered.wait(), timeout=5)
        current = await _get(bench, session_id)
        assert current.current_round == 2
        end_task = asyncio.create_task(
            client.post(
                f"/api/discussion-sessions/{session_id}/end-round",
                json={
                    "expected_revision": current.control_revision,
                    "reason": "分差过大，本轮不再自动继续",
                    "confirm": True,
                },
                headers=_headers(bots[0]),
            )
        )
        await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        gate.set()
        ended_response = await asyncio.wait_for(end_task, timeout=10)
        assert ended_response.status_code == 200, ended_response.text
        ended = ended_response.json()
        await _wait(bench, session_id)

        assert ended["status"] == "converged_pending_human"
        assert ended["paused"] is True
        assert ended["pause_requested"] is False
        assert ended["decision_package"] is None
        reason = ended["round_end_reason"]
        assert reason["kind"] == "manual"
        assert reason["text"] == "分差过大，本轮不再自动继续"
        assert reason["round_no"] == 2
        assert reason["actor"] == bots[0]
        assert reason["revision"] == ended["control_revision"]

        record = await _get(bench, session_id)
        assert record.status == "converged_pending_human"
        assert record.decision_package is None
        assert record.paused is True
        # No decision package / approval / grant side effects.
        assert ended["decision_package"] is None
        assert bench.runs == {}
        assert await _count(bench, ExecutionGrantRow) == 0
        messages = await _messages(bench, session_id)
        manual_events = [
            message
            for message in messages
            if message["payload"].get("event") == "manual_round_ended"
        ]
        assert len(manual_events) == 1

        # Ordinary continuation is blocked.
        resume = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={},
            headers=_headers(bots[0]),
        )
        assert resume.status_code == 409, resume.text
        run = await client.post(
            f"/api/discussion-sessions/{session_id}/run",
            headers=_headers(bots[0]),
        )
        assert run.status_code == 409, run.text
        assert await driver.step(bench, session_id) is False
        assert await driver.step(bench, session_id) is False

        # rounds/start requires the exact control revision.
        no_revision = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={},
            headers=_headers(bots[0]),
        )
        assert no_revision.status_code == 409, no_revision.text
        wrong_revision = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={"expected_revision": ended["control_revision"] + 99},
            headers=_headers(bots[0]),
        )
        assert wrong_revision.status_code == 409, wrong_revision.text
        calls_before_restart = len(provider.calls)
        started = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={"expected_revision": ended["control_revision"]},
            headers=_headers(bots[0]),
        )
        assert started.status_code == 200, started.text
        restarted = started.json()
        assert restarted["status"] == "round_n_revise"
        assert restarted["current_round"] == 3
        assert restarted["round_end_reason"] is None
        assert restarted["paused"] is False
        assert restarted["decision_package"] is None
        assert len(provider.calls) == calls_before_restart
        assert not driver.is_running(bench, session_id)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_pause_and_end_round_race_same_revision_conflicts(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        record = await _get(bench, session_id)
        revision = record.control_revision
        pause_response, end_response = await asyncio.gather(
            client.post(
                f"/api/discussion-sessions/{session_id}/pause",
                json={"expected_revision": revision},
                headers=_headers(bots[0]),
            ),
            client.post(
                f"/api/discussion-sessions/{session_id}/end-round",
                json={
                    "expected_revision": revision,
                    "reason": "race",
                    "confirm": True,
                },
                headers=_headers(bots[0]),
            ),
        )
    finally:
        await client.aclose()

    assert sorted([pause_response.status_code, end_response.status_code]) == [200, 409]
    loser = pause_response if pause_response.status_code == 409 else end_response
    assert loser.json()["error_category"] == "invalid_status"
    assert "revision" in loser.json()["detail"]

    record = await _get(bench, session_id)
    assert record.control_revision == revision + 1
    assert record.paused is True
    if end_response.status_code == 200:
        assert record.status == "converged_pending_human"
        assert record.round_end_reason["kind"] == "manual"
    else:
        assert record.round_end_reason is None


@pytest.mark.asyncio
async def test_restart_preserves_paused_interventions_and_round_end(tmp_path) -> None:
    models = load_models()
    bench1 = Workbench(
        Gateway(models, ScriptedProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    app1 = create_app()
    app1.state.workbench = bench1
    client1, bots, _project_id, session_id = await _setup(app1, ["Leader", "Alice"])
    try:
        pause_response = await client1.post(
            f"/api/discussion-sessions/{session_id}/pause",
            headers=_headers(bots[0]),
        )
        assert pause_response.status_code == 200, pause_response.text
        revision = pause_response.json()["control_revision"]
        assert pause_response.json()["paused"] is True

        intervention_response = await client1.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": revision, "text": "重启后仍要保留的介入"},
            headers=_headers(bots[0]),
        )
        assert intervention_response.status_code == 200, intervention_response.text
        revision = intervention_response.json()["control_revision"]

        end_response = await client1.post(
            f"/api/discussion-sessions/{session_id}/end-round",
            json={
                "expected_revision": revision,
                "reason": "重启前手动结束",
                "confirm": True,
            },
            headers=_headers(bots[0]),
        )
        assert end_response.status_code == 200, end_response.text
        before_restart = end_response.json()
    finally:
        await client1.aclose()
        await bench1.close()

    bench2 = Workbench(
        Gateway(models, ScriptedProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    try:
        record = await _get(bench2, session_id)
        assert record.paused is True
        assert record.status == "converged_pending_human"
        assert record.control_revision == before_restart["control_revision"]
        assert record.round_end_reason["kind"] == "manual"
        assert record.round_end_reason["text"] == "重启前手动结束"
        assert record.interventions[-1]["text"] == "重启后仍要保留的介入"

        # Recovery must not lift a manual end or a pause.
        await driver.recover_interrupted_sessions(bench2)
        after_recovery = await _get(bench2, session_id)
        assert after_recovery.paused is True
        assert after_recovery.round_end_reason["kind"] == "manual"
        assert await driver.step(bench2, session_id) is False
        await driver.run_session(bench2, session_id)
        await asyncio.sleep(0.05)
        assert not driver.is_running(bench2, session_id)
    finally:
        await bench2.close()


def test_threshold_2_0_remains_inclusive() -> None:
    budget = DiscussionBudget(max_rounds=3, score_gap_threshold=2.0)
    common = {
        "current_round": 1,
        "budget": budget,
        "tokens_used": 0,
        "elapsed_seconds": 0,
        "hard_gate_pass_counts": [3],
        "dissent_items": [],
        "all_required_hard_gates_pass": True,
    }
    assert (
        should_converge(DiscussionRoundState(**common, score_spread=1.99))[0]
        == "submit_human"
    )
    assert (
        should_converge(DiscussionRoundState(**common, score_spread=2.0))[0]
        == "submit_human"
    )
    assert (
        should_converge(DiscussionRoundState(**common, score_spread=2.01))[0]
        == "revise"
    )


@pytest.mark.asyncio
async def test_spread_equal_to_threshold_converges_end_to_end(app) -> None:
    bench = app.state.workbench
    provider = app.state.provider
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    # Two ballots on two proposals with totals 16 and 14 => spread exactly 2.0.
    provider.push(_review(value=4, feasibility=4, testability=4, clarity=4))
    provider.push(_review(value=4, feasibility=4, testability=3, clarity=3))
    provider.push(_leader_reply())
    try:
        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
    finally:
        await client.aclose()

    record = await _get(bench, session_id)
    assert record.status == "converged_pending_human"
    assert record.decision_package is not None
    messages = await _messages(bench, session_id)
    converged = [
        message
        for message in messages
        if message["payload"].get("event") == "converged"
    ]
    assert len(converged) == 1
    assert not any(
        message["payload"].get("event") == "forced_submit" for message in messages
    )


@pytest.mark.asyncio
async def test_legacy_session_payload_defaults_new_control_fields(app) -> None:
    bench = app.state.workbench
    payload = {
        "session_id": "legacy-h-session",
        "project_id": "project-1",
        "leader_bot_id": "leader",
        "participant_bot_ids": ["leader", "alice"],
        "status": "round1_independent",
        "current_round": 1,
        "budget": {"max_rounds": 3, "score_gap_threshold": 2.0},
        "requirement_snapshot_hash": "snapshot-hash",
    }
    validated = DiscussionSession.model_validate(payload)
    assert validated.control_revision == 0
    assert validated.pause_requested is False
    assert validated.control_epoch == 0
    assert validated.checkpoint == {}
    assert validated.interventions == []
    assert validated.round_end_reason is None

    async with bench.db_session() as session:
        session.add(
            DiscussionSessionRow(
                session_id="legacy-h-session",
                project_id="project-1",
                status="round1_independent",
                payload=payload,
            )
        )
        await session.commit()
        stored = await DiscussionSessionStore(session).get("legacy-h-session")
    assert stored.control_revision == 0
    assert stored.pause_requested is False
    assert stored.interventions == []
    assert stored.round_end_reason is None


@pytest.mark.asyncio
async def test_control_endpoints_reject_non_leader(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        pause = await client.post(
            f"/api/discussion-sessions/{session_id}/pause", headers=_headers(bots[1])
        )
        assert pause.status_code == 403
        intervention = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": 0, "text": "越权"},
            headers=_headers(bots[1]),
        )
        assert intervention.status_code == 403
        end_round = await client.post(
            f"/api/discussion-sessions/{session_id}/end-round",
            json={"expected_revision": 0, "reason": "越权", "confirm": True},
            headers=_headers(bots[1]),
        )
        assert end_round.status_code == 403
        start = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={"expected_revision": 0},
            headers=_headers(bots[1]),
        )
        assert start.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_skip_bot_ids_still_works_after_pause(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        paused = await client.post(
            f"/api/discussion-sessions/{session_id}/pause",
            headers=_headers(bots[0]),
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["paused"] is True

        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"skip_bot_ids": [bots[1]]},
            headers=_headers(bots[0]),
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["status"] == "terminated"
        assert body["participant_bot_ids"] == [bots[0]]
        assert not driver.is_running(bench, session_id)
    finally:
        await client.aclose()

    messages = await _messages(bench, session_id)
    assert any(
        message["payload"].get("event") == "bot_skipped" for message in messages
    )
    assert any(
        message["payload"].get("event") == "terminated" for message in messages
    )


@pytest.mark.asyncio
async def test_intervention_requires_paused_and_current_revision(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        not_paused = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": 0, "text": INTERVENTION},
            headers=_headers(bots[0]),
        )
        assert not_paused.status_code == 409, not_paused.text

        paused = await client.post(
            f"/api/discussion-sessions/{session_id}/pause",
            headers=_headers(bots[0]),
        )
        assert paused.status_code == 200
        revision = paused.json()["control_revision"]

        wrong = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": revision + 99, "text": INTERVENTION},
            headers=_headers(bots[0]),
        )
        assert wrong.status_code == 409, wrong.text

        too_long = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": revision, "text": "x" * 2001},
            headers=_headers(bots[0]),
        )
        assert too_long.status_code == 400, too_long.text

        accepted = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={"expected_revision": revision, "text": INTERVENTION},
            headers=_headers(bots[0]),
        )
        assert accepted.status_code == 200, accepted.text
        record = await _get(bench, session_id)
        assert record.interventions[-1]["round_no"] == record.current_round
        assert record.interventions[-1]["effective_after"] == record.current_round
    finally:
        await client.aclose()

@pytest.mark.asyncio
async def test_manual_end_cannot_reopen_until_cooperative_stop_finalizes(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            record = record.model_copy(
                update={
                    "status": "round_n_revise",
                    "paused": False,
                    "pause_requested": True,
                    "control_revision": 5,
                    "round_end_reason": {
                        "kind": "manual",
                        "text": "stop",
                        "round_no": 1,
                        "actor": bots[0],
                        "revision": 5,
                    },
                }
            )
            await store.save(record)
            await session.commit()
        with pytest.raises(InvalidStatus) as excinfo:
            await driver.start_round_after_manual_end(
                bench,
                session_id,
                actor_bot_id=bots[0],
                expected_revision=5,
            )
        assert str(excinfo.value) == "manual_end_not_finalized"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_repeated_pause_request_does_not_bump_revision(app) -> None:
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        first = await driver.request_pause(bench, session_id)
        assert first.paused is True
        second = await driver.request_pause(bench, session_id)
        assert second.paused is True
        assert second.control_revision == first.control_revision
        assert second.control_epoch == first.control_epoch
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_round_start_honours_expected_revision_outside_manual_end(app) -> None:
    from app.discussion.proposals import start_round

    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            record = record.model_copy(
                update={
                    "status": "converged_pending_human",
                    "decision_package": None,
                    "control_revision": 5,
                }
            )
            await store.save(record)
            await session.commit()

        async with bench.db_session() as session:
            with pytest.raises(InvalidStatus) as excinfo:
                await start_round(
                    session_id,
                    None,
                    actor_bot_id=bots[0],
                    session=session,
                    expected_revision=4,
                )
            assert str(excinfo.value) == "revision_conflict"
            await session.rollback()

        async with bench.db_session() as session:
            started = await start_round(
                session_id,
                None,
                actor_bot_id=bots[0],
                session=session,
                expected_revision=5,
            )
            await session.commit()
        assert started.current_round == 1
        assert started.control_revision == 6
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# generation identity / cancellation races (F1) and pause-vs-decision (F4)
# ---------------------------------------------------------------------------


async def _proposal_rows(
    bench, session_id: str, round_no: int | None = None
) -> list[DiscussionProposalRow]:
    async with bench.db_session() as session:
        stmt = select(DiscussionProposalRow).where(
            DiscussionProposalRow.session_id == session_id
        )
        if round_no is not None:
            stmt = stmt.where(DiscussionProposalRow.round == round_no)
        stmt = stmt.order_by(
            DiscussionProposalRow.round, DiscussionProposalRow.author_bot_id
        )
        return list((await session.execute(stmt)).scalars())


async def _wait_until_paused(bench, session_id: str, timeout: float = 10.0):
    return await _wait_until(bench, session_id, lambda record: record.paused, timeout)


async def _poll_reopen(client, session_id: str, actor: str, revision: int):
    """Client-style CAS retry: reopen only once the cooperative stop finalized."""

    async def _poll() -> dict:
        last = None
        for _ in range(400):
            response = await client.post(
                f"/api/discussion-sessions/{session_id}/rounds/start",
                json={"expected_revision": revision},
                headers=_headers(actor),
            )
            last = {"status_code": response.status_code, "text": response.text}
            if response.status_code == 200:
                return last
            await asyncio.sleep(0.01)
        return last

    return await asyncio.wait_for(_poll(), timeout=15)


@pytest.mark.asyncio
async def test_reverse_returns_after_manual_end_reopen_never_pollute_new_round(app) -> None:
    """F1(a): proposals returning A/B in reverse must never reach the new round."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    end_task: asyncio.Task | None = None
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)
        provider.push(_proposal(OLD_LEADER))
        provider.push(_proposal(OLD_ALICE))
        current = await _get(bench, session_id)
        end_task = asyncio.create_task(
            client.post(
                f"/api/discussion-sessions/{session_id}/end-round",
                json={
                    "expected_revision": current.control_revision,
                    "reason": "reverse return race",
                    "confirm": True,
                },
                headers=_headers(leader),
            )
        )
        manual = await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        revision = manual.control_revision
        reopens = asyncio.create_task(
            _poll_reopen(client, session_id, leader, revision)
        )
        # Alice returns first (reverse of the participant order), then a reopen
        # may slip in before Leader's in-flight result returns.
        gate_alice.set()
        await asyncio.sleep(0.2)
        gate_leader.set()
        await _wait(bench, session_id)
        ended = await asyncio.wait_for(end_task, timeout=10)
        end_task = None
        reopened = await reopens
        assert ended.status_code == 200, ended.text
        assert reopened["status_code"] == 200, reopened
        record = await _get(bench, session_id)
        assert record.current_round == 2
        rows = await _proposal_rows(bench, session_id, 2)
        bodies = [row.body_md for row in rows]
        assert all(OLD_LEADER not in body for body in bodies), bodies
        assert all(OLD_ALICE not in body for body in bodies), bodies
        assert rows == [], [row.body_md for row in rows]

        # The new runner must build round 2 from scratch and reach review.
        await _wait(bench, session_id)
        provider.push(_proposal(NEW_LEADER))
        provider.push(_proposal(NEW_ALICE))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
        final = await _get(bench, session_id)
        assert final.status == "converged_pending_human", final.status
        rows = await _proposal_rows(bench, session_id, 2)
        assert len(rows) == 2, [row.body_md for row in rows]
        bodies = [row.body_md for row in rows]
        assert any(NEW_LEADER in body for body in bodies), bodies
        assert any(NEW_ALICE in body for body in bodies), bodies
        assert all(OLD_LEADER not in body and OLD_ALICE not in body for body in bodies)
    finally:
        gate_leader.set()
        gate_alice.set()
        if end_task is not None and not end_task.done():
            end_task.cancel()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001 - cleanup must not mask the assertion
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_reopen_blocked_until_cooperative_stop_finalizes(app) -> None:
    """F1(f): reopen is only allowed after every in-flight call stopped."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    end_task: asyncio.Task | None = None
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)
        provider.push(_proposal(OLD_LEADER))
        provider.push(_proposal(OLD_ALICE))
        current = await _get(bench, session_id)
        end_task = asyncio.create_task(
            client.post(
                f"/api/discussion-sessions/{session_id}/end-round",
                json={
                    "expected_revision": current.control_revision,
                    "reason": "wait for stop",
                    "confirm": True,
                },
                headers=_headers(leader),
            )
        )
        manual = await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        revision = manual.control_revision
        gate_alice.set()
        await asyncio.sleep(0.2)
        early = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={"expected_revision": revision},
            headers=_headers(leader),
        )
        assert early.status_code == 409, (
            "reopen must stay blocked while the other call is still in flight: "
            f"{early.status_code} {early.text}"
        )
        assert early.json()["detail"] == "manual_end_not_finalized", early.text
        assert (await _get(bench, session_id)).paused is False

        gate_leader.set()
        ended = await asyncio.wait_for(end_task, timeout=10)
        end_task = None
        assert ended.status_code == 200, ended.text
        assert ended.json()["paused"] is True
        paused = await _wait_until_paused(bench, session_id)
        assert paused.current_round == 1
        assert paused.decision_package is None
        reopened = await client.post(
            f"/api/discussion-sessions/{session_id}/rounds/start",
            json={"expected_revision": revision},
            headers=_headers(leader),
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["current_round"] == 2
    finally:
        gate_leader.set()
        gate_alice.set()
        if end_task is not None and not end_task.done():
            end_task.cancel()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_pause_intervention_resume_regenerates_with_intervention(app) -> None:
    """F1(b): paused proposals are never persisted; resumed prompts see the block."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    pause_task: asyncio.Task | None = None
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)
        provider.push(_proposal(OLD_LEADER))
        provider.push(_proposal(OLD_ALICE))
        pause_task = asyncio.create_task(
            client.post(
                f"/api/discussion-sessions/{session_id}/pause",
                headers=_headers(leader),
            )
        )
        await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        gate_alice.set()
        await asyncio.sleep(0.1)
        gate_leader.set()
        paused_response = await asyncio.wait_for(pause_task, timeout=10)
        pause_task = None
        assert paused_response.status_code == 200, paused_response.text
        paused = paused_response.json()
        assert paused["paused"] is True
        assert paused["pause_requested"] is False
        assert await _proposal_rows(bench, session_id) == []
        assert await _count(bench, DiscussionReviewRow) == 0
        assert paused["checkpoint"]["inflight_state"] == "response_received"

        intervention = await client.post(
            f"/api/discussion-sessions/{session_id}/interventions",
            json={
                "expected_revision": paused["control_revision"],
                "text": INTERVENTION,
            },
            headers=_headers(leader),
        )
        assert intervention.status_code == 200, intervention.text
        revision = intervention.json()["control_revision"]

        started_before = len(provider.started)
        finished_before = len(provider.finished)
        provider.push(_proposal(NEW_LEADER))
        provider.push(_proposal(NEW_ALICE))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"expected_revision": revision},
            headers=_headers(leader),
        )
        assert resumed.status_code == 200, resumed.text
        await _wait(bench, session_id)
        record = await _get(bench, session_id)
        assert record.status == "converged_pending_human"
        rows = await _proposal_rows(bench, session_id, record.current_round)
        bodies = [row.body_md for row in rows]
        assert len(rows) == 2, bodies
        assert all(OLD_LEADER not in body and OLD_ALICE not in body for body in bodies)
        resumed_calls = provider.started[started_before:]
        assert len(resumed_calls) >= 3, len(resumed_calls)
        returned_after_resume = provider.finished[finished_before:]
        assert returned_after_resume, "the resumed generation made no model call"
        for call in returned_after_resume:
            prompt = call["messages"][-1]["content"]
            assert INTERVENTION in prompt, prompt[:200]
    finally:
        gate_leader.set()
        gate_alice.set()
        if pause_task is not None and not pause_task.done():
            pause_task.cancel()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_pause_during_compression_retry_stops_before_next_call(app) -> None:
    """F1(c): a pause while the compression retry is pending stops all old work."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    provider.push("超长方案" * 2000)  # > 6000 chars => compression retry
    provider.push(_proposal(OLD_ALICE))
    entered_retry, gate_retry = provider.block_key("proposal:Leader", nth=2)
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_retry.wait(), timeout=5)
        provider.push(_proposal(OLD_ALICE))
        await driver.request_pause(bench, session_id)
        await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        calls_at_pause = len(provider.started)
        gate_retry.set()
        paused = await _wait_until_paused(bench, session_id)
        assert paused.pause_requested is False
        assert await _proposal_rows(bench, session_id) == []
        await asyncio.sleep(0.1)
        assert len(provider.started) == calls_at_pause, (
            "no further old-prompt call may start after the pause: "
            f"{len(provider.started)} != {calls_at_pause}"
        )
    finally:
        gate_retry.set()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_provider_cancel_bound_writes_nothing_and_new_runner_unaffected(
    app, monkeypatch
) -> None:
    """F1(d): bounded cancel => zero writes, fresh runner works."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    monkeypatch.setattr(driver, "PAUSE_INFLIGHT_CANCEL_SECONDS", 0.2)
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)
        started_at = time.monotonic()
        await driver.request_pause(bench, session_id)
        paused = await _wait_until_paused(bench, session_id, timeout=5)
        elapsed = time.monotonic() - started_at
        assert elapsed < 3.0, elapsed
        assert paused.checkpoint["inflight_state"] == "interrupted_unknown"
        assert paused.checkpoint["round"] == 1
        assert paused.checkpoint.get("epoch") == paused.control_epoch
        work_keys = paused.checkpoint.get("work_keys") or []
        assert len(work_keys) == 2, work_keys
        assert all(key.startswith("proposal:") for key in work_keys), work_keys
        assert await _proposal_rows(bench, session_id) == []
        # The cancelled calls never return a result: cancellation aborts them
        # inside ``await gate.wait()``, so nothing can reach the writer.  Assert
        # that honestly instead of claiming a "late result" was rejected; the
        # transaction-level rejection of a stale generated write is covered by
        # ``test_stale_generation_cannot_submit_proposal``.
        finished_before = len(provider.finished)
        gate_leader.set()
        gate_alice.set()
        await asyncio.sleep(0.05)
        assert len(provider.finished) == finished_before
        assert await _proposal_rows(bench, session_id) == []

        provider.push(_proposal(NEW_LEADER))
        provider.push(_proposal(NEW_ALICE))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"expected_revision": paused.control_revision},
            headers=_headers(leader),
        )
        assert resumed.status_code == 200, resumed.text
        await _wait(bench, session_id)
        record = await _get(bench, session_id)
        assert record.status == "converged_pending_human", record.status
        rows = await _proposal_rows(bench, session_id, record.current_round)
        bodies = [row.body_md for row in rows]
        assert len(rows) == 2, bodies
        assert all(OLD_LEADER not in body and OLD_ALICE not in body for body in bodies)
    finally:
        gate_leader.set()
        gate_alice.set()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_resume_replaces_old_driver_handle_with_new_generation(app) -> None:
    """F1(e): the old runner must not own the handle/checkpoint after a resume."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)
        old_task = driver._tasks(bench)[session_id]
        await driver.request_pause(bench, session_id)
        paused = await _wait_until(
            bench, session_id, lambda record: record.pause_requested, timeout=5
        )
        epoch_before = paused.control_epoch
        # The fresh generation's first call is blocked so the handle stays visible.
        entered_new, gate_new = provider.block_key("proposal:Leader")
        provider.push(_proposal(NEW_LEADER))
        provider.push(_proposal(NEW_ALICE))
        provider.push(_review())
        provider.push(_review())
        provider.push(_leader_reply())
        resumed = await client.post(
            f"/api/discussion-sessions/{session_id}/resume",
            json={"expected_revision": paused.control_revision},
            headers=_headers(leader),
        )
        assert resumed.status_code == 200, resumed.text
        await asyncio.wait_for(entered_new.wait(), timeout=5)
        record = await _get(bench, session_id)
        assert record.control_epoch > epoch_before
        assert record.paused is False
        assert record.pause_requested is False
        new_task = driver._tasks(bench).get(session_id)
        assert new_task is not None and new_task is not old_task, (
            "resume must replace the old driver handle instead of reusing it"
        )
        assert old_task.done()
        gate_new.set()
        await _wait(bench, session_id)
        final = await _get(bench, session_id)
        assert final.status == "converged_pending_human", final.status
        rows = await _proposal_rows(bench, session_id, final.current_round)
        bodies = [row.body_md for row in rows]
        assert len(rows) == 2, bodies
        assert all(OLD_LEADER not in body and OLD_ALICE not in body for body in bodies)
    finally:
        gate_leader.set()
        gate_alice.set()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bump_epoch",
    [True, False],
    ids=["pause_bumped_epoch", "pause_same_epoch"],
)
async def test_pause_wins_before_decision_commit(
    app, monkeypatch, bump_epoch: bool
) -> None:
    """F4: a pause committed after the last checkpoint still vetoes the commit.

    The wrapper replaces the module-level ``driver.submit_decision`` (what
    ``_leader_submit`` actually calls), so ``leader:before_commit`` returns
    normally first; only then is the pause intent persisted and the real commit
    attempted.  ``pause_bumped_epoch=True`` mirrors ``request_pause`` (epoch +
    revision bump, original generation token is passed, so both the generation
    guard and the pause veto reject).  ``pause_same_epoch`` keeps the captured
    generation current, isolating the in-transaction ``pause_requested`` veto:
    deleting that veto creates a package and fails this test.
    """
    from app.discussion.decision import submit_decision as real_submit_decision

    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    provider.push(_review(value=4, feasibility=4, testability=4, clarity=4))
    provider.push(_review(value=4, feasibility=4, testability=3, clarity=3))
    entered, gate = provider.block_key("synthesis:Leader")
    observed: dict = {}

    async def _race_submit(
        session_id_: str,
        body_md: str,
        dissent_items: list[str],
        *,
        actor_bot_id: str,
        session,
        generation=None,
    ):
        # Checkpoint has already returned; land the pause intent in its own
        # committed transaction before the decision transaction runs.
        async with bench.db_session() as race_session:
            store = DiscussionSessionStore(race_session)
            locked = await store.get_locked(session_id_)
            fields: dict = {
                "pause_requested": True,
                "control_revision": locked.control_revision + 1,
            }
            if bump_epoch:
                fields["control_epoch"] = locked.control_epoch + 1
            await store.save(locked.model_copy(update=fields))
            await race_session.commit()
        observed["generation"] = generation
        return await real_submit_decision(
            session_id_,
            body_md,
            dissent_items,
            actor_bot_id=actor_bot_id,
            session=session,
            generation=generation,
        )

    monkeypatch.setattr(driver, "submit_decision", _race_submit)
    try:
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert (await _get(bench, session_id)).status == "converged_pending_human"
        provider.push(_leader_reply())
        gate.set()
        await _wait(bench, session_id)
        record = await _get(bench, session_id)
        assert observed.get("generation") is not None, (
            "the background leader commit must still carry its generation token"
        )
        assert record.decision_package is None, "a pause intent must veto the package"
        assert record.paused is True
        assert record.pause_requested is False
    finally:
        gate.set()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_decision_commit_wins_before_pause(app) -> None:
    """F4: when the package already exists, a pause request must not fake a stop."""
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    provider.push(_proposal(LEADER_BODY))
    provider.push(_proposal(ALICE_BODY))
    provider.push(_review(value=4, feasibility=4, testability=4, clarity=4))  # 16
    provider.push(_review(value=4, feasibility=4, testability=3, clarity=3))  # 14
    provider.push(_leader_reply())
    try:
        await driver.run_session(bench, session_id)
        await _wait(bench, session_id)
        committed = await _get(bench, session_id)
        assert committed.decision_package is not None
        paused = await driver.request_pause(bench, session_id)
        assert paused.paused is False, "pausing must not pretend to stop a decided session"
        assert paused.pause_requested is False
        assert paused.control_epoch == committed.control_epoch
        assert paused.control_revision == committed.control_revision
        assert paused.decision_package is not None
        route = await asyncio.wait_for(
            client.post(
                f"/api/discussion-sessions/{session_id}/pause",
                headers=_headers(leader),
            ),
            timeout=2,
        )
        assert route.status_code == 200, route.text
        assert route.json()["paused"] is False
        assert route.json()["decision_package"] is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_generation_cannot_submit_decision(app) -> None:
    """F4: only the generation captured before the model call may commit."""
    from app.discussion.decision import submit_decision
    from app.discussion.models import DiscussionGenerationToken

    bench = app.state.workbench
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            await store.save(
                record.model_copy(update={"status": "converged_pending_human"})
            )
            await session.commit()
        record = await _get(bench, session_id)
        stale = DiscussionGenerationToken(
            session_id=session_id,
            round_no=record.current_round,
            control_epoch=record.control_epoch,
            operation="synthesis",
            work_key="synthesis:test",
        )
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            locked = await store.get_locked(session_id)
            await store.save(
                locked.model_copy(update={"control_epoch": locked.control_epoch + 1})
            )
            await session.commit()
        async with bench.db_session() as session:
            with pytest.raises(InvalidStatus):
                await submit_decision(
                    session_id,
                    "# stale",
                    [],
                    actor_bot_id=leader,
                    session=session,
                    generation=stale,
                )
            await session.rollback()
        assert (await _get(bench, session_id)).decision_package is None

        current = await _get(bench, session_id)
        fresh = DiscussionGenerationToken(
            session_id=session_id,
            round_no=current.current_round,
            control_epoch=current.control_epoch,
            operation="synthesis",
            work_key="synthesis:test",
        )
        async with bench.db_session() as session:
            package = await submit_decision(
                session_id,
                "# fresh",
                [],
                actor_bot_id=leader,
                session=session,
                generation=fresh,
            )
            await session.commit()
        assert package.body_md == "# fresh"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_generation_cannot_submit_proposal(app) -> None:
    """F1: the proposal write transaction itself rejects a stale generation."""
    from app.discussion.models import DiscussionGenerationToken
    from app.discussion.proposals import submit_proposal

    bench = app.state.workbench
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            record = record.model_copy(update={"status": "round1_independent"})
            await store.save(record)
            await session.commit()
        record = await _get(bench, session_id)
        stale = DiscussionGenerationToken(
            session_id=session_id,
            round_no=record.current_round,
            control_epoch=record.control_epoch,
            operation="proposal",
            work_key=f"proposal:{leader}",
        )
        # Same round, newer control epoch: the pre-pause generation is stale.
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            locked = await store.get_locked(session_id)
            await store.save(
                locked.model_copy(update={"control_epoch": locked.control_epoch + 1})
            )
            await session.commit()
        async with bench.db_session() as session:
            with pytest.raises(InvalidStatus):
                await submit_proposal(
                    session_id,
                    leader,
                    "# stale proposal",
                    session=session,
                    generation=stale,
                )
            await session.rollback()
        assert await _proposal_rows(bench, session_id) == [], (
            "a stale generation must not create a proposal row"
        )

        current = await _get(bench, session_id)
        fresh = DiscussionGenerationToken(
            session_id=session_id,
            round_no=current.current_round,
            control_epoch=current.control_epoch,
            operation="proposal",
            work_key=f"proposal:{leader}",
        )
        async with bench.db_session() as session:
            submitted = await submit_proposal(
                session_id,
                leader,
                "# fresh proposal",
                session=session,
                generation=fresh,
            )
            await session.commit()
        assert submitted["proposal_id"]
        rows = await _proposal_rows(bench, session_id)
        assert len(rows) == 1, [row.body_md for row in rows]
        assert rows[0].body_md == "# fresh proposal"
        assert rows[0].round == current.current_round
        assert rows[0].author_bot_id == leader
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_generation_cannot_submit_review(app) -> None:
    """F1: the review write transaction itself rejects a stale generation."""
    from app.discussion.cross_review import submit_review
    from app.discussion.models import DiscussionGenerationToken, ReviewBallot

    bench = app.state.workbench
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, alice = bots
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            record = record.model_copy(
                update={"status": "cross_review", "current_round": 1}
            )
            await store.save(record)
            session.add(
                DiscussionProposalRow(
                    proposal_id="proposal-alice",
                    session_id=session_id,
                    author_bot_id=alice,
                    round=1,
                    sealed=0,
                    body_md=_proposal(ALICE_BODY),
                )
            )
            await session.commit()
        record = await _get(bench, session_id)
        ballot = ReviewBallot.model_validate(
            {
                **_review(),
                "reviewer_bot_id": leader,
                "proposal_id": "proposal-alice",
            }
        )
        stale = DiscussionGenerationToken(
            session_id=session_id,
            round_no=record.current_round,
            control_epoch=record.control_epoch,
            operation="review",
            work_key=f"review:{leader}:proposal-alice",
        )
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            locked = await store.get_locked(session_id)
            await store.save(
                locked.model_copy(update={"control_epoch": locked.control_epoch + 1})
            )
            await session.commit()
        async with bench.db_session() as session:
            with pytest.raises(InvalidStatus):
                await submit_review(
                    session_id, ballot, session=session, generation=stale
                )
            await session.rollback()
        assert await _count(bench, DiscussionReviewRow) == 0, (
            "a stale generation must not create a review row"
        )

        current = await _get(bench, session_id)
        fresh = DiscussionGenerationToken(
            session_id=session_id,
            round_no=current.current_round,
            control_epoch=current.control_epoch,
            operation="review",
            work_key=f"review:{leader}:proposal-alice",
        )
        async with bench.db_session() as session:
            await submit_review(session_id, ballot, session=session, generation=fresh)
            await session.commit()
        assert await _count(bench, DiscussionReviewRow) == 1
        async with bench.db_session() as session:
            rows = list(
                (await session.execute(select(DiscussionReviewRow))).scalars()
            )
        assert len(rows) == 1
        assert rows[0].reviewer_bot_id == leader
        assert rows[0].proposal_id == "proposal-alice"
        assert rows[0].payload["reviewer_bot_id"] == leader
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_pause_wins_before_manual_decision_commit(app) -> None:
    """F4: the in-lock pause veto is load-bearing for the manual decision route.

    The manual route calls ``submit_decision(..., generation=None)``, so the
    pure generation helper cannot veto a pause here: only
    ``decision._submit_once``'s locked ``pause_requested`` check can.  Deleting
    that check makes this test create a package and fail.
    """
    bench = app.state.workbench
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    leader, _alice = bots
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            record = record.model_copy(update={"status": "converged_pending_human"})
            await store.save(record)
            await session.commit()
        # request_pause landed after a hypothetical out-of-transaction check and
        # before the manual submit transaction.
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            locked = await store.get_locked(session_id)
            await store.save(
                locked.model_copy(
                    update={
                        "pause_requested": True,
                        "control_epoch": locked.control_epoch + 1,
                        "control_revision": locked.control_revision + 1,
                    }
                )
            )
            await session.commit()
        response = await client.post(
            f"/api/discussion-sessions/{session_id}/submit-decision",
            json={"body_md": "# must not commit", "dissent_items": []},
            headers=_headers(leader),
        )
        assert response.status_code == 409, response.text
        assert response.json()["error_category"] == "invalid_status"
        record = await _get(bench, session_id)
        assert record.decision_package is None, (
            "a pause intent must veto the manual decision package"
        )
    finally:
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_pause_finalizer_does_not_repause_resumed_session(
    app, monkeypatch
) -> None:
    """H1: a finalizer that read ``pause_requested`` before a resume must not
    publish ``paused=True`` after the resume has committed.

    The interleaving is reproduced deterministically: the pause intent is
    persisted, the caller captures its pre-resume snapshot, the resume state is
    committed, and only then does the finalizer lock the row.  ``driver._get``
    is patched so the first out-of-transaction read (inside
    ``_finalize_control_stop``) still sees the stale pause intent while every
    later read goes to SQLite; the new lock-side guard is what must reject the
    stale stop.
    """
    bench = app.state.workbench
    client, _bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            await store.save(
                record.model_copy(
                    update={
                        "pause_requested": True,
                        "control_revision": record.control_revision + 1,
                        "control_epoch": record.control_epoch + 1,
                    }
                )
            )
            await session.commit()

        # What the caller reads before the resume wins.
        stale = await _get(bench, session_id)
        assert stale.paused is False
        assert stale.pause_requested is True

        # Resume commits while the finalizer is between that read and its own
        # write transaction.
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            resumed_epoch = record.control_epoch + 1
            await store.save(
                record.model_copy(
                    update={
                        "paused": False,
                        "pause_requested": False,
                        "control_revision": record.control_revision + 1,
                        "control_epoch": resumed_epoch,
                    }
                )
            )
            await session.commit()

        real_get = driver._get
        calls = {"count": 0}

        async def stale_first_get(bench_, session_id_):
            calls["count"] += 1
            if calls["count"] == 1:
                return stale
            return await real_get(bench_, session_id_)

        monkeypatch.setattr(driver, "_get", stale_first_get)
        finalized = await driver._finalize_control_stop(
            bench,
            session_id,
            driver.CooperativeStop("pause_requested", phase="driver_exit"),
        )
        assert calls["count"] >= 1
        assert finalized is not None
        assert finalized.paused is False, (
            "a stale finalizer must not re-pause a resumed session"
        )

        record = await _get(bench, session_id)
        assert record.paused is False
        assert record.pause_requested is False
        assert record.control_epoch == resumed_epoch, (
            "the stale stop must not roll the control epoch back"
        )
        assert record.control_revision == stale.control_revision + 1
        messages = await _messages(bench, session_id)
        assert not any(
            message["payload"].get("event") == "paused" for message in messages
        ), "a stale finalizer must not emit a paused event"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_round_start_rejects_pending_pause(app) -> None:
    """M1: a pending pause vetoes the round write inside the transaction."""
    from app.discussion.proposals import start_round

    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    bench = app.state.workbench
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            await store.save(
                record.model_copy(
                    update={
                        "status": "cross_review",
                        "current_round": 1,
                        "pause_requested": True,
                        "control_revision": record.control_revision + 1,
                        "control_epoch": record.control_epoch + 1,
                    }
                )
            )
            await session.commit()
        before = await _get(bench, session_id)

        async with bench.db_session() as session:
            with pytest.raises(InvalidStatus) as excinfo:
                await start_round(
                    session_id, None, actor_bot_id=bots[0], session=session
                )
            assert str(excinfo.value) == "paused"
            await session.rollback()

        blocked = await _get(bench, session_id)
        assert blocked.current_round == before.current_round
        assert blocked.status == "cross_review"
        assert blocked.control_epoch == before.control_epoch
        assert blocked.control_revision == before.control_revision
        assert blocked.pause_requested is True

        # Once the pause is no longer pending the same call works again.
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            await store.save(record.model_copy(update={"pause_requested": False}))
            await session.commit()
        async with bench.db_session() as session:
            started = await start_round(
                session_id, None, actor_bot_id=bots[0], session=session
            )
            await session.commit()
        assert started.current_round == 2
        assert started.status == "round_n_revise"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cooperative_pause_not_published_while_sibling_in_flight(
    app, monkeypatch
) -> None:
    """F1: ``paused`` must stay False until every sibling model call is done.

    Both proposal calls are blocked.  Pause is requested, then only Leader's
    gate is opened.  A spy proves Leader's response reached its after-response
    checkpoint (where a subtask may only raise ``CooperativeStop``); Alice is
    still blocked at that moment, so the DB must not be paused yet.
    """
    bench = app.state.workbench
    provider = app.state.provider
    client, bots, _project_id, session_id = await _setup(app, ["Leader", "Alice"])
    entered_leader, gate_leader = provider.block_key("proposal:Leader")
    entered_alice, gate_alice = provider.block_key("proposal:Alice")
    real_checkpoint = driver._checkpoint
    after_response = asyncio.Event()

    async def checkpoint_spy(bench_, session_id_, *, phase, **kwargs):
        try:
            return await real_checkpoint(bench_, session_id_, phase=phase, **kwargs)
        finally:
            if phase == "proposal:after_response":
                after_response.set()

    monkeypatch.setattr(driver, "_checkpoint", checkpoint_spy)
    try:
        provider.push(_proposal(LEADER_BODY))
        provider.push(_proposal(ALICE_BODY))
        await driver.run_session(bench, session_id)
        await asyncio.wait_for(entered_leader.wait(), timeout=5)
        await asyncio.wait_for(entered_alice.wait(), timeout=5)

        requested = await driver.request_pause(bench, session_id)
        assert requested.paused is False
        assert requested.pause_requested is True

        # Only the Leader result may return; Alice stays blocked.
        gate_leader.set()
        await asyncio.wait_for(after_response.wait(), timeout=5)
        await asyncio.sleep(0.05)
        mid = await _get(bench, session_id)
        assert mid.paused is False, (
            "paused must not be published while Alice's call is still in flight"
        )
        assert mid.pause_requested is True
        assert await _proposal_rows(bench, session_id) == []
        assert not gate_alice.is_set()

        # Both subtasks are now done/isolated: the coordinator may publish the
        # stop and the old generated texts must be discarded.
        gate_alice.set()
        paused = await _wait_until_paused(bench, session_id)
        assert paused.paused is True
        assert paused.pause_requested is False
        assert await _proposal_rows(bench, session_id) == []
    finally:
        gate_leader.set()
        gate_alice.set()
        try:
            await driver.terminate_session(bench, session_id)
        except Exception:  # noqa: BLE001
            pass
        await client.aclose()
