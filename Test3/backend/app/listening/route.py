from __future__ import annotations

from typing import Any, Literal

Route = Literal["忽略", "继续观察", "小变更", "大变更", "新想法"]


def route(item: dict[str, Any], scores: dict[str, Any] | None = None) -> Route:
    scores = scores or {}
    if item.get("known") or item.get("category") == "噪声":
        return "忽略"
    if item.get("red_line") or scores.get("red_line"):
        return "小变更" if item.get("category") == "缺陷" else "大变更"
    if item.get("new_direction"):
        return "新想法"
    unique_authors = int(item.get("unique_authors") or item.get("count") or 0)
    value = float(scores.get("价值") or scores.get("value") or 0)
    if unique_authors < 3 and value <= 3 and not item.get("red_line"):
        if item.get("category") not in {"缺陷"}:
            return "继续观察"
    if item.get("category") == "缺陷" or item.get("category") == "体验问题":
        return "小变更"
    if item.get("category") == "新需求" or item.get("conflicts"):
        return "大变更"
    return "继续观察"
