from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

FailureKind = Literal["环境故障", "代码缺陷", "任务描述问题", "合并冲突", "依赖失败", "预算耗尽"]

_NOISE = re.compile(
    r"("
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*|"
    r"[\w./\\]+:\d+|"
    r"(?:[A-Za-z]:)?[\\/]?(?:[\w.\-]+[\\/])+[\w.\-]+|"
    r"0x[0-9a-fA-F]+|"
    r"\b\d+ms\b|"
    r"line \d+"
    r")"
)


def classify(result: dict[str, Any]) -> FailureKind:
    if result.get("budget_exceeded"):
        return "预算耗尽"
    if result.get("upstream") in {"needs_human", "failed", "skipped"}:
        return "依赖失败"
    if result.get("merge_conflict"):
        return "合并冲突"
    if result.get("http_status") in {429, 500, 502, 503, 504} or result.get("timeout") or result.get("parse_error"):
        return "环境故障"
    if result.get("same_signature") or result.get("zero_tests") or result.get("all_skipped"):
        return "任务描述问题"
    if result.get("review_task_problem"):
        return "任务描述问题"
    if result.get("exit_code") not in (None, 0) or result.get("review_blocking"):
        return "代码缺陷"
    if result.get("env_error"):
        return "环境故障"
    return "代码缺陷"


def failure_signature(output: str) -> str:
    normalized = _NOISE.sub("<N>", output)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
