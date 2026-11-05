from __future__ import annotations

from app.docs.checks import check_design, check_task_graph
from app.errors import ValidationFailed
from app.orchestrator.classify import classify
from app.orchestrator.control import require_control
from app.schemas.common import Budget
from app.schemas.docs import (
    AcceptanceCheck,
    DesignDoc,
    Interface,
    Issue,
    Module,
    SpecDoc,
    SpecItem,
    TaskCard,
    TaskGraph,
)


def test_study_room_design_has_no_access_module() -> None:
    spec = SpecDoc(
        features=[
            SpecItem(code="F1", kind="功能", title="查看", scenario="S1", priority="P0", impact="x", acceptance=["a"], sources=["I-02"]),
            SpecItem(code="F2", kind="功能", title="上报", scenario="S1", priority="P0", impact="x", acceptance=["a"], sources=["I-06"]),
            SpecItem(code="F3", kind="功能", title="收藏", scenario="S1", priority="P1", impact="x", acceptance=["a"], sources=["初步做法"]),
        ],
        scenarios=[{"code": "S1"}],
        out_of_scope=[{"title": "门禁数据接入"}],
        chapters=["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
    )
    modules = [
        Module(code="M1", name="查询服务", responsibility="查看剩余座位", sources=["F1"], provides=["C1"]),
        Module(code="M2", name="上报服务", responsibility="上报限频", sources=["F2"], provides=["C2"]),
        Module(code="M3", name="账号", responsibility="查看免登录", sources=["F2", "I-05"]),
        Module(code="M4", name="教室数据", responsibility="座位数与时间", sources=["F1"]),
        Module(code="M5", name="界面", responsibility="小程序", sources=["F1"]),
    ]
    design = DesignDoc(
        chapters=["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
        modules=modules,
        interfaces=[
            Interface(code="C1", provider="M1", consumers=["M5"]),
            Interface(code="C2", provider="M2", consumers=["M5"], errors=["10 分钟内重复上报"]),
        ],
        contingencies=[{"code": "I-03"}],
    )
    issues = [Issue(code="I-03", status="待定", text="上报量", proposers=["开发"])]
    missing = check_design(design, spec, issues)
    assert any("F3" in e for e in missing)
    design.modules.append(Module(code="M6", name="收藏", responsibility="收藏教室", sources=["F3"]))
    assert not any("F3" in e for e in check_design(design, spec, issues))
    assert all("门禁" not in m.name for m in design.modules)


def test_task_graph_stub_before_impl() -> None:
    spec = SpecDoc(features=[SpecItem(code="F1", kind="功能", title="t", scenario="S1", priority="P0", impact="x", acceptance=["a"], sources=["初步做法"])], scenarios=[{"code": "S1"}])
    design = DesignDoc(modules=[Module(code="M1", name="m", responsibility="r", sources=["F1"])], interfaces=[Interface(code="C1", provider="M1", consumers=["M1"]), Interface(code="C2", provider="M1", consumers=["M1"])])

    def card(code, kind, role="coder", depends=None, write=None, sources=None):
        return TaskCard(
            code=code,
            title=code,
            kind=kind,
            module="M1",
            sources=sources or ["F1"],
            description="d",
            write_set=write or [f"src/{code}.py"],
            outputs=[f"src/{code}.py"],
            acceptance=[AcceptanceCheck(cmd=["pytest"], pass_criteria="ok", from_criterion="F1")],
            depends_on=depends or [],
            points=3,
            priority="P0",
            role=role,
            budget=Budget(),
        )

    graph = TaskGraph(
        tasks=[
            card("T-01", "scaffold", write=["src/t01.py"]),
            card("T-02", "stub", depends=["T-01"], write=["src/t02.py"]),
            card("T-03", "test", role="tester", depends=["T-02"], write=["tests/t03.py"]),
            card("T-04", "impl", depends=["T-02", "T-03"], write=["src/t04.py"]),
            card("T-05", "impl", depends=["T-02", "T-03"], write=["src/t05.py"]),
        ]
    )
    errors = check_task_graph(graph, spec, design, 40)
    assert not errors
    t04 = next(t for t in graph.tasks if t.code == "T-04")
    assert "T-02" in t04.depends_on
    assert next(t for t in graph.tasks if t.code == "T-03").role == "tester"


def test_fake_done_rejected() -> None:
    assert classify({"exit_code": 1}) == "代码缺陷"
    assert classify({"denied": True, "exit_code": 1}) == "代码缺陷"


def test_force_pass_requires_reason() -> None:
    try:
        require_control("force-pass", "failed", reason="")
        raise AssertionError("should require reason")
    except ValidationFailed:
        pass
