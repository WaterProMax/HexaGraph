from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import ValidationFailed
from app.fixtures.study_room import EXPECTED_STATUS, IDEA, QUESTIONS, scripted_m1_queue
from app.fixtures.study_room import issues as study_issues
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.orchestrator.control import require_control
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _card(**kwargs) -> TaskCard:
    data = {
        "code": "T-01",
        "title": "t",
        "kind": "impl",
        "module": "M1",
        "sources": ["F1"],
        "description": "d",
        "write_set": ["tests/test_feature.py"],
        "outputs": ["tests/test_feature.py"],
        "acceptance": [AcceptanceCheck(cmd=["python", "-m", "pytest", "tests/test_feature.py", "-q"], pass_criteria="ok", from_criterion="F1")],
        "depends_on": [],
        "points": 2,
        "priority": "P0",
        "role": "coder",
        "budget": Budget(),
    }
    data.update(kwargs)
    return TaskCard.model_validate(data)


def _bench(tmp_path: Path, queue: list | None = None) -> tuple[Workbench, ScriptedProvider]:
    provider = ScriptedProvider(queue or [])
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    return bench, provider


def _ready_run(bench: Workbench, card: TaskCard):
    project = bench.create_project("exec")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    run.artifacts["spec"] = {
        "features": [
            {
                "code": "F1",
                "kind": "功能",
                "title": "t",
                "scenario": "S1",
                "priority": "P0",
                "impact": "x",
                "acceptance": ["a"],
                "manual": [False],
                "sources": ["初步做法"],
            }
        ],
        "nonfunc": [],
        "scenarios": [{"code": "S1"}],
        "chapters": [],
    }
    bench._materialize_tasks(run)
    run.tasks[card.code]["state"] = "ready"
    return run


@pytest.mark.asyncio
async def test_denied_acceptance_cannot_be_done(tmp_path: Path) -> None:
    card = _card(acceptance=[AcceptanceCheck(cmd=["python", "-c", "print(1)"], pass_criteria="ok", from_criterion="F1")])
    bench, provider = _bench(tmp_path, [{"done": True, "summary": "I finished", "files": ["tests/test_feature.py"]}])
    run = _ready_run(bench, card)
    result = await bench.execute_task(run, card.code)
    assert run.tasks[card.code]["state"] != "done"
    assert result.get("state") != "done"
    assert result["kind"] == "任务描述问题"
    assert result.get("gate", {}).get("kind") == "重排提案"


@pytest.mark.asyncio
async def test_repair_round_includes_prev_output(tmp_path: Path) -> None:
    fail_write = {
        "tool_calls": [
            {
                "name": "write_file",
                "arguments": {"path": "tests/test_feature.py", "content": "def test_feature():\n    assert False\n"},
            }
        ]
    }
    ok_write = {
        "tool_calls": [
            {
                "name": "write_file",
                "arguments": {"path": "tests/test_feature.py", "content": "def test_feature():\n    assert True\n"},
            }
        ]
    }
    queue = [
        fail_write,
        {"done": True, "summary": "failing", "files": ["tests/test_feature.py"]},
        {"verdict": "fail", "issues": [{"text": "assert fail", "blocking": True, "kind": "缺陷"}]},
        ok_write,
        {"done": True, "summary": "fixed", "files": ["tests/test_feature.py"]},
        {"verdict": "pass", "issues": []},
    ]
    bench, provider = _bench(tmp_path, queue)
    run = _ready_run(bench, _card())
    result = await bench.execute_task(run, "T-01")
    assert run.tasks["T-01"]["state"] == "done", result
    blobs = [str(c["messages"]) for c in provider.calls]
    assert any("<资料 name=\"prev_output\">" in b or "<资料 name=\"review_issues\">" in b for b in blobs)


