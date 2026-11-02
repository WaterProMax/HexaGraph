"""命令行入口：一句话需求 -> 完整编排 -> 验收报告。

用法：
    python -m orchestration.cli "做一个订单接口，字段有订单号、金额、状态，支持创建、取消、查询"
    python -m orchestration.cli --mermaid        # 打印图结构（Mermaid）
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .graph import build_graph
from .state import initial_state

DEFAULT_REQUIREMENT = "做一个订单接口，字段有订单号、金额、状态，支持创建、取消、查询，重复提交不能重复创建"


def render_report(state: dict[str, Any]) -> str:
    """把终态渲染成人类可读的验收报告。"""
    lines: list[str] = []
    spec = state.get("spec") or {}
    contract = state.get("contract") or {}
    checks = state.get("checks") or []

    lines.append("=" * 64)
    lines.append("编排结果")
    lines.append("=" * 64)
    lines.append(f"实体        : {spec.get('entity')}")
    lines.append(f"字段        : {', '.join(f for f in (contract.get('fields') or {}))}")
    lines.append(f"契约版本    : v{contract.get('version')}")
    lines.append(f"门禁轮次    : {state.get('gate_rounds')}（上限 3）")
    lines.append(f"评审轮次    : {state.get('review_rounds')}（上限 2）")
    lines.append(f"最终结论    : {state.get('verdict')}")
    lines.append("")
    lines.append("-" * 64)
    lines.append("不变量检查")
    lines.append("-" * 64)
    for check in checks:
        flag = "PASS" if check["passed"] else "FAIL"
        lines.append(f"[{flag}] {check['name']:<26} {check['detail']}")
    lines.append("")
    lines.append("-" * 64)
    lines.append("编排轨迹（State 驱动的节点流转）")
    lines.append("-" * 64)
    for entry in state.get("trace") or []:
        lines.append(f"  {entry['node']:<18} {entry['summary']}")
    lines.append("")
    passed = sum(1 for c in checks if c["passed"])
    lines.append(f"验收：{passed}/{len(checks)} 项不变量通过 · 结论 {state.get('verdict')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HexaGraph 六人编排 demo")
    parser.add_argument("requirement", nargs="?", default=DEFAULT_REQUIREMENT, help="一句话需求")
    parser.add_argument("--mermaid", action="store_true", help="打印图结构并退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出终态")
    args = parser.parse_args(argv)

    app = build_graph()

    if args.mermaid:
        print(app.get_graph().draw_mermaid())
        return 0

    final_state = app.invoke(initial_state(args.requirement), {"configurable": {"thread_id": "demo"}})

    if args.json:
        printable = {k: v for k, v in final_state.items() if k != "implementation"}
        print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
        return 0

    print(render_report(final_state))
    return 0 if final_state.get("verdict") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
