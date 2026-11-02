"""编排图的行为测试。

测试原则（对齐 dev-skill「验收可用结果」）：断言的是可观察行为，
不是「函数被调用过」。改动编排逻辑若破坏不变量，这里必须先红。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from orchestration.graph import build_graph, route_after_gate, route_after_review
from orchestration.nodes import contract_gate, verifier
from orchestration.state import initial_state

REQUIREMENT = "做一个订单接口，字段有订单号、金额、状态，支持创建、取消、查询，重复提交不能重复创建"


@pytest.fixture(scope="module")
def final_state():
    app = build_graph()
    return app.invoke(initial_state(REQUIREMENT), {"configurable": {"thread_id": "test"}})


def test_happy_path_accepted(final_state):
    assert final_state["verdict"] == "accepted"


def test_all_invariants_pass(final_state):
    checks = final_state["checks"]
    assert len(checks) == 6
    assert all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]


def test_gate_actually_reworked_once(final_state):
    """首版契约被打回、修复后二轮通过——证明条件边与状态回流真实生效。"""
    nodes = [t["node"] for t in final_state["trace"]]
    assert nodes.count("contract_architect") == 2
    assert nodes.count("contract_gate") == 2
    assert final_state["gate_rounds"] == 2
    assert final_state["contract"]["version"] == 2


def test_trace_order_follows_graph(final_state):
    order = [
        "intake",
        "contract_architect",
        "contract_gate",
        "contract_architect",
        "contract_gate",
        "implementer",
        "verifier",
        "reviewer",
    ]
    assert [t["node"] for t in final_state["trace"]] == order


def test_generated_source_matches_contract(final_state):
    source = final_state["implementation"]["source"]
    assert "class ContractService" in source
    assert "order_no" in source
    assert "updated_at" in source


def test_verifier_rejects_illegal_transition(final_state):
    """直接喂一份缺终态约束的契约，验证官必须报 FAIL（不是静默通过）。"""
    state = {
        "contract": {
            "entity": "order",
            "version": 1,
            "fields": {"order_no": {"type": "str", "required": True}, "amount": {"type": "int", "required": True}},
            "transitions": {"created": ["cancelled"], "cancelled": ["cancelled"]},
            "terminal_states": ["cancelled"],
            "invariants": ["x"],
            "idempotency_key": "order_no",
        },
        "implementation": {"source": ""},
    }
    from orchestration.nodes import _render_source

    state["implementation"]["source"] = _render_source(state["contract"])
    result = verifier(state)
    illegal = [c for c in result["checks"] if c["name"] == "reject_illegal_transition"]
    assert illegal and illegal[0]["passed"] is False


def test_gate_flags_missing_fields():
    state = {
        "contract": {
            "entity": "order",
            "version": 1,
            "fields": {},
            "transitions": {},
            "terminal_states": [],
            "invariants": [],
            "idempotency_key": None,
        }
    }
    result = contract_gate(state)
    assert set(result["gate_feedback"]) == {
        "CHECK_FIELDS",
        "CHECK_AUDIT",
        "CHECK_TERMINAL",
        "CHECK_INVARIANT",
        "CHECK_IDEMPOTENCY",
    }


def test_router_unit_paths():
    assert route_after_gate({"gate_feedback": [], "gate_rounds": 1}) == "pass"
    assert route_after_gate({"gate_feedback": ["CHECK_AUDIT"], "gate_rounds": 1}) == "rework"
    assert route_after_gate({"gate_feedback": ["CHECK_AUDIT"], "gate_rounds": 3}) == "fail"
    assert route_after_review({"verdict": "accepted"}) == "accept"
    assert route_after_review({"verdict": "rejected", "review_rounds": 1}) == "rework"
    assert route_after_review({"verdict": "rejected", "review_rounds": 2}) == "fail"


def test_graph_has_six_business_nodes():
    app = build_graph()
    nodes = set(app.get_graph().nodes)
    assert {
        "intake",
        "contract_architect",
        "contract_gate",
        "implementer",
        "verifier",
        "reviewer",
    } <= nodes


def test_checkpoint_persists_final_state():
    app = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "persist-1"}}
    app.invoke(initial_state(REQUIREMENT), config)
    snapshot = app.get_state(config)
    assert snapshot.values["verdict"] == "accepted"


def test_unknown_requirement_falls_back_to_defaults():
    app = build_graph()
    state = app.invoke(initial_state("随便做个东西"), {"configurable": {"thread_id": "fallback"}})
    assert state["spec"]["entity"] == "resource"
    assert [f["name"] for f in state["spec"]["fields"]] == ["biz_no", "amount"]
    assert state["verdict"] == "accepted"
