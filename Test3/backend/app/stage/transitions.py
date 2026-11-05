from __future__ import annotations

from typing import Any

from app.errors import IllegalTransition

# Architecture.md 6.1 — data table, not scattered ifs.
# (current, event) -> next. Extra conditions live in ctx.
STAGE_TABLE: dict[tuple[str, str], str] = {
    ("0", "idea_confirmed"): "1",
    ("0", "idea_unclear"): "0",
    ("1", "discussion_viewed"): "2",
    ("2", "proposal_checked"): "3",
    ("3", "review_confirmed"): "4",
    ("3", "review_to_discussion"): "1",
    ("3", "review_to_proposal"): "2",
    ("3", "review_accept_risk"): "4",
    ("3", "review_stop"): "stopped",
    ("4", "spec_confirmed"): "5",
    ("5", "design_confirmed"): "6",
    ("6", "plan_confirmed"): "7",
    ("7", "tasks_complete"): "8",
    ("8", "acceptance_confirmed"): "done",
    ("8", "acceptance_fix"): "7",
}


def next_stage(current: str, event: str, ctx: dict[str, Any] | None = None) -> str:
    ctx = ctx or {}
    key = (str(current), event)
    if key not in STAGE_TABLE:
        raise IllegalTransition(f"illegal stage transition: {current} + {event}")
    nxt = STAGE_TABLE[key]
    if event == "idea_unclear" and int(ctx.get("supplements", 0)) >= int(ctx.get("max_supplements", 3)):
        return "paused"
    if event in {"review_to_discussion", "review_to_proposal"}:
        returns = int(ctx.get("returns", 0))
        max_returns = int(ctx.get("max_returns", 2))
        if returns >= max_returns:
            return "stopped"
    if event == "acceptance_fix" and int(ctx.get("fix_cycles", 0)) >= int(ctx.get("max_fix_cycles", 2)):
        return "stopped"
    return nxt
