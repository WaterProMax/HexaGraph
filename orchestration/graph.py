"""图装配（LangGraph Edge）。

这里只做三件事：注册节点、声明边、给两条回流路径装上条件路由。
路由函数是纯函数 `state -> 分支名`，不产生副作用，便于单测。
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    contract_architect,
    contract_gate,
    implementer,
    intake,
    reviewer,
    verifier,
)
from .state import OrchestrationState

#: 回流上限：门禁最多 3 轮、评审最多 2 轮，避免状态机死循环。
MAX_GATE_ROUNDS = 3
MAX_REVIEW_ROUNDS = 2

GateRoute = Literal["pass", "rework", "fail"]
ReviewRoute = Literal["accept", "rework", "fail"]


def route_after_gate(state: OrchestrationState) -> GateRoute:
    """契约门禁之后怎么走：通过 / 回流契约官 / 终止。"""
    if not (state.get("gate_feedback") or []):
        return "pass"
    if int(state.get("gate_rounds", 0)) < MAX_GATE_ROUNDS:
        return "rework"
    return "fail"


def route_after_review(state: OrchestrationState) -> ReviewRoute:
    """评审之后怎么走：验收 / 回流实现官 / 终止。"""
    if state.get("verdict") == "accepted":
        return "accept"
    if int(state.get("review_rounds", 0)) < MAX_REVIEW_ROUNDS:
        return "rework"
    return "fail"


def build_graph(checkpointer: Any | None = None):
    """装配并编译编排图。

    节点顺序：intake -> contract_architect -> contract_gate
             -> implementer -> verifier -> reviewer
    其中 contract_gate 与 reviewer 各带一条回到上游的条件边。
    """
    graph = StateGraph(OrchestrationState)

    graph.add_node("intake", intake)
    graph.add_node("contract_architect", contract_architect)
    graph.add_node("contract_gate", contract_gate)
    graph.add_node("implementer", implementer)
    graph.add_node("verifier", verifier)
    graph.add_node("reviewer", reviewer)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "contract_architect")
    graph.add_edge("contract_architect", "contract_gate")
    graph.add_conditional_edges(
        "contract_gate",
        route_after_gate,
        {"pass": "implementer", "rework": "contract_architect", "fail": END},
    )
    graph.add_edge("implementer", "verifier")
    graph.add_edge("verifier", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"accept": END, "rework": "implementer", "fail": END},
    )

    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())
