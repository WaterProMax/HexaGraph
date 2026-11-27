"""讨论流第 5 步（设计规格）与第 6 步（任务拆解）的 API 行为和 workflow 投影。"""

from __future__ import annotations

import copy

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.discussion.models import DecisionPackage, DiscussionBudget, DiscussionSession
from app.discussion.session_store import DiscussionSessionStore
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import RunState, Workbench
from app.settings import load_models, load_roles
from app.workflow.projection import project_workflow_projection


SPEC = {
    "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
    "users": [{"name": "学生"}],
    "scenarios": [{"code": "S1", "title": "期末周找空位"}],
    "features": [
        {
            "code": "F1",
            "kind": "功能",
            "title": "查看空闲座位",
            "story": "学生查看座位",
            "scenario": "S1",
            "priority": "P0",
            "impact": "减少找座位时间",
            "acceptance": ["显示剩余座位数与开放时段"],
            "manual": [False],
            "sources": ["已批准的需求规格"],
            "out_of_scope": False,
        }
    ],
    "out_of_scope": [],
    "nonfunc": [],
    "open_questions": [],
    "review_followup": [],
}

DESIGN = {
    "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
    "modules": [
        {"code": "M1", "name": "座位查询", "responsibility": "返回空闲座位", "sources": ["F1"], "provides": ["C1"], "depends_on": [], "data": []},
        {"code": "M2", "name": "学生端页面", "responsibility": "展示座位", "sources": ["F1"], "provides": [], "depends_on": ["M1"], "data": []},
    ],
    "interfaces": [
        {"code": "C1", "provider": "M1", "consumers": ["M2"], "inputs": [], "outputs": [], "errors": []}
    ],
    "data": [],
    "decisions": [],
    "contingencies": [],
    "appendix": "",
}

PACKAGES = [
    {"code": "W1", "title": "查询基座", "module": "M1", "summary": "座位查询", "sources": ["F1"]},
    {"code": "W2", "title": "查询测试", "module": "M1", "summary": "验收测试", "sources": ["F1"]},
    {"code": "W3", "title": "学生端页面", "module": "M2", "summary": "展示座位", "sources": ["F1"]},
]


def _task(code: str, kind: str, parent: str, module: str, deps: list[str], path: str) -> dict:
    return {
        "code": code, "title": code, "parent": parent, "kind": kind, "module": module,
        "sources": ["F1"], "description": code, "inputs": [],
        "write_set": [path], "outputs": [path],
        "acceptance": [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": "F1"}],
        "depends_on": deps, "points": 1, "priority": "P0", "role": "coder",
    }


TASKS = [
    _task("T-01", "impl", "W1", "M1", [], "src/seats.py"),
    _task("T-02", "test", "W2", "M1", ["T-01"], "tests/test_seats.py"),
    _task("T-03", "impl", "W3", "M2", ["T-01"], "src/page.py"),
]

REVIEW_ARCH = {"reviewer": "架构", "dimension": "架构一致性", "score": 5, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]}
REVIEW_QUALITY = {"reviewer": "质量", "dimension": "实现质量", "score": 5, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]}


def _design_queue() -> list[dict]:
    """leader_spec → architect → 双评审。"""
    return [
        {"spec": copy.deepcopy(SPEC)},
        copy.deepcopy(DESIGN),
        copy.deepcopy(REVIEW_ARCH),
        copy.deepcopy(REVIEW_QUALITY),
    ]


def _plan_queue() -> list[dict]:
    """LeaderOutline（保持 SPEC/DESIGN）→ scripted TaskBatch。"""
    return [
        {"spec": copy.deepcopy(SPEC), "design": copy.deepcopy(DESIGN), "work_packages": copy.deepcopy(PACKAGES)},
        {"tasks": copy.deepcopy(TASKS)},
    ]


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


@pytest.mark.asyncio
async def test_plan_rejected_without_approved_spec_and_creates_no_run(app) -> None:
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


@pytest.mark.asyncio
async def test_design_rejected_without_approved_spec(app) -> None:
    bench = app.state.workbench
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=False)

    res = await client.post(
        f"/api/discussion-sessions/{session_id}/design", headers={"X-Bot-Id": leader}
    )

    assert res.status_code == 409, res.text
    assert bench.runs == {}


@pytest.mark.asyncio
async def test_plan_requires_design_approval_first(app) -> None:
    bench = app.state.workbench
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=True)

    res = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_category"] == "design_not_approved"
    assert bench.runs == {}


@pytest.mark.asyncio
async def test_design_creates_stage5_run_with_design_gate(app) -> None:
    bench = app.state.workbench
    provider = bench.gateway.provider
    provider.queue.extend(_design_queue())
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=True)

    res = await client.post(
        f"/api/discussion-sessions/{session_id}/design", headers={"X-Bot-Id": leader}
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    run = bench.runs[run_id]
    assert run.engine.current == "5"
    assert run.artifacts["discussion_session_id"] == session_id
    assert run.artifacts["baseline_SPEC"] == "1.0"
    assert run.artifacts["design"]["modules"]
    assert run.artifacts["design_reviews"]
    gate = run.gates[-1]
    assert gate["kind"] == "DESIGN基线确认"
    assert gate["status"] == "pending"
    assert not any(g["kind"] == "PLAN基线确认" for g in run.gates)

    run_view = await client.get(f"/api/runs/{run_id}")
    assert run_view.json()["workflow"]["stage"] == "design_pending"
    assert run_view.json()["workflow"]["design_approved"] is False

    # 幂等：再次 /design 不重新生成。
    calls_before = len(provider.calls)
    again = await client.post(
        f"/api/discussion-sessions/{session_id}/design", headers={"X-Bot-Id": leader}
    )
    assert again.status_code == 200, again.text
    assert again.json()["run_id"] == run_id
    assert len(provider.calls) == calls_before

    # 设计未确认前 /plan 仍被拒绝。
    premature = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )
    assert premature.status_code == 409
    assert premature.json()["error_category"] == "design_not_approved"


@pytest.mark.asyncio
async def test_design_approval_then_plan_reaches_plan_pending(app) -> None:
    bench = app.state.workbench
    provider = bench.gateway.provider
    provider.queue.extend(_design_queue() + _plan_queue())
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=True)

    design = await client.post(
        f"/api/discussion-sessions/{session_id}/design", headers={"X-Bot-Id": leader}
    )
    run_id = design.json()["run_id"]
    run = bench.runs[run_id]
    design_gate = run.gates[-1]

    approved = await client.post(
        f"/api/gates/{design_gate['id']}/resolve", json={"decision": "approve", "payload": {}}
    )
    assert approved.status_code == 200, approved.text
    # DESIGN 批准直接接上 Leader 任务拆解（第 6 步），产出 PLAN 关卡。
    assert approved.json()["gate"]["kind"] == "PLAN基线确认"
    assert run.engine.current == "6"
    assert run.artifacts["baseline_DESIGN"] == "1.0"
    assert "DESIGN" in run.approved_baseline_hashes
    assert run.artifacts["plan"]["tasks"]

    run_view = await client.get(f"/api/runs/{run_id}")
    assert run_view.json()["workflow"]["stage"] == "plan_pending"
    assert run_view.json()["workflow"]["design_approved"] is True

    # /plan 幂等：已有计划时直接返回 run_id，不再消耗模型调用。
    calls_before = len(provider.calls)
    first = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )
    second = await client.post(
        f"/api/discussion-sessions/{session_id}/plan", headers={"X-Bot-Id": leader}
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"] == run_id
    assert len(provider.calls) == calls_before

    session_view = await client.get(
        f"/api/discussion-sessions/{session_id}", headers={"X-Bot-Id": leader}
    )
    assert session_view.json()["workflow"]["run_id"] == run_id
    assert session_view.json()["workflow"]["stage"] == "plan_pending"
    listed = await client.get(
        f"/api/projects/{project_id}/discussion-sessions", headers={"X-Bot-Id": leader}
    )
    item = listed.json()["items"][0]
    assert item["workflow"]["design_approved"] is True


@pytest.mark.asyncio
async def test_design_reject_rewrites_and_reopens_gate(app) -> None:
    bench = app.state.workbench
    provider = bench.gateway.provider
    rewritten = copy.deepcopy(DESIGN)
    rewritten["modules"][0]["responsibility"] = "返回空闲座位（含更新时间）"
    provider.queue.extend(
        _design_queue()
        + [rewritten, copy.deepcopy(REVIEW_ARCH), copy.deepcopy(REVIEW_QUALITY)]
    )
    client, project_id, leader = await _project_with_leader(app)
    session_id = await _seed_session(bench, project_id, leader, approved=True)

    design = await client.post(
        f"/api/discussion-sessions/{session_id}/design", headers={"X-Bot-Id": leader}
    )
    run_id = design.json()["run_id"]
    run = bench.runs[run_id]
    old_gate = run.gates[-1]

    rejected = await client.post(
        f"/api/gates/{old_gate['id']}/resolve",
        json={"decision": "reject", "payload": {"reason": "模块职责需补充更新时间"}},
    )
    assert rejected.status_code == 200, rejected.text
    new_gate = rejected.json()["gate"]
    assert new_gate["kind"] == "DESIGN基线确认"
    assert new_gate["id"] != old_gate["id"]
    assert old_gate["status"] == "rejected"
    assert run.artifacts["design"]["modules"][0]["responsibility"] == "返回空闲座位（含更新时间）"
    assert run.engine.current == "5"


def test_projection_designing_for_discussion_run_without_gates() -> None:
    run = RunState(id="R1", project_id="P1", idea="需求")
    run.artifacts["discussion_session_id"] = "S-1"
    run.artifacts["spec"] = copy.deepcopy(SPEC)
    projection = project_workflow_projection(run=run)
    assert projection.stage == "designing"
    assert projection.design_approved is False