"""社团报名：管理员审核 → 自动通过 的变更对比（scripted，不打真实模型）。

比较业务内容、来源与依赖，不以任务数量作为唯一依据。
"""

from __future__ import annotations

import copy

import pytest

from app.schemas.design_input import DesignSource
from tests.e2e.test_must_fixes import _bench

SCENARIOS = [{"code": "S1", "title": "学生报名活动"}, {"code": "S2", "title": "负责人管理报名"}]

FEATURES_COMMON = [
    {
        "code": "F1",
        "kind": "功能",
        "title": "活动发布",
        "story": "负责人发布活动",
        "scenario": "S2",
        "priority": "P0",
        "impact": "可创建活动",
        "acceptance": ["缺少标题返回 400"],
        "manual": [False],
        "sources": ["§3 F1"],
        "out_of_scope": False,
    },
    {
        "code": "F2",
        "kind": "功能",
        "title": "活动列表",
        "story": "学生浏览活动",
        "scenario": "S1",
        "priority": "P0",
        "impact": "可发现活动",
        "acceptance": ["列表显示剩余名额"],
        "manual": [False],
        "sources": ["§3 F2"],
        "out_of_scope": False,
    },
    {
        "code": "F3",
        "kind": "功能",
        "title": "提交报名",
        "story": "学生提交报名",
        "scenario": "S1",
        "priority": "P0",
        "impact": "可报名",
        "acceptance": ["满员返回 409"],
        "manual": [False],
        "sources": ["§3 F3"],
        "out_of_scope": False,
    },
]

FEATURE_REVIEW = {
    "code": "F4",
    "kind": "功能",
    "title": "报名审核",
    "story": "负责人逐条通过或拒绝报名",
    "scenario": "S2",
    "priority": "P0",
    "impact": "人工控制名额质量",
    "acceptance": ["只有负责人可审核", "审核结果即时反映到学生端"],
    "manual": [True],
    "sources": ["§3 F4 管理员审核"],
    "out_of_scope": False,
}

FEATURE_AUTO = {
    "code": "F4",
    "kind": "功能",
    "title": "报名自动通过",
    "story": "满足名额与截止条件后系统自动通过报名",
    "scenario": "S1",
    "priority": "P0",
    "impact": "无需人工审核即可完成报名",
    "acceptance": ["提交成功后状态为已通过", "不再提供人工审核入口"],
    "manual": [False],
    "sources": ["§3 F4 满足条件后自动通过"],
    "out_of_scope": False,
}

FEATURE_EXPORT = {
    "code": "F5",
    "kind": "功能",
    "title": "名单导出",
    "story": "导出通过名单",
    "scenario": "S2",
    "priority": "P1",
    "impact": "可导出名单",
    "acceptance": ["只含通过状态"],
    "manual": [False],
    "sources": ["§3 F5"],
    "out_of_scope": False,
}


def _spec(features: list[dict]) -> dict:
    return {
        "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
        "users": [{"name": "学生"}, {"name": "社团负责人"}],
        "scenarios": copy.deepcopy(SCENARIOS),
        "features": copy.deepcopy(features),
        "out_of_scope": [{"code": "N1", "title": "候补队列"}],
        "nonfunc": [
            {
                "code": "NF1",
                "kind": "非功能",
                "title": "名额不超卖",
                "story": "",
                "scenario": "S1",
                "priority": "P0",
                "impact": "并发安全",
                "acceptance": ["100 并发不超卖"],
                "manual": [False],
                "sources": ["§4"],
                "out_of_scope": False,
            }
        ],
        "open_questions": [],
        "review_followup": [],
    }