@pytest.mark.asyncio
async def test_limits_are_copied_and_deep_merged(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    p = bench.create_project("lim")
    a = bench.create_run(p["id"], "a")
    b = bench.create_run(p["id"], "b")
    bench.patch_limits(a, {"orchestrator": {"concurrency": 2}})
    assert a.limits["orchestrator"]["concurrency"] == 2
    assert a.limits["orchestrator"]["max_repair_rounds"] == 6
    assert b.limits["orchestrator"]["concurrency"] == 6
    with pytest.raises(ValidationFailed):
        bench.patch_limits(a, {"unknown": 1})


@pytest.mark.asyncio
async def test_gate_cannot_resolve_twice(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path, scripted_m1_queue())
    p = bench.create_project("g")
    run = bench.create_run(p["id"], IDEA.raw)
    first = await bench.start_idea(run)
    gate_id = first["gate"]["id"]
    await bench.resolve_gate(run, gate_id, "approve", {})
    with pytest.raises(ValidationFailed):
        await bench.resolve_gate(run, gate_id, "approve", {})


@pytest.mark.asyncio
async def test_accept_runs_tests_and_requires_reason(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    run.tasks["T-01"]["state"] = "done"
    run.tasks["T-01"]["card"]["acceptance"] = [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": "F1"}]
    result = await bench.accept(run)
    assert result["gate"]["kind"] == "验收确认"
    assert result["gate"]["payload"]["pass"] is False
    report = run.artifacts["acceptance"]
    assert report["features"][0]["result"] == "未通过"
    assert report["features"][0]["reason"]
    assert run.crs
    assert run.crs[0]["kind"] == "小变更"
    assert run.crs[0].get("source") == "acceptance" or "验收未通过" in run.crs[0]["description"]
    run.engine.current = "8"
    with pytest.raises(ValidationFailed):
        await bench.resolve_gate(run, result["gate"]["id"], "approve", {})
    done = await bench.resolve_gate(run, result["gate"]["id"], "approve", {"reason": "人工确认剩余项"})
    assert done["status"] == "done"
    assert run.artifacts.get("build_tag") == "build-1.0"
    assert (Path(run.artifacts["release_dir"]) / "acceptance.json").exists()


def _spec_payload(f1_title: str = "按楼层查看剩余座位") -> dict:
    return {
        "users": [{"name": "u"}],
        "scenarios": [{"code": "S1"}],
        "features": [
            {
                "code": "F1",
                "kind": "功能",
                "title": f1_title,
                "scenario": "S1",
                "priority": "P0",
                "impact": "x",
                "acceptance": ["能看到座位数"],
                "manual": [False],
                "sources": ["初步做法"],
            },
            {
                "code": "F2",
                "kind": "功能",
                "title": "untouched",
                "scenario": "S1",
                "priority": "P1",
                "impact": "x",
                "acceptance": ["a"],
                "manual": [False],
                "sources": ["初步做法"],
            },
        ],
        "nonfunc": [],
        "out_of_scope": [],
        "open_questions": [],
        "review_followup": [],
        "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
    }


@pytest.mark.asyncio
async def test_decide_cr_marks_applied_and_bumps_1_1(tmp_path: Path) -> None:
    bench, provider = _bench(
        tmp_path,
        [
            {"dimension": "价值", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "影响", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "风险", "score": 4, "red_line": True, "blocking": False, "reason": "红线"},
            {"dimension": "价值", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "影响", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "风险", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            _spec_payload("改过的查询页"),
            {"dimension": "价值", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "影响", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            {"dimension": "风险", "score": 4, "red_line": False, "blocking": False, "reason": "ok"},
            _spec_payload("第二次变更"),
        ],
    )
    run = _ready_run(bench, _card())
    run.tasks["T-01"]["state"] = "done"
    run.trace.link("F1", "T-01", "spec_item → task")
    run.artifacts["spec"]["features"].append(
        {
            "code": "F2",
            "kind": "功能",
            "title": "untouched",
            "scenario": "S1",
            "priority": "P1",
            "impact": "x",
            "acceptance": ["a"],
            "manual": [False],
            "sources": ["初步做法"],
        }
    )
    f1_before = copy.deepcopy(next(f for f in run.artifacts["spec"]["features"] if f["code"] == "F1"))
    f2_before = copy.deepcopy(next(f for f in run.artifacts["spec"]["features"] if f["code"] == "F2"))
    gate = await bench.submit_cr(run, "改查询页", ["F1"], kind="小变更")
    cr = gate["gate"]["payload"]["cr"]
    assert cr["eval_flags"]["red_line"] is True
    assert cr["kind"] == "小变更"
    rejected = await bench.decide_cr(run, {"code": cr["code"], "decision": "驳回"})
    assert rejected["status"] == "rejected"
    gate = await bench.submit_cr(run, "改查询页", ["F1"], kind="小变更")
    cr = gate["gate"]["payload"]["cr"]
    decided = await bench.decide_cr(run, {"code": cr["code"], "decision": "批准"})
    assert decided["status"] == "applied"
    assert decided["applied_version"] == "1.1"
    assert run.artifacts["baseline_SPEC"] == "1.1"
    assert run.artifacts.get("spec_1.0")
    f1_after = next(f for f in run.artifacts["spec"]["features"] if f["code"] == "F1")
    f2_after = next(f for f in run.artifacts["spec"]["features"] if f["code"] == "F2")
    assert f1_after != f1_before
    assert f1_after["title"] == "改过的查询页"
    assert f2_after == f2_before
    assert run.tasks["T-01"]["state"] == "stale"
    assert any(e["kind"] == "task.state_changed" and e["payload"].get("event") == "change_impact" for e in run.events)

    async def _noop_execute(_run, _code):
        return {"state": _run.tasks[_code]["state"]}

    bench.execute_task = _noop_execute  # type: ignore[method-assign]
    await bench.schedule_once(run)
    assert run.tasks["T-01"]["state"] == "ready"
    gate = await bench.submit_cr(run, "再改一次", ["F1"], kind="小变更")
    cr2 = gate["gate"]["payload"]["cr"]
    second = await bench.decide_cr(run, {"code": cr2["code"], "decision": "批准"})
    assert second["applied_version"] == "1.2"
    assert run.artifacts["baseline_SPEC"] == "1.2"


@pytest.mark.asyncio
async def test_review_reopen_then_pass(tmp_path: Path) -> None:
    reopen_q = []
    for role in ("产品经理", "用户代表", "付费方代表", "开发", "测试"):
        q = next(q for q in QUESTIONS if q.role == role)
        reopen_q.append({"questions": [q.model_dump()], "persona": ""})
    reopen_q.append(
        {
            "rows": [
                {
                    "issue": "I-03",
                    "from_questions": ["Q-01", "Q-02", "Q-03", "Q-04", "Q-05"],
                    "proposers": ["开发"],
                    "text": "上报的人够不够",
                    "category": "可行性",
                }
            ],
            "notes": "",
        }
    )
    from app.schemas.common import Claim, Target
    from app.schemas.docs import Utterance

    utters = [
        Utterance(seq=1, role="主持人", targets=[Target(issue="I-03", to_role="开发")], position="追问", body="请开发先回应重开的 I-03。", reasons="开场", mention=["开发"]),
        Utterance(seq=2, role="开发", targets=[Target(issue="I-03")], position="不接受", body="上报量仍需试点，不能当已解决。", reasons="未知"),
        Utterance(seq=3, role="产品经理", targets=[Target(issue="I-03")], position="补充", body="继续单栋试点，两周看上报条数。", reasons="集中上报", claims=[Claim(text="单栋能凑够上报", kind="假设")]),
        Utterance(seq=4, role="用户代表", targets=[Target(issue="I-03")], position="接受", body="信息太灰我就不再打开。", reasons="人设", claims=[Claim(text="稀疏导致流失", kind="假设")]),
        Utterance(seq=5, role="付费方代表", targets=[Target(issue="I-03")], position="同意", body="可以配合张贴试点说明。", reasons="后勤可配合"),
        Utterance(seq=6, role="测试", targets=[Target(issue="I-03")], position="补充", body="试点期间统计每日上报条数即可验收。", reasons="可测"),
        Utterance(seq=7, role="主持人", targets=[Target(issue="I-03")], position="小结", body="重开讨论结束。", reasons="正常结束"),
    ]
    for u in utters:
        if u.role == "主持人":
            reopen_q.append({"body": u.body, "mention": u.mention, "announce_finish": u.position == "小结"})
        else:
            reopen_q.append({"questions": [], "utterance": u.model_dump()})
    reopen_q.append({"issues": [{"code": "I-03", "text": "上报的人够不够", "proposers": ["开发"], "category": "可行性"}], "notes": "重开结束"})
    tail = scripted_m1_queue()
    # reuse proposal/review/spec items from the original queue tail
    start = next(i for i, item in enumerate(tail) if isinstance(item, dict) and "elevator" in item)
    bench, provider = _bench(tmp_path, reopen_q)
    project = bench.create_project("reopen")
    run = bench.create_run(project["id"], IDEA.raw)
    run.artifacts["idea_card"] = IDEA.model_dump()
    run.artifacts["issues"] = [
        {"code": "I-03", "text": "上报的人够不够", "status": "待定", "proposers": ["开发"], "category": "可行性"}
    ]
    run.artifacts["review_pass"] = False
    run.artifacts["reviews"] = [
        {
            "reviewer": "用户价值",
            "dimension": "用户价值",
            "score": 2,
            "opinions": [{"text": "退回 I-03 上报量争议", "kind": "争议类", "blocking": True, "code": "R-09"}],
        }
    ]
    run.engine.current = "3"
    run.ids.set_at_least("I", 3)
    r3 = await bench.after_review_gate(run, "reject", {"route": "步骤1"})
    assert r3["gate"]["kind"] == "争议清单查看与裁决"
    assert r3["gate"]["payload"]["reopen"] is True
    codes = {i["code"] for i in run.artifacts["issues"]}
    assert "I-03" in codes
    assert any((i.get("history") or []) for i in run.artifacts["issues"] if i["code"] == "I-03")
    restored = []
    for issue in study_issues():
        restored.append(issue.model_copy(update={"status": EXPECTED_STATUS[issue.code]}).model_dump())
    run.artifacts["issues"] = restored
    provider.queue = list(tail[start:])
    r4 = await bench.resolve_gate(run, r3["gate"]["id"], "approve", {})
    assert r4.get("gate", {}).get("kind") == "评审确认", r4
    r5 = await bench.resolve_gate(run, r4["gate"]["id"], "approve", {})
    assert r5["gate"]["kind"] == "SPEC基线确认"


def test_control_actions_require_reason_by_state() -> None:
    for state in ("pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"):
        require_control("pause", state, reason="")
        require_control("resume", state, reason="")
    with pytest.raises(ValidationFailed):
        require_control("skip", "ready", reason="")
    require_control("skip", "ready", reason="下游继续")
    with pytest.raises(ValidationFailed):
        require_control("force-pass", "failed", reason="")
