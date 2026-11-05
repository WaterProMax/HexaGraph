from __future__ import annotations

from typing import Any, Literal

Level = Literal["澄清", "小变更", "大变更"]


def classify_cr(impact: dict[str, Any], kind: str = "") -> Level:
    modules = list(impact.get("modules") or [])
    add_or_remove = bool(impact.get("add_or_remove_feature") or kind == "add_or_remove")
    changes_p0 = bool(impact.get("changes_p0"))
    overturns = bool(impact.get("overturns_issue"))
    if kind == "clarification" or (
        not add_or_remove
        and not changes_p0
        and not overturns
        and not modules
        and kind in {"", "clarify", "澄清"}
    ):
        if kind in {"clarification", "clarify", "澄清"}:
            return "澄清"
    if add_or_remove or changes_p0 or overturns or len(modules) > 2:
        return "大变更"
    if kind == "澄清":
        return "澄清"
    return "小变更"


def evaluation_pass(scores: list[int], *, any_red_line: bool = False, any_blocking: bool = False) -> bool:
    if not scores:
        return False
    if any_blocking:
        return False
    return sum(scores) / len(scores) >= 3.5
