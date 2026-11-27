"""Deterministic self-study room responses for the isolated browser demo."""

from __future__ import annotations

import json
from typing import Any

from app.llm.providers import ScriptedProvider

from .discussion_demo_files import TASK_FILES

EXPIRY_RULE = "座位数据超过 30 分钟未更新时标为「已过期」，不计入可用座位。"

LEADER_PROPOSAL = """### 1. 目标用户与痛点
期末周找不到座位的学生，跑楼找空位浪费时间。

### 2. 功能清单
- F-01 查看剩余座位（验收：列表显示座位数与上报时间）
- F-02 上报剩余座位（验收：10 分钟内重复上报被拒绝）

### 3. 验收标准
给定教学楼，当学生打开列表，则按楼层显示剩余座位数。

### 4. 非功能需求
页面首屏 2 秒内可用。

### 5. 本版不做
不做门禁与摄像头接入。

### 6. 风险与待定
上报人数不足时信息稀疏。
"""

MEMBER_PROPOSAL = """### 1. 目标用户与痛点
到场学生想快速知道哪层还有空位。

### 2. 功能清单
- F-01 楼层座位列表（验收：显示座位数和更新时间）
- F-02 手动上报座位（验收：同一账号限频）

### 3. 验收标准
给定一条上报，当其他学生查看，则 5 秒内看到最新座位数。

### 4. 非功能需求
移动端可访问。

### 5. 本版不做
不做预约占座。

### 6. 风险与待定
数据可信度需要运营抽查。
"""

LEADER_SPEC = """## 概述
自习座位查看工具：帮期末周的本科生按楼层查看剩余座位，减少白跑。

## 功能列表
- F-01 查看剩余座位：来源：Leader 方案的 F-01 与成员方案的 F-01。
- F-02 上报剩余座位：来源：成员方案的 F-02，限频沿用 Leader 方案。

## 本版不做
不做门禁接入、不做预约占座。

## 验收标准
给定教学楼，当学生打开列表，则按楼层显示剩余座位数与最后上报时间。

## 非功能需求
移动端首屏 2 秒内可用。

## 还没定的问题
上报人数不足时信息稀疏，先在一栋楼试点。
"""


def _review() -> dict[str, Any]:
    """Four dimensions all 5, three hard gates true, no dissent: spread 0 → submit_human."""
    return {
        "scores": {"value": 5, "feasibility": 5, "testability": 5, "clarity": 5},
        "score_justification": {
            "value": "痛点明确。",
            "feasibility": "只用学生上报，可落地。",
            "testability": "验收标准可判定。",
            "clarity": "六段结构完整。",
        },
        "hard_gate_results": {
            "coverage": True,
            "conflicts_closed_or_recorded": True,
            "evidence_complete": True,
        },
        "dissent_items": [],
    }


def _leader_output(*, revised: bool) -> str:
    verdict = {"ok": True, "reason": "六段齐全，验收可判定。", "dissent_items": []}
    spec = LEADER_SPEC
    if revised:
        spec = spec.replace(
            "## 非功能需求",
            f"给定最后一次上报超过 30 分钟，当学生查询楼层，则显示过期状态并排除该条余位。\n\n"
            f"## 本次修订\n{EXPIRY_RULE}\n\n## 非功能需求",
        )
    return spec + "\n```json\n" + json.dumps(verdict, ensure_ascii=False) + "\n```\n"


