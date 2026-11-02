"""编排状态定义（LangGraph State）。

本文件是「状态即唯一真相」的落点：
- 所有节点只声明自己写回的字段，不做跨节点隐式通信；
- `trace` 使用 `operator.add` 归约器，支持多个节点并发/顺序追加而不是相互覆盖；
- 其余字段均为「后写覆盖」，因为每一轮都代表一次完整重算。

字段语义见 docs/contract.md §2。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

Verdict = Literal["pending", "accepted", "rejected"]


class TraceEntry(TypedDict):
    """一条节点执行记录，用于复盘编排路径（审计证据）。"""

    node: str
    summary: str


class OrchestrationState(TypedDict, total=False):
    """六人编排流水线的共享状态。

    `total=False` 是刻意的：入口只注入 requirement，其余字段由各节点逐步填充，
    节点必须容忍字段缺失（LangGraph 不做字段默认值填充）。
    """

    # ---- 输入 ----
    requirement: str

    # ---- 需求官产出 ----
    spec: dict[str, Any]

    # ---- 契约官产出 ----
    contract: dict[str, Any]

    # ---- 契约门禁产出 ----
    gate_feedback: list[str]
    gate_rounds: int

    # ---- 实现官产出 ----
    implementation: dict[str, Any]

    # ---- 验证官产出 ----
    checks: list[dict[str, Any]]

    # ---- 评审官产出 ----
    review_rounds: int
    verdict: Verdict

    # ---- 全局审计 ----
    trace: Annotated[list[TraceEntry], operator.add]


def initial_state(requirement: str) -> OrchestrationState:
    """构造入口状态。

    只注入 requirement 与空 trace；其余字段保持「不存在」，
    以便 dev-doc 中的证据可以证明节点确实在按需写回字段。
    """
    return {"requirement": requirement, "trace": []}