DESIGN_REVIEW = {
    "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
    "modules": [
        {"code": "M1", "name": "活动目录", "responsibility": "活动 CRUD", "sources": ["F1", "F2"], "provides": ["C1"], "depends_on": [], "data": ["Activity"]},
        {"code": "M2", "name": "报名服务", "responsibility": "提交报名", "sources": ["F3"], "provides": ["C3"], "depends_on": ["M1"], "data": ["Registration"]},
        {"code": "M3", "name": "审核与导出", "responsibility": "人工审核与导出", "sources": ["F4", "F5"], "provides": ["C4", "C5"], "depends_on": ["M2"], "data": ["Registration"]},
        {"code": "M4", "name": "管理端", "responsibility": "审核 UI", "sources": ["F4", "F5"], "provides": [], "depends_on": ["M3"], "data": []},
        {"code": "M5", "name": "学生端", "responsibility": "报名 UI", "sources": ["F2", "F3"], "provides": [], "depends_on": ["M1", "M2"], "data": []},
    ],
    "interfaces": [
        {"code": "C1", "provider": "M1", "consumers": ["M5"], "inputs": [], "outputs": [], "errors": []},
        {"code": "C3", "provider": "M2", "consumers": ["M5"], "inputs": [], "outputs": [], "errors": []},
        {"code": "C4", "provider": "M3", "consumers": ["M4"], "inputs": [], "outputs": [], "errors": []},
        {"code": "C5", "provider": "M3", "consumers": ["M4"], "inputs": [], "outputs": [], "errors": []},
    ],
    "data": [],
    "decisions": [{"code": "D1", "decision": "报名需管理员审核", "rationale": "原文要求"}],
    "contingencies": [],
    "appendix": "",
}

DESIGN_AUTO = {
    "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
    "modules": [
        {"code": "M1", "name": "活动目录", "responsibility": "活动 CRUD", "sources": ["F1", "F2"], "provides": ["C1"], "depends_on": [], "data": ["Activity"]},
        {
            "code": "M2",
            "name": "报名服务",
            "responsibility": "提交报名并在满足条件后自动通过",
            "sources": ["F3", "F4"],
            "provides": ["C3"],
            "depends_on": ["M1"],
            "data": ["Registration"],
        },
        {"code": "M3", "name": "名单导出", "responsibility": "导出已通过名单", "sources": ["F5"], "provides": ["C5"], "depends_on": ["M2"], "data": ["Registration"]},
        {"code": "M4", "name": "管理端", "responsibility": "活动发布与导出", "sources": ["F1", "F5"], "provides": [], "depends_on": ["M1", "M3"], "data": []},
        {"code": "M5", "name": "学生端", "responsibility": "报名 UI", "sources": ["F2", "F3", "F4"], "provides": [], "depends_on": ["M1", "M2"], "data": []},
    ],
    "interfaces": [
        {"code": "C1", "provider": "M1", "consumers": ["M5"], "inputs": [], "outputs": [], "errors": []},
        {"code": "C3", "provider": "M2", "consumers": ["M5"], "inputs": [], "outputs": [], "errors": []},
        {"code": "C5", "provider": "M3", "consumers": ["M4"], "inputs": [], "outputs": [], "errors": []},
    ],
    "data": [],
    "decisions": [{"code": "D1", "decision": "满足条件后自动通过，无人工审核", "rationale": "变更后原文"}],
    "contingencies": [],
    "appendix": "",
}


def _task(**kwargs) -> dict:
    base = {
        "kind": "impl",
        "inputs": [],
        "write_set": ["src/app.py"],
        "outputs": ["src/app.py"],
        "acceptance": [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": "F1"}],
        "depends_on": [],
        "points": 2,
        "priority": "P0",
        "role": "coder",
    }
    base.update(kwargs)
    return base


def _ok(from_criterion: str) -> list[dict]:
    return [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": from_criterion}]


PLAN_REVIEW = {
    "tasks": [
        _task(code="T-01", title="实现活动发布与列表", module="M1", sources=["F1", "F2"], description="活动发布与列表 API", write_set=["src/activities.py"], outputs=["src/activities.py"], acceptance=_ok("F1")),
        _task(code="T-02", title="实现提交报名", module="M2", sources=["F3"], description="报名提交与名额校验，状态为待审核", depends_on=["T-01"], write_set=["src/regs.py"], outputs=["src/regs.py"], acceptance=_ok("F3")),
        _task(code="T-03", title="实现管理员审核接口", module="M3", sources=["F4"], description="负责人逐条通过或拒绝报名，写审核状态", depends_on=["T-02"], write_set=["src/review.py"], outputs=["src/review.py"], acceptance=_ok("F4")),
        _task(code="T-04", title="实现名单导出", module="M3", sources=["F5"], description="导出通过审核的名单", depends_on=["T-03"], write_set=["src/export.py"], outputs=["src/export.py"], acceptance=_ok("F5")),
        _task(code="T-05", title="活动发布与列表测试", kind="test", module="M1", sources=["F1", "F2"], description="覆盖发布与列表", depends_on=["T-01"], write_set=["tests/test_activities.py"], outputs=["tests/test_activities.py"], points=1, acceptance=_ok("F1")),
        _task(code="T-06", title="报名与审核测试", kind="test", module="M2", sources=["F3", "F4"], description="覆盖待审核状态与人工审核流转", depends_on=["T-02", "T-03"], write_set=["tests/test_review.py"], outputs=["tests/test_review.py"], points=1, acceptance=_ok("F4")),
        _task(code="T-07", title="名单导出测试", kind="test", module="M3", sources=["F5"], description="导出只含通过状态", depends_on=["T-04"], write_set=["tests/test_export.py"], outputs=["tests/test_export.py"], points=1, acceptance=_ok("F5")),
    ],
    "notes": "含管理员审核",
    "capacity": 40,
}

PLAN_AUTO = {
    "tasks": [
        _task(code="T-01", title="实现活动发布与列表", module="M1", sources=["F1", "F2"], description="活动发布与列表 API", write_set=["src/activities.py"], outputs=["src/activities.py"], acceptance=_ok("F1")),
        _task(
            code="T-02",
            title="实现报名自动通过",
            module="M2",
            sources=["F3", "F4"],
            description="提交报名后若名额与截止满足则状态直接为已通过，无人工审核",
            depends_on=["T-01"],
            write_set=["src/regs.py"],
            outputs=["src/regs.py"],
            acceptance=_ok("F4"),
        ),
        _task(code="T-03", title="实现名单导出", module="M3", sources=["F5"], description="导出已通过名单 CSV", depends_on=["T-02"], write_set=["src/export.py"], outputs=["src/export.py"], acceptance=_ok("F5")),
        _task(code="T-04", title="学生端自动通过状态", module="M5", sources=["F4"], description="展示自动通过后的已通过状态，无审核入口", depends_on=["T-02"], write_set=["web/status.tsx"], outputs=["web/status.tsx"], acceptance=_ok("F4")),
        _task(code="T-05", title="活动发布与列表测试", kind="test", module="M1", sources=["F1", "F2"], description="覆盖发布与列表", depends_on=["T-01"], write_set=["tests/test_activities.py"], outputs=["tests/test_activities.py"], points=1, acceptance=_ok("F1")),
        _task(
            code="T-06",
            title="自动通过与报名测试",
            kind="test",
            module="M2",
            sources=["F3", "F4"],
            description="断言提交后自动通过，且无人工审核接口",
            depends_on=["T-02"],
            write_set=["tests/test_auto_pass.py"],
            outputs=["tests/test_auto_pass.py"],
            points=1,
            acceptance=_ok("F4"),
        ),
        _task(code="T-07", title="名单导出测试", kind="test", module="M3", sources=["F5"], description="导出只含已通过", depends_on=["T-03"], write_set=["tests/test_export.py"], outputs=["tests/test_export.py"], points=1, acceptance=_ok("F5")),
    ],
    "notes": "自动通过",
    "capacity": 40,
}


def _queue(spec: dict, design: dict, plan: dict) -> list[dict]:
    return [
        {"spec": copy.deepcopy(spec), "missing": [], "notes": "ok"},
        {"design": copy.deepcopy(design), "missing": [], "notes": "ok"},
        copy.deepcopy(plan),
    ]


async def _to_plan(bench, text: str, queue: list[dict]) -> dict:
    project = bench.create_project("club")
    created = await bench.create_design_run(project["id"], text, DesignSource(kind="text", name="club.md"), title="社团报名")
    assert created["status"] == "awaiting_confirmation"
    run = bench.runs[created["run_id"]]
    planned = await bench.resolve_gate(run, created["gate"]["id"], "approve", {})
    assert planned["gate"]["kind"] == "PLAN基线确认"
    await bench.resolve_gate(run, planned["gate"]["id"], "approve", {})
    return run


def _f4_tasks(run) -> list[dict]:
    return [t for t in run.tasks.values() if "F4" in (t["card"].get("sources") or [])]


@pytest.mark.asyncio
async def test_club_signup_rule_change_updates_review_tasks_not_just_count(tmp_path) -> None:
    text_review = "# 社团\nF4 管理员审核：负责人逐条通过或拒绝。"
    text_auto = "# 社团\nF4 满足条件后自动通过：提交成功即为已通过，无人工审核。"

    review_features = FEATURES_COMMON + [FEATURE_REVIEW, FEATURE_EXPORT]
    auto_features = FEATURES_COMMON + [FEATURE_AUTO, FEATURE_EXPORT]

    bench_a, _ = _bench(tmp_path / "a", _queue(_spec(review_features), DESIGN_REVIEW, PLAN_REVIEW))
    run_a = await _to_plan(bench_a, text_review, [])
    f4_a = _f4_tasks(run_a)
    assert f4_a, "审核版应有追溯到 F4 的任务"
    blob_a = " ".join(f"{t['card']['title']} {t['card']['description']}" for t in f4_a)
    assert "审核" in blob_a
    assert any(t["card"]["code"] == "T-03" and "审核" in t["card"]["title"] for t in f4_a)
    assert run_a.tasks["T-04"]["card"]["depends_on"] == ["T-03"]
    decisions_a = [d.get("decision", "") for d in (run_a.artifacts["design"].get("decisions") or [])]
    assert any("审核" in d for d in decisions_a)

    bench_b, _ = _bench(tmp_path / "b", _queue(_spec(auto_features), DESIGN_AUTO, PLAN_AUTO))
    run_b = await _to_plan(bench_b, text_auto, [])
    f4_b = _f4_tasks(run_b)
    assert f4_b, "自动通过版也应有追溯到 F4 的任务"
    blob_b = " ".join(f"{t['card']['title']} {t['card']['description']}" for t in f4_b)
    assert "自动通过" in blob_b
    assert "人工审核" in blob_b or "无人工审核" in blob_b
    assert not any("管理员审核" in t["card"]["title"] for t in f4_b)
    assert not any("审核接口" in t["card"]["title"] for t in run_b.tasks.values())

    # 任务数量可以相同；真正要变的是业务措辞、来源与依赖结构
    assert len(run_a.tasks) == len(run_b.tasks) == 7
    titles_a = {t["card"]["title"] for t in f4_a}
    titles_b = {t["card"]["title"] for t in f4_b}
    assert titles_a != titles_b

    feature_a = next(f for f in run_a.artifacts["spec"]["features"] if f["code"] == "F4")
    feature_b = next(f for f in run_b.artifacts["spec"]["features"] if f["code"] == "F4")
    assert "审核" in feature_a["title"]
    assert "自动通过" in feature_b["title"]
    assert feature_a["sources"] != feature_b["sources"]

    # 自动通过后，报名实现任务应同时覆盖 F3+F4，且导出不再依赖独立审核任务
    t02_b = run_b.tasks["T-02"]["card"]
    assert set(t02_b["sources"]) >= {"F3", "F4"}
    assert t02_b["depends_on"] == ["T-01"]
    assert run_b.tasks["T-03"]["card"]["depends_on"] == ["T-02"]
