"""Deterministic ScriptedProvider queue for the discussion Playwright E2E case.

The queue is consumed in driver order: two proposals (one per participant),
then two cross reviews (each bot reviews the other bot only), then one Leader
synthesis.  A project with two active bots therefore spends exactly five calls
per discussion session; the E2E rejects the first spec and runs a second
session, so the queue contains the block twice.

Proposal/review payloads are intentionally interchangeable: the driver drafts
the two proposals concurrently, so FIFO order between the two proposal items is
an implementation detail.  The Leader item must stay last in each block because
the driver only calls it after convergence.
"""

from __future__ import annotations

import json
from typing import Any

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


def _leader_output() -> str:
    verdict = {"ok": True, "reason": "六段齐全，验收可判定。", "dissent_items": []}
    return LEADER_SPEC + "\n```json\n" + json.dumps(verdict, ensure_ascii=False) + "\n```\n"


def scripted_discussion_queue() -> list[Any]:
    """Two identical five-call blocks: first session and the post-rejection session."""
    queue: list[Any] = []
    for _ in range(2):
        queue.extend(
            [LEADER_PROPOSAL, MEMBER_PROPOSAL, _review(), _review(), _leader_output()]
        )
    return queue


__all__ = ["scripted_discussion_queue"]