from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import ConfigError, IllegalTransition
from app.ids import IdAllocator
from app.orchestrator.states import TASK_STATES, TASK_TRANSITIONS, can_transition, next_task_state
from app.schemas.common import Budget
from app.schemas.docs import Question, TaskCard
from app.settings import load_limits, load_models, load_roles, validate_config
from app.stage.transitions import STAGE_TABLE, next_stage


def test_question_roundtrip() -> None:
    q = Question(code="Q-01", role="产品经理", category="竞争", text="好在哪", reason="群聊")
    assert Question.model_validate_json(q.model_dump_json()) == q


def test_task_card_rejects_bad_points_and_priority() -> None:
    base = dict(
        code="T-01",
        title="x",
        kind="impl",
        module="M1",
        sources=["F1"],
        description="d",
        write_set=["src/a.py"],
        acceptance=[{"cmd": ["pytest"], "pass_criteria": "ok", "from_criterion": "F1"}],
        points=3,
        priority="P0",
        role="coder",
        budget=Budget().model_dump(),
    )
    TaskCard.model_validate(base)
    with pytest.raises(Exception):
        TaskCard.model_validate({**base, "points": 13})
    with pytest.raises(Exception):
        TaskCard.model_validate({**base, "priority": "P9"})


def test_id_allocator_concurrent_unique() -> None:
    alloc = IdAllocator()

    def one(_: int) -> str:
        return alloc.next("Q")

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(one, range(50)))
    assert len(set(codes)) == 50
    alloc.set_at_least("I", 7)
    assert alloc.next("I") == "I-08"


def test_stage_table_positive_and_illegal() -> None:
    for (cur, ev), nxt in STAGE_TABLE.items():
        if ev == "review_to_discussion":
            assert next_stage(cur, ev, {"returns": 0}) == nxt
        else:
            assert next_stage(cur, ev) in {nxt, "paused", "stopped"}
    illegal = [
        ("0", "spec_confirmed"),
        ("1", "idea_confirmed"),
        ("2", "tasks_complete"),
        ("4", "discussion_viewed"),
        ("5", "idea_unclear"),
        ("6", "review_confirmed"),
        ("7", "spec_confirmed"),
        ("8", "idea_confirmed"),
        ("done", "idea_confirmed"),
        ("3", "plan_confirmed"),
    ]
    for cur, ev in illegal:
        with pytest.raises(IllegalTransition):
            next_stage(cur, ev)
    assert next_stage("3", "review_to_discussion", {"returns": 2}) == "stopped"


def test_task_transition_edges_and_rejects() -> None:
    for (state, event), nxt in TASK_TRANSITIONS.items():
        assert can_transition(state, event)
        assert next_task_state(state, event) == nxt
    for state in TASK_STATES:
        for other in TASK_STATES:
            if (state, other) not in TASK_TRANSITIONS and not can_transition(state, other):
                with pytest.raises(IllegalTransition):
                    next_task_state(state, other)


def test_config_validation_errors(tmp_path) -> None:

    models = load_models()
    roles = load_roles()
    broken = roles.model_copy(deep=True)
    broken.roles["产品经理"].slot = "no-such-slot"
    with pytest.raises(ConfigError, match="no-such-slot"):
        validate_config(models, broken)
    broken = roles.model_copy(deep=True)
    broken.roles["产品经理"].prompt = "prompts/missing.md"
    with pytest.raises(ConfigError, match="missing"):
        validate_config(models, broken)
    broken = roles.model_copy(deep=True)
    broken.roles["产品经理"].visible.append("not_a_type")
    with pytest.raises(ConfigError, match="not_a_type"):
        validate_config(models, broken)
    validate_config(load_models(), load_roles())
    limits = load_limits()
    assert limits["orchestrator"]["concurrency"] == 6
    assert limits["orchestrator"]["max_repair_rounds"] == 6
    assert limits["orchestrator"]["tokens_per_point"] == 1_500_000
    assert limits["acceptance"]["p1_pass_ratio"] == 0.9
