from __future__ import annotations

import random

from app.discussion.rules import (
    DiscussionState,
    can_finish,
    finalize_issue,
    forced_end_status,
    must_finish,
    rebuttal_check,
    reopen_issue,
    select_speaker,
    validate_merge,
    validate_round1,
    validate_utterance,
)
from app.schemas.common import Claim, Target
from app.schemas.docs import Issue, MergeRow, Question, ReviewOpinion, Utterance
from tests.unit.study_room import EXPECTED_SPEAKERS, EXPECTED_STATUS, MERGE_ROWS, QUESTIONS, issues, utterances


def _state_after(n: int) -> DiscussionState:
    state = DiscussionState(issues=tuple(issues()))
    for u in utterances()[:n]:
        state = state.with_utterance(u)
    return state


def test_select_speaker_matches_study_room_gold_standard() -> None:
    state = DiscussionState(issues=tuple(issues()))
    for idx, (role, rule) in enumerate(EXPECTED_SPEAKERS):
        got_role, got_rule = select_speaker(state)
        assert (got_role, got_rule) == (role, rule), f"after {idx} utterances"
        state = state.with_utterance(utterances()[idx])


def test_can_finish_before_14_and_not_before_13() -> None:
    assert not can_finish(_state_after(12))
    assert can_finish(_state_after(13))


def test_finalize_matches_table_a() -> None:
    state = _state_after(14)
    for issue in state.issues:
        done = finalize_issue(issue, state)
        assert done.status == EXPECTED_STATUS[issue.code], issue.code


def test_validate_round1_ok_and_counterexamples() -> None:
    by_role: dict[str, list[Question]] = {}
    for q in QUESTIONS:
        by_role.setdefault(q.role, []).append(q)
    assert validate_round1(by_role) == []
    assert validate_round1({"产品经理": by_role["产品经理"][:1]})
    assert validate_round1({"产品经理": by_role["产品经理"]}, reopen=True) == []
    bad = [Question(code="Q-99", role="产品经理", category="价值", text="x", reason="")]
    assert validate_round1({"产品经理": bad * 2})


def test_validate_merge_covers_and_truncates() -> None:
    rows, errors = validate_merge(QUESTIONS, MERGE_ROWS)
    assert not any("未覆盖" in e for e in errors)
    extra = [
        MergeRow(issue=f"I-{i:02d}", from_questions=[f"Q-{i:02d}"], proposers=["产品经理"], text="x", category="范围")
        for i in range(1, 10)
    ]
    qs = [Question(code=f"Q-{i:02d}", role="产品经理", category="范围", text="x", reason="y") for i in range(1, 10)]
    rows, errors = validate_merge(qs, extra)
    assert sum(1 for r in rows if not r.deferred) == 8
    assert any(r.deferred and r.defer_reason for r in rows)


def test_validate_utterance_rejects() -> None:
    state = _state_after(2)
    consecutive = Utterance(role="开发", targets=[Target(issue="I-01")], position="补充", body="还是我", reasons="继续")
    assert any("连续" in e for e in validate_utterance(consecutive, state))
    too_many = Utterance(
        role="测试",
        targets=[Target(issue="I-01"), Target(issue="I-02"), Target(issue="I-03"), Target(issue="I-04")],
        position="补充",
        body="四个",
        reasons="太多",
    )
    assert any("3" in e for e in validate_utterance(too_many, state))
    agree = Utterance(role="测试", targets=[Target(issue="I-01")], position="同意", body="同意", reasons="")
    assert any("同意" in e for e in validate_utterance(agree, state))
    user = Utterance(
        role="用户代表",
        targets=[Target(issue="I-01")],
        position="补充",
        body="用户会用",
        reasons="人设",
        claims=[Claim(text="会用", kind="事实")],
    )
    assert any("假设" in e for e in validate_utterance(user, state))


def test_must_finish_at_20() -> None:
    state = DiscussionState(issues=tuple(issues()), max_utterances=20)
    for i in range(20):
        role = "主持人" if i % 5 == 0 else ["产品经理", "用户代表", "付费方代表", "开发", "测试"][i % 5]
        state = state.with_utterance(
            Utterance(seq=i + 1, role=role, targets=[Target(issue="I-01")], position="补充", body=f"u{i}", reasons="x")
        )
    assert must_finish(state)


def test_forced_end_status() -> None:
    issue = issues()[2]  # I-03
    empty = DiscussionState(issues=tuple(issues()))
    assert forced_end_status(issue, empty) == "未讨论"
    state = empty.with_utterance(Utterance(seq=1, role="用户代表", targets=[Target(issue="I-03")], position="补充", body="回应", reasons="x"))
    i03 = next(i for i in state.issues if i.code == "I-03")
    assert forced_end_status(i03, state) == "待定"


def test_withdraw_only_by_proposers() -> None:
    issue = issues()[0]
    state = DiscussionState(issues=(issue,))
    other = Utterance(seq=1, role="产品经理", targets=[Target(issue="I-01")], position="撤回", body="撤回", reasons="不算")
    state = state.with_utterance(other)
    assert finalize_issue(issue, state).status != "撤回"
    proposer = Utterance(seq=2, role="付费方代表", targets=[Target(issue="I-01")], position="撤回", body="我撤回", reasons="不成立")
    state = state.with_utterance(proposer)
    # last speaker 付费方, but we just check withdraw set
    assert finalize_issue(next(i for i in state.issues if i.code == "I-01"), state).status == "撤回"


def test_opponent_keeps_pending() -> None:
    state = _state_after(14)
    i03 = next(i for i in state.issues if i.code == "I-03")
    assert i03.opponents
    assert finalize_issue(i03, state).status == "待定"


def test_rebuttal_two_outcomes() -> None:
    a = Issue(code="I-05", text="登录", proposers=["用户代表"], assumption_critical=False)
    b = Issue(code="I-04", text="群聊", proposers=["产品经理"], assumption_critical=True)
    assert rebuttal_check(a) == "假设（不影响结论）"
    assert rebuttal_check(b) == "待真人验证"


def test_reopen_appends_history() -> None:
    prev = issues()[0].model_copy(update={"status": "采纳"})
    nxt = reopen_issue(prev, ReviewOpinion(text="忽略无障碍", kind="争议类", blocking=True))
    assert nxt.status == "待定"
    assert nxt.history[-1].from_status == "采纳"


def test_select_speaker_property_no_consecutive_and_rule1() -> None:
    rng = random.Random(0)
    for _ in range(40):
        state = DiscussionState(issues=tuple(issues()))
        for n in range(12):
            role, rule = select_speaker(state)
            if n and state.utterances[-1].role != "主持人" and role != "主持人":
                assert role != state.utterances[-1].role
            if _consecutive(state) >= 4:
                assert role == "主持人" and rule == "1"
            body = rng.choice(["观点", "补充理由"])
            mention = [role] if role == "主持人" else []
            # pick a legal speaker utterance
            u = Utterance(seq=n + 1, role=role, targets=[Target(issue="I-01")], position="补充", body=body, reasons="x", mention=mention)
            state = state.with_utterance(u)


def _consecutive(state: DiscussionState) -> int:
    n = 0
    for u in reversed(state.utterances):
        if u.role == "主持人":
            break
        n += 1
    return n
