from __future__ import annotations

from app.docs.acceptance import acceptance_pass
from app.docs.checks import (
    check_design,
    check_proposal,
    check_spec,
    check_task_graph,
    critical_path,
    reconcile_estimates,
    review_pass,
    route_design_review,
    route_review,
)
from app.orchestrator.budget import check_budget, tokens_budget
from app.orchestrator.classify import classify, failure_signature
from app.orchestrator.control import control_allowed
from app.orchestrator.scheduler import select_tasks
from app.schemas.common import Budget
from app.schemas.docs import (
    AcceptanceCheck,
    AcceptanceItem,
    AcceptanceReport,
    DesignDoc,
    Interface,
    Issue,
    Module,
    ProposalDoc,
    ProposalFeature,
    ProposalRisk,
    ReviewOpinion,
    ReviewSheet,
    SpecDoc,
    SpecItem,
    TaskCard,
    TaskGraph,
)


def _sheet(score: int, blocking: bool = False, kind: str = "方案类") -> ReviewSheet:
    return ReviewSheet(reviewer="r", dimension="d", score=score, opinions=[ReviewOpinion(text="x", kind=kind, blocking=blocking)])


def test_review_pass_boundaries() -> None:
    assert review_pass([_sheet(4), _sheet(3), _sheet(4), _sheet(3)])  # avg 3.5
    assert not review_pass([_sheet(5), _sheet(5), _sheet(5), _sheet(2)])
    assert not review_pass([_sheet(5), _sheet(5), _sheet(5), _sheet(5, blocking=True)])


def test_route_review_combinations() -> None:
    assert route_review([ReviewOpinion(text="a", kind="争议类")]) == "步骤1"
    assert route_review([ReviewOpinion(text="a", kind="方案类")]) == "步骤2"
    assert route_review([ReviewOpinion(text="a", kind="验证类")]) == "我决定"
    assert route_review([ReviewOpinion(text="a", kind="争议类"), ReviewOpinion(text="b", kind="方案类")]) == "步骤1"
    assert route_review([ReviewOpinion(text="a", kind="方案类")], returns=2) == "停止"


def test_route_design_review() -> None:
    assert route_design_review([ReviewOpinion(text="a", kind="需求类")]) == "变更单"
    assert route_design_review([ReviewOpinion(text="a", kind="设计类")], rewrites=2) == "停止"
    assert route_design_review([ReviewOpinion(text="a", kind="验证类")]) == "探索任务"


def test_proposal_check_counterexamples() -> None:
    issues = [Issue(code="I-03", text="上报量", status="待定", proposers=["开发"])]
    doc = ProposalDoc(elevator="e", chapters=["电梯演讲"], features=[ProposalFeature(name="f"+str(i), sources=["初步做法"]) for i in range(13)], estimate_total=99, capacity=10)
    errors = check_proposal(doc, issues, capacity=10)
    assert any("章节" in e or "缺章节" in e for e in errors)
    assert any("12" in e for e in errors)
    assert any("容量" in e for e in errors)
    assert any("I-03" in e for e in errors)
    bad_src = ProposalDoc(elevator="e", chapters=list(__import__("app.docs.checks", fromlist=["PROPOSAL_CHAPTERS"]).PROPOSAL_CHAPTERS), features=[ProposalFeature(name="x", sources=["I-99"])], risks=[ProposalRisk(code="I-03", verification="v", fallback="f")])
    assert any("来源" in e for e in check_proposal(bad_src, issues, capacity=40))


def test_spec_checks() -> None:
    issues = [
        Issue(code="I-01", text="门禁", status="采纳", destination="本版不做", proposers=["付费方代表"]),
        Issue(code="I-03", text="上报量", status="待定", proposers=["开发"]),
        Issue(code="I-09", text="已撤回内容", status="撤回", proposers=["测试"]),
    ]
    spec = SpecDoc(chapters=["用户与场景"], features=[], scenarios=[])
    errors = check_spec(spec, issues)
    assert errors
    good = SpecDoc(
        chapters=["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
        scenarios=[{"code": "S1"}],
        features=[SpecItem(code="F1", kind="功能", title="查看座位", story="s", scenario="S1", priority="P0", impact="不能用", acceptance=["可见"], sources=["初步做法"])],
        out_of_scope=[{"code": "I-01", "title": "门禁"}],
        open_questions=[{"code": "I-03"}],
        review_followup=[],
    )
    # withdrawn text leaking
    leak = good.model_copy(deep=True)
    leak.features[0].title = "已撤回内容"
    assert any("撤回" in e for e in check_spec(leak, issues))


def test_design_cycle_and_missing_module() -> None:
    spec = SpecDoc(
        chapters=["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
        features=[SpecItem(code="F3", kind="功能", title="收藏", scenario="S1", priority="P1", impact="x", acceptance=["a"], sources=["初步做法"])],
        scenarios=[{"code": "S1"}],
    )
    design = DesignDoc(
        chapters=["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
        modules=[
            Module(code="M1", name="A", responsibility="a", sources=["F1"], depends_on=["M2"]),
            Module(code="M2", name="B", responsibility="b", sources=["F1"], depends_on=["M1"]),
        ],
        interfaces=[Interface(code="C1", provider="M9", consumers=[])],
        contingencies=[],
    )
    errors = check_design(design, spec, [Issue(code="I-03", status="待定", text="x", proposers=["开发"])], max_modules=10)
    assert any("环" in e for e in errors)
    assert any("F3" in e for e in errors)


def _card(code: str, **kwargs) -> TaskCard:
    data = dict(
        code=code,
        title=code,
        kind=kwargs.get("kind", "impl"),
        module="M1",
        sources=kwargs.get("sources", ["F1"]),
        description="d",
        write_set=kwargs.get("write_set", [f"src/{code}.py"]),
        outputs=kwargs.get("outputs", [f"src/{code}.py"]),
        acceptance=[AcceptanceCheck(cmd=["pytest"], pass_criteria="ok", from_criterion="F1")],
        depends_on=kwargs.get("depends_on", []),
        points=kwargs.get("points", 3),
        priority=kwargs.get("priority", "P0"),
        role=kwargs.get("role", "coder"),
        budget=Budget(),
        inputs=kwargs.get("inputs", []),
    )
    return TaskCard.model_validate(data)


def test_task_graph_checks() -> None:
    spec = SpecDoc(features=[SpecItem(code="F1", kind="功能", title="t", scenario="S1", priority="P0", impact="x", acceptance=["a"], sources=["初步做法"])], scenarios=[{"code": "S1"}])
    design = DesignDoc(modules=[Module(code="M1", name="m", responsibility="r", sources=["F1"])], interfaces=[Interface(code="C1", provider="M1", consumers=["M1"])])
    cyclic = TaskGraph(tasks=[_card("T-01", depends_on=["T-02"]), _card("T-02", depends_on=["T-01"], kind="test")])
    assert any("环" in e for e in check_task_graph(cyclic, spec, design, 40))
    hanging = TaskGraph(tasks=[_card("T-01", depends_on=["T-99"], kind="impl"), _card("T-02", kind="test")])
    assert any("悬空" in e for e in check_task_graph(hanging, spec, design, 40))
    overlap = TaskGraph(tasks=[_card("T-01", write_set=["src/a.py"]), _card("T-02", write_set=["src/a.py"], kind="test")])
    assert any("写集" in e for e in check_task_graph(overlap, spec, design, 40))
    no_test = TaskGraph(tasks=[_card("T-01", kind="impl")])
    assert any("测试" in e for e in check_task_graph(no_test, spec, design, 40))
    big = TaskGraph(tasks=[_card("T-01", points=8, kind="impl"), _card("T-02", points=8, kind="test")])
    # 8 is allowed per task; total 16 < 40
    assert not any("点数超过 8" in e for e in check_task_graph(big, spec, design, 40))
    over = TaskGraph(tasks=[_card("T-01", kind="impl"), _card("T-02", kind="test")])
    assert any("容量" in e for e in check_task_graph(over, spec, design, 1))
    bad_src = TaskGraph(tasks=[_card("T-01", sources=["F9"], kind="impl"), _card("T-02", sources=["F1"], kind="test")])
    assert any("来源" in e for e in check_task_graph(bad_src, spec, design, 40))
    bad_in = TaskGraph(tasks=[_card("T-01", inputs=["missing.py"], kind="impl"), _card("T-02", kind="test")])
    assert any("输入" in e for e in check_task_graph(bad_in, spec, design, 40))


def test_reconcile_and_critical_path() -> None:
    assert reconcile_estimates(3, 8)[1] is False  # ranks 2 and 4, gap 2
    assert reconcile_estimates(2, 8)[1] is True  # ranks 1 and 4, gap 3
    val, need, disagreed = reconcile_estimates(2, 8, reestimated=True)
    assert val == 8 and disagreed
    diamond = TaskGraph(
        tasks=[
            _card("T-01", points=2),
            _card("T-02", points=5, depends_on=["T-01"]),
            _card("T-03", points=1, depends_on=["T-01"]),
            _card("T-04", points=2, depends_on=["T-02", "T-03"]),
        ]
    )
    path = critical_path(diamond)
    assert path[0] == "T-01"
    assert "T-02" in path


def test_scheduler_rules() -> None:
    graph = TaskGraph(
        tasks=[
            _card("T-01", points=1, priority="P2"),
            _card("T-02", points=8, priority="P0"),
            _card("T-03", points=2, priority="P0", write_set=["src/x.py"], depends_on=["T-99"]),
        ]
    )
    states = {"T-01": "ready", "T-02": "ready", "T-03": "ready"}
    assert select_tasks(graph, states, run_paused=True) == []
    picked = select_tasks(graph, states, concurrency=1)
    assert picked[0].code == "T-02"
    running = [_card("T-09", write_set=["src/T-01.py"])]
    picked = select_tasks(graph, {"T-01": "ready", "T-02": "pending"}, running=running, concurrency=6)
    assert all(t.code != "T-01" for t in picked)
    assert select_tasks(graph, {"T-01": "ready"}, concurrency=0) == []


def test_classify_and_signature() -> None:
    assert classify({"http_status": 429}) == "环境故障"
    assert classify({"exit_code": 1}) == "代码缺陷"
    assert classify({"zero_tests": True}) == "任务描述问题"
    assert classify({"merge_conflict": True}) == "合并冲突"
    assert classify({"upstream": "failed"}) == "依赖失败"
    assert classify({"budget_exceeded": True}) == "预算耗尽"
    a = failure_signature("FAIL tests/test.py:12 at 2020-01-01T00:00:00 assertion X")
    b = failure_signature("FAIL tests/other.py:99 at 2021-02-02T00:00:00 assertion X")
    assert a == b
    c = failure_signature("FAIL tests/test.py:12 assertion Y")
    assert a != c


def test_acceptance_pass_and_budget() -> None:
    report = AcceptanceReport(features=[AcceptanceItem(code="F1", kind="功能", priority="P0", result="未通过")])
    assert not acceptance_pass(report)
    items = [AcceptanceItem(code=f"F{i}", kind="功能", priority="P1", result="通过" if i < 9 else "未通过") for i in range(10)]
    items[0] = AcceptanceItem(code="F0", kind="功能", priority="P0", result="通过")
    # 8/9 p1 = 88.8% if we exclude P0... wait we have 9 P1? items 0 is P0, 1-9 are 8 pass 1 fail = 8/9
    assert not acceptance_pass(AcceptanceReport(features=items), {"p1_pass_ratio": 0.9})
    ok = [AcceptanceItem(code="F0", kind="功能", priority="P0", result="通过")] + [
        AcceptanceItem(code=f"F{i}", kind="功能", priority="P1", result="通过") for i in range(9)
    ] + [AcceptanceItem(code="F9", kind="功能", priority="P1", result="未通过")]
    # 9/10 = 0.9
    assert acceptance_pass(AcceptanceReport(features=ok), {"p1_pass_ratio": 0.9})
    assert tokens_budget(2) == 3_000_000
    assert check_budget(80, 100)["warn"]
    assert check_budget(100, 100)["exceeded"]


def test_control_table() -> None:
    assert control_allowed("retry", "needs_human")
    assert not control_allowed("retry", "running")
    assert control_allowed("force-pass", "failed")
    assert not control_allowed("force-pass", "running")
    assert control_allowed("patch", "pending")
    assert not control_allowed("patch", "running")