class DiscussionDemoProvider(ScriptedProvider):
    def next_item(self, slot: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        operation = kwargs.get("discussion_operation")
        material = "\n".join(
            message["content"] for message in messages
            if message["role"] == "user" and isinstance(message.get("content"), str)
        )
        revised = "座位数据的过期规则" in material or EXPIRY_RULE in material
        if operation == "proposal":
            body = LEADER_PROPOSAL if slot == "flagship" else MEMBER_PROPOSAL
            return body + ("\n" + EXPIRY_RULE if revised else "")
        if operation == "review":
            return _review()
        if operation == "synthesis":
            return _leader_output(revised=revised)
        if operation in {"plan", "plan_rewrite"}:
            result = _plan(revised=revised)
            if "LeaderSpec" in material:
                return {"spec": result["spec"]}
            if "LeaderOutline" in material:
                return {
                    "spec": result["spec"],
                    "design": result["design"],
                    "work_packages": result["plan"]["work_packages"],
                }
            return {"tasks": result["plan"]["tasks"]}
        # 第 5 步设计阶段走通用角色槽位（架构师 + 双评审），与旧想法流同一条管线。
        if not operation and kwargs.get("role") == "architect":
            return _plan(revised=revised)["design"]
        if not operation and kwargs.get("role") in {"review_arch", "review_quality"}:
            arch = kwargs["role"] == "review_arch"
            return {
                "reviewer": "架构" if arch else "质量",
                "dimension": "架构一致性" if arch else "实现质量",
                "score": 5,
                "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}],
            }
        if not operation and kwargs.get("role") in {"coder", "tester", "code_reviewer"}:
            _, marker, payload = material.partition('<资料 name="task_card">\n')
            if marker:
                card = json.loads(payload.split("\n</资料>", 1)[0])
                file = TASK_FILES.get(card.get("code"))
                if file and file[0] in card.get("write_set", []):
                    path, content = file
                    if kwargs["role"] == "code_reviewer":
                        return {"verdict": "pass", "issues": []}
                    if messages[-1]["role"] == "tool":
                        result = json.loads(messages[-1]["content"])
                        return {"done": result.get("ok", False), "summary": f"演示交付物 {path}"}
                    return {"tool_calls": [{"name": "write_file", "arguments": {"path": path, "content": content}}]}
        return super().next_item(slot, messages, **kwargs)


def _plan(*, revised: bool) -> dict[str, Any]:
    inputs = [
        ("F-01", "查看剩余座位", "列表显示座位数与更新时间"),
        ("F-02", "上报剩余座位", "同一账号的上报间隔至少 10 分钟"),
    ]
    features = [
        {
            "code": code, "kind": "功能", "title": title, "scenario": "S1",
            "priority": "P0", "impact": "支持学生查找空位",
            "acceptance": [criterion], "sources": ["已批准的需求规格"],
        }
        for code, title, criterion in inputs
    ]
    if revised:
        features[0]["acceptance"].append(EXPIRY_RULE)
    parents = {1: "W1", 2: "W1", 3: "W2", 4: "W3"}
    tasks = [
        {
            "code": f"T{index}", "title": title, "parent": parents[index], "kind": kind, "module": module,
            "sources": ["F-01", "F-02"], "description": title,
            "write_set": [TASK_FILES[f"T{index}"][0]], "outputs": [TASK_FILES[f"T{index}"][0]],
            "acceptance": [{
                "cmd": ["python", "-m", "pytest"],
                "pass_criteria": "全部通过", "from_criterion": "座位查询及上报",
            }],
            "depends_on": dependencies, "points": 2,
            "priority": "P0", "role": "tester" if kind == "test" else "coder",
        }
        for index, (title, kind, module, dependencies) in enumerate([
            ("实现座位查询和上报", "impl", "M3", []),
            ("验证查询、上报限频和过期状态" if revised else "验证查询与上报限频",
             "test", "M3", ["T1"]),
            ("接通查询和上报接口", "integration", "M2", ["T1"]),
            ("展示楼层余位和上报表单", "impl", "M1", ["T3"]),
        ], start=1)
    ]
    work_packages = [
        {"code": "W1", "title": "座位数据与测试基座", "module": "M3", "summary": "座位数据、限频与过期规则",
         "sources": ["F-01", "F-02"]},
        {"code": "W2", "title": "查询与上报接口", "module": "M2", "summary": "统一查询与上报表单的 API",
         "sources": ["F-01", "F-02"]},
        {"code": "W3", "title": "查询界面与交互", "module": "M1", "summary": "楼层余位展示与上报表单",
         "sources": ["F-01", "F-02"]},
    ]
    return {
        "spec": {"scenarios": [{"code": "S1"}], "features": features},
        "design": {
            "modules": [
                {"code": "M1", "name": "座位查询界面", "responsibility": "展示楼层余位与更新时间，收集座位上报",
                 "sources": ["F-01", "F-02"], "depends_on": ["M2"]},
                {"code": "M2", "name": "查询与上报 API", "responsibility": "校验请求并返回统一响应",
                 "sources": ["F-01", "F-02"], "depends_on": ["M3"], "provides": ["C1"]},
                {"code": "M3", "name": "座位数据服务", "responsibility": "记录座位数与上报时间，执行上报限频",
                 "sources": ["F-01", "F-02"], "provides": ["C2"]},
            ],
            "interfaces": [
                {"code": "C1", "provider": "M2", "consumers": ["M1"]},
                {"code": "C2", "provider": "M3", "consumers": ["M2"]},
            ],
        },
        "plan": {"tasks": tasks, "work_packages": work_packages},
    }


__all__ = ["DiscussionDemoProvider"]
