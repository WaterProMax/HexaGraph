from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.stage.transitions import next_stage


@dataclass
class StageOutcome:
    status: Literal["passed", "failed", "need_human", "stopped"]
    artifacts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    gate: dict[str, Any] | None = None


@dataclass
class StageContext:
    run_id: str
    data: dict[str, Any]
    services: dict[str, Any]


class StageEngine:
    def __init__(self) -> None:
        self.current = "0"
        self.returns = 0
        self.supplements = 0
        self.fix_cycles = 0
        self.history: list[dict[str, str]] = []

    def apply(self, event: str, ctx: dict[str, Any] | None = None) -> str:
        nxt = next_stage(
            self.current,
            event,
            {
                "returns": self.returns,
                "supplements": self.supplements,
                "fix_cycles": self.fix_cycles,
                **(ctx or {}),
            },
        )
        self.history.append({"from": self.current, "event": event, "to": nxt})
        if event in {"review_to_discussion", "review_to_proposal"} and nxt not in {"stopped", "paused"}:
            self.returns += 1
        if event == "idea_unclear":
            self.supplements += 1
        if event == "acceptance_fix":
            self.fix_cycles += 1
        self.current = nxt
        return nxt
