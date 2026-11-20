from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, model_validator

DiscussionSessionStatus = Literal[
    "draft",
    "grouping",
    "round1_independent",
    "cross_review",
    "round_n_revise",
    "converged_pending_human",
    "approved",
    "rejected",
    "budget_exhausted",
    "terminated",
]


class ReviewBallot(BaseModel):
    reviewer_bot_id: str
    proposal_id: str
    scores: dict[str, int]
    score_justification: dict[str, str]
    hard_gate_results: dict[str, bool]
    dissent_items: list[str]

    @model_validator(mode="after")
    def _check_ballot(self) -> "ReviewBallot":
        if not self.scores:
            raise ValueError("scores must not be empty")
        if set(self.scores) != set(self.score_justification):
            raise ValueError("score_justification keys must match scores")
        required = {"coverage", "conflicts_closed_or_recorded", "evidence_complete"}
        if not required <= set(self.hard_gate_results):
            raise ValueError("hard_gate_results is missing a required gate")
        return self


class DecisionPackage(BaseModel):
    decision_id: str
    session_id: str
    requirement_snapshot_hash: str
    proposal_ids: list[str]
    dissent_items: list[str]
    hard_gate_summary: dict[str, bool]
    body_md: str
    sha256: str


class DiscussionBudget(BaseModel):
    max_rounds: int = 3
    max_tokens: int | None = None
    max_wallclock_seconds: int | None = None
    # ``None`` keeps the pre-threshold behaviour (hard gates only). New sessions
    # get the 10% default written by the create route.
    score_gap_threshold: float | None = None


class DiscussionSession(BaseModel):
    session_id: str
    project_id: str
    leader_bot_id: str
    participant_bot_ids: list[str]
    status: DiscussionSessionStatus
    current_round: int
    budget: DiscussionBudget
    requirement_snapshot_hash: str
    decision_package: DecisionPackage | None = None
    requirement_text: str = ""
    previous_session_id: str | None = None
    resolution_comment: str | None = None
    paused: bool = False
    created_at: str = ""


@dataclass
class DiscussionRoundState:
    current_round: int
    budget: DiscussionBudget
    tokens_used: int
    elapsed_seconds: int
    hard_gate_pass_counts: list[int]
    dissent_items: list[str]
    all_required_hard_gates_pass: bool
    score_spread: float | None = None


__all__ = [
    "DecisionPackage",
    "DiscussionBudget",
    "DiscussionRoundState",
    "DiscussionSession",
    "DiscussionSessionStatus",
    "ReviewBallot",
]