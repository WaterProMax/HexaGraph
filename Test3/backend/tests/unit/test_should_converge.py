from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

from app.discussion import converge
from app.discussion.converge import should_converge
from app.discussion.models import DiscussionBudget, DiscussionRoundState


def _state(
    *,
    counts: list[int],
    current_round: int | None = None,
    dissent: list[str] | None = None,
    max_rounds: int = 3,
    max_tokens: int | None = None,
    max_wallclock_seconds: int | None = None,
    tokens_used: int = 0,
    elapsed_seconds: int = 0,
    all_pass: bool | None = None,
) -> DiscussionRoundState:
    latest = counts[-1] if counts else 0
    return DiscussionRoundState(
        current_round=current_round if current_round is not None else len(counts),
        budget=DiscussionBudget(
            max_rounds=max_rounds,
            max_tokens=max_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
        ),
        tokens_used=tokens_used,
        elapsed_seconds=elapsed_seconds,
        hard_gate_pass_counts=list(counts),
        dissent_items=list(dissent or []),
        all_required_hard_gates_pass=(latest == 3) if all_pass is None else all_pass,
    )


def test_all_hard_gates_pass_submits_human_with_dissent_in_reason() -> None:
    action, reason = should_converge(_state(counts=[3], dissent=["风险X"]))
    assert action == "submit_human"
    assert "风险X" in reason


def test_improving_gate_count_revises() -> None:
    action, _reason = should_converge(
        _state(counts=[1, 2], current_round=2, max_rounds=3, dissent=[])
    )
    assert action == "revise"


def test_two_equal_low_counts_are_no_improvement() -> None:
    action, _reason = should_converge(
        _state(counts=[1, 1], current_round=2, max_rounds=3, dissent=[])
    )
    assert action == "no_improvement"


def test_token_budget_exhaustion_wins_first() -> None:
    action, _reason = should_converge(
        _state(counts=[3], max_tokens=10, tokens_used=10)
    )
    assert action == "budget_exhausted"


def test_wallclock_budget_exhaustion_wins_first() -> None:
    action, _reason = should_converge(
        _state(counts=[3], max_wallclock_seconds=5, elapsed_seconds=5)
    )
    assert action == "budget_exhausted"


def test_round_limit_submits_human_before_no_improvement() -> None:
    action, _reason = should_converge(
        _state(counts=[1], current_round=2, max_rounds=2, dissent=[])
    )
    assert action == "submit_human"


def test_unmet_gates_recorded_in_dissent_submit_human() -> None:
    action, reason = should_converge(
        _state(counts=[2], current_round=1, max_rounds=3, dissent=["已记录风险"])
    )
    assert action == "submit_human"
    assert "已记录风险" in reason


def test_converge_source_and_signature_have_no_forbidden_terms() -> None:
    signature = inspect.signature(should_converge)
    assert list(signature.parameters) == ["state"]
    names = [field.name for field in dataclasses.fields(DiscussionRoundState)]
    forbidden = ("score", "delta", "variance")
    assert not any(term in name.lower() for name in names for term in forbidden)
    source = Path(converge.__file__).read_text(encoding="utf-8")
    assert "score_delta" not in source
    assert "score_spread" not in source
    assert "variance" not in source