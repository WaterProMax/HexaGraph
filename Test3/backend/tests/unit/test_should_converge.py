from __future__ import annotations

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
    score_spread: float | None = None,
    score_gap_threshold: float | None = None,
) -> DiscussionRoundState:
    latest = counts[-1] if counts else 0
    return DiscussionRoundState(
        current_round=current_round if current_round is not None else len(counts),
        budget=DiscussionBudget(
            max_rounds=max_rounds,
            max_tokens=max_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            score_gap_threshold=score_gap_threshold,
        ),
        tokens_used=tokens_used,
        elapsed_seconds=elapsed_seconds,
        hard_gate_pass_counts=list(counts),
        dissent_items=list(dissent or []),
        all_required_hard_gates_pass=(latest == 3) if all_pass is None else all_pass,
        score_spread=score_spread,
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


def test_none_threshold_unmet_gates_recorded_in_dissent_submit_human() -> None:
    action, reason = should_converge(
        _state(counts=[2], current_round=1, max_rounds=3, dissent=["已记录风险"])
    )
    assert action == "submit_human"
    assert "已记录风险" in reason


def test_threshold_mode_small_spread_with_all_gates_submits_human() -> None:
    action, reason = should_converge(
        _state(
            counts=[3],
            current_round=1,
            max_rounds=3,
            score_spread=1.0,
            score_gap_threshold=2.0,
            dissent=["风险X"],
        )
    )
    assert action == "submit_human"
    assert "score spread 1" in reason
    assert "threshold 2" in reason
    assert "风险X" in reason


def test_threshold_mode_spread_equal_to_threshold_still_converges() -> None:
    action, _reason = should_converge(
        _state(
            counts=[3],
            current_round=1,
            max_rounds=3,
            score_spread=2.0,
            score_gap_threshold=2.0,
        )
    )
    assert action == "submit_human"


def test_threshold_mode_large_spread_revises_despite_gates() -> None:
    action, reason = should_converge(
        _state(
            counts=[3],
            current_round=1,
            max_rounds=3,
            score_spread=5.0,
            score_gap_threshold=2.0,
        )
    )
    assert action == "revise"
    assert "score spread 5" in reason
    assert "threshold 2" in reason


def test_threshold_mode_unmet_gates_revise_instead_of_dissent_override() -> None:
    action, reason = should_converge(
        _state(
            counts=[2],
            current_round=1,
            max_rounds=3,
            dissent=["已记录风险"],
            score_spread=0.5,
            score_gap_threshold=2.0,
        )
    )
    assert action == "revise"
    assert "已记录风险" in reason


def test_threshold_mode_missing_spread_is_not_converged() -> None:
    action, reason = should_converge(
        _state(
            counts=[3],
            current_round=1,
            max_rounds=3,
            score_spread=None,
            score_gap_threshold=2.0,
        )
    )
    assert action == "revise"
    assert "unavailable" in reason


def test_threshold_mode_round_limit_forces_submit_human() -> None:
    action, reason = should_converge(
        _state(
            counts=[2, 3],
            current_round=3,
            max_rounds=3,
            score_spread=7.5,
            score_gap_threshold=2.0,
        )
    )
    assert action == "submit_human"
    assert "round limit" in reason
    assert "score spread 7.5" in reason


def test_threshold_mode_no_improvement_still_applies() -> None:
    action, reason = should_converge(
        _state(
            counts=[1, 1],
            current_round=2,
            max_rounds=3,
            score_spread=1.0,
            score_gap_threshold=2.0,
        )
    )
    assert action == "no_improvement"
    assert "did not improve" in reason


def test_threshold_mode_budget_exhaustion_wins_first() -> None:
    action, _reason = should_converge(
        _state(
            counts=[3],
            current_round=1,
            max_rounds=3,
            max_tokens=10,
            tokens_used=10,
            score_spread=0.0,
            score_gap_threshold=2.0,
        )
    )
    assert action == "budget_exhausted"


def test_threshold_mode_round_limit_beats_no_improvement() -> None:
    action, _reason = should_converge(
        _state(
            counts=[1, 1],
            current_round=3,
            max_rounds=3,
            score_spread=4.0,
            score_gap_threshold=2.0,
        )
    )
    assert action == "submit_human"


def test_converge_source_and_signature_have_no_forbidden_terms() -> None:
    # Scores are now one convergence input (spread vs threshold), not the truth:
    # `should_converge` still takes the assembled round state and nothing else.
    signature = inspect.signature(should_converge)
    assert list(signature.parameters) == ["state"]
    source = Path(converge.__file__).read_text(encoding="utf-8")
    assert "score_delta" not in source
    assert "variance" not in source