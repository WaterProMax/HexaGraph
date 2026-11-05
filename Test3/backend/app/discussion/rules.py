"""Deterministic discussion rules from Design.md chapter 4. No I/O, no model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas.common import (
    DISCUSSION_ROLES,
    FIRST_SPEAK_ORDER,
    QUESTION_CATEGORIES,
    Role,
    normalize_role,
)
from app.schemas.docs import Issue, MergeRow, Question, ReviewOpinion, StatusChange, Utterance

CATEGORY_ROLES: dict[str, tuple[Role, ...]] = {
    "价值": ("用户代表",),
    "范围": ("付费方代表", "产品经理"),
    "可行性": ("开发", "付费方代表"),
    "可测性": ("测试",),
    "竞争": ("产品经理", "用户代表"),
    "其他": ("产品经理",),
}

AGREE_ONLY = {"同意", "ok", "okay", "yes", "+1"}


@dataclass(frozen=True)
class DiscussionState:
    utterances: tuple[Utterance, ...] = ()
    issues: tuple[Issue, ...] = ()
    mentions: tuple[Role, ...] = ()
    review_issue_codes: tuple[str, ...] = ()
    reopen: bool = False
    max_utterances: int = 20
    moderator_every: int = 4

    def with_utterance(self, utterance: Utterance) -> "DiscussionState":
        mentions = list(self.mentions)
        if utterance.role in mentions:
            mentions = [m for m in mentions if m != utterance.role]
        for role in utterance.mention:
            if role not in mentions and role != utterance.role:
                mentions.append(role)
        issues = tuple(_apply_utterance(issue, utterance) for issue in self.issues)
        return DiscussionState(
            utterances=self.utterances + (utterance,),
            issues=issues,
            mentions=tuple(mentions),
            review_issue_codes=self.review_issue_codes,
            reopen=self.reopen,
            max_utterances=self.max_utterances,
            moderator_every=self.moderator_every,
        )


def validate_round1(
    questions_by_role: dict[str, list[Question]],
    *,
    reopen: bool = False,
) -> list[str]:
    errors: list[str] = []
    low, high = (1, 2) if reopen else (2, 3)
    for raw_role, questions in questions_by_role.items():
        role = normalize_role(raw_role)
        if role == "主持人":
            errors.append("主持人不参加第一轮提问")
            continue
        if not low <= len(questions) <= high:
            errors.append(f"{role} 问题数 {len(questions)} 不在 {low}-{high}")
        for q in questions:
            if q.role != role:
                errors.append(f"{role} 的问题角色字段是 {q.role}")
            if q.category not in QUESTION_CATEGORIES:
                errors.append(f"{role} 类别非法: {q.category}")
            if not q.text.strip() or not q.reason.strip():
                errors.append(f"{role} 问题字段不齐全")
    return errors


def validate_merge(
    questions: Iterable[Question],
    merge_rows: Iterable[MergeRow],
    *,
    max_round2: int = 8,
) -> tuple[list[MergeRow], list[str]]:
    questions = list(questions)
    rows = [row.model_copy(deep=True) for row in merge_rows]
    errors: list[str] = []
    q_codes = {q.code for q in questions if q.code}
    covered: set[str] = set()
    for row in rows:
        for code in row.from_questions:
            covered.add(code)
    missing = sorted(code for code in q_codes if code not in covered)
    if missing:
        errors.append("未覆盖的问题: " + ",".join(missing))
    active = [row for row in rows if not row.deferred]
    if len(active) > max_round2:
        overflow = active[max_round2:]
        keep = active[:max_round2]
        for row in overflow:
            row.deferred = True
            row.defer_reason = row.defer_reason or "超过第二轮 8 条上限，按重要性截断"
        rows = keep + overflow + [row for row in rows if row.deferred and row not in overflow]
        errors.append(f"合并后 {len(active)} 条，已截断为 {max_round2} 条")
    return rows, errors


def fallback_merge(questions: list[Question]) -> list[MergeRow]:
    rows: list[MergeRow] = []
    for idx, question in enumerate(questions, start=1):
        rows.append(
            MergeRow(
                issue=f"I-{idx:02d}",
                from_questions=[question.code or f"Q-{idx:02d}"],
                proposers=[question.role],
                text=question.text,
                category=question.category,
                deferred=idx > 8,
                defer_reason="主持人合并不合规，程序按每 Q 单独成条兜底" if idx > 8 else None,
            )
        )
    return rows


def select_speaker(state: DiscussionState) -> tuple[Role, str]:
    if not state.utterances:
        return "主持人", "open"
    consecutive = _consecutive_non_moderator(state)
    if consecutive >= state.moderator_every:
        return "主持人", "1"
    pending = [role for role in state.mentions if role != _last_role(state)]
    if pending:
        return pending[0], "2"
    unspoken = [role for role in FIRST_SPEAK_ORDER if _count(state, role) == 0]
    if unspoken:
        return unspoken[0], "3"
    unanswered = _unanswered_issues(state)
    last_codes = _last_issue_codes(state)
    focus = [issue for issue in unanswered if issue.code in last_codes] or unanswered
    if focus:
        role = _most_related(focus[0], state, exclude_proposers=True)
        if role:
            return role, "4"
    waiting_stance = _waiting_stance(state)
    if waiting_stance:
        issue, role = waiting_stance
        if role != _last_role(state):
            return role, "5"
        other = next((p for p in issue.proposers if p != role), None)
        if other:
            return other, "5"
    current = _current_issue(state)
    if current:
        role = _most_related(current, state, exclude_proposers=False)
        if role:
            return role, "6"
    return "主持人", "6"


def validate_utterance(u: Utterance, state: DiscussionState) -> list[str]:
    errors: list[str] = []
    last = _last_role(state)
    if u.role != "主持人" and last == u.role:
        errors.append("同一非主持人角色不能连续发言")
    codes = {issue.code for issue in state.issues}
    if not u.targets:
        errors.append("缺少回应对象")
    if len(u.targets) > 3:
        errors.append("一条发言最多涉及 3 个争议")
    for target in u.targets:
        if target.issue not in codes:
            errors.append(f"回应对象不存在: {target.issue}")
    if not u.body.strip():
        errors.append("缺少观点")
    if not u.reasons.strip() and u.position != "小结":
        errors.append("缺少理由")
    compact = u.body.strip().replace("。", "").replace("！", "").replace("!", "")
    if compact in AGREE_ONLY and not u.reasons.strip():
        errors.append("只说同意且没有新信息，视为无效")
    needs_claim = any(token in u.body for token in ("竞品", "数据", "用户", "市场", "学校"))
    if needs_claim and not u.claims and u.role != "主持人":
        errors.append("涉及事实或假设的说法必须标注")
    if u.role == "用户代表":
        for claim in u.claims:
            if claim.kind != "假设":
                errors.append("用户代表的说法一律标为假设")
    return errors


def can_finish(state: DiscussionState) -> bool:
    if must_finish(state):
        return True
    active = [issue for issue in state.issues if not issue.deferred]
    if not active:
        return False
    if any(not issue.responses for issue in active):
        return False
    spoken = {u.role for u in state.utterances if u.role in DISCUSSION_ROLES}
    if set(DISCUSSION_ROLES) - spoken:
        return False
    if state.reopen:
        linked = {code for code in state.review_issue_codes}
        for issue in active:
            if issue.code in linked and not issue.responses:
                return False
    # Gold standard 11.4 waits until proposers have taken a stance (utterance 13).
    for issue in active:
        if issue.responses and not issue.stances:
            return False
    return True


def must_finish(state: DiscussionState) -> bool:
    return len(state.utterances) >= state.max_utterances


def rebuttal_check(issue: Issue) -> str:
    if issue.assumption_critical is True:
        return "待真人验证"
    if issue.assumption_critical is False:
        return "假设（不影响结论）"
    if issue.basis in {"待真人验证", "假设（不影响结论）", "事实", "共识", "人工裁决"}:
        return issue.basis
    return "共识"


def finalize_issue(issue: Issue, state: DiscussionState) -> Issue:
    current = next((item for item in state.issues if item.code == issue.code), issue)
    forced = must_finish(state) and not can_finish(
        DiscussionState(
            utterances=state.utterances,
            issues=state.issues,
            mentions=state.mentions,
            review_issue_codes=state.review_issue_codes,
            reopen=state.reopen,
            max_utterances=state.max_utterances + 1,
            moderator_every=state.moderator_every,
        )
    )
    if current.deferred or (forced and not current.responses):
        return current.model_copy(update={"status": "未讨论", "basis": current.basis or "共识"})
    withdrawn = _all_proposers_withdrew(current, state)
    if withdrawn:
        return current.model_copy(update={"status": "撤回", "basis": "共识"})
    if current.opponents:
        return current.model_copy(update={"status": "待定", "basis": rebuttal_check(current)})
    proposers_ok = _all_proposers_accepted(current, state)
    basis = rebuttal_check(current)
    if proposers_ok and current.responses and basis != "待真人验证":
        return current.model_copy(update={"status": "采纳", "basis": basis if basis != "共识" else current.basis or "共识"})
    if forced and current.responses and not current.stances:
        return current.model_copy(update={"status": "待定", "basis": basis})
    if not current.responses:
        return current.model_copy(update={"status": "未讨论"})
    return current.model_copy(update={"status": "待定", "basis": basis})


def forced_end_status(issue: Issue, state: DiscussionState) -> str:
    current = next((item for item in state.issues if item.code == issue.code), issue)
    if not current.responses:
        return "未讨论"
    if current.responses and not current.stances:
        return "待定"
    return finalize_issue(current, state).status


def reopen_issue(prev: Issue, review_opinion: ReviewOpinion) -> Issue:
    history = list(prev.history) + [
        StatusChange(from_status=prev.status, to_status="待定", reason=review_opinion.text)
    ]
    return prev.model_copy(
        update={
            "status": "待定",
            "history": history,
            "responses": [],
            "stances": [],
            "supporters": [],
            "opponents": [],
        }
    )


def _apply_utterance(issue: Issue, utterance: Utterance) -> Issue:
    targeted = [t for t in utterance.targets if t.issue == issue.code]
    if not targeted or utterance.seq is None:
        return issue
    responses = list(issue.responses)
    stances = list(issue.stances)
    supporters = list(issue.supporters)
    opponents = list(issue.opponents)
    is_proposer = utterance.role in issue.proposers
    stance_positions = {"接受", "不接受", "撤回", "同意", "反对"}
    if is_proposer and utterance.position in stance_positions:
        if utterance.seq not in stances:
            stances.append(utterance.seq)
        if utterance.position in {"接受", "同意"}:
            if utterance.role not in supporters:
                supporters.append(utterance.role)
            opponents = [r for r in opponents if r != utterance.role]
        elif utterance.position in {"不接受", "反对"}:
            if utterance.role not in opponents:
                opponents.append(utterance.role)
            supporters = [r for r in supporters if r != utterance.role]
    elif is_proposer and utterance.position in {"补充"}:
        # Design 4.4: 提出者自己给出的结论，视为已接受
        if utterance.seq not in stances:
            stances.append(utterance.seq)
        if utterance.role not in supporters:
            supporters.append(utterance.role)
    if not is_proposer:
        if utterance.seq not in responses:
            responses.append(utterance.seq)
        if utterance.position in {"接受", "同意", "补充"} and utterance.role not in supporters:
            supporters.append(utterance.role)
        if utterance.position in {"不接受", "反对"} and utterance.role not in opponents:
            opponents.append(utterance.role)
    return issue.model_copy(
        update={
            "responses": responses,
            "stances": stances,
            "supporters": supporters,
            "opponents": opponents,
        }
    )


def _consecutive_non_moderator(state: DiscussionState) -> int:
    n = 0
    for utterance in reversed(state.utterances):
        if utterance.role == "主持人":
            break
        n += 1
    return n


def _last_role(state: DiscussionState) -> Role | None:
    return state.utterances[-1].role if state.utterances else None


def _count(state: DiscussionState, role: Role) -> int:
    return sum(1 for u in state.utterances if u.role == role)


def _last_issue_codes(state: DiscussionState) -> set[str]:
    if not state.utterances:
        return set()
    return {t.issue for t in state.utterances[-1].targets}


def _unanswered_issues(state: DiscussionState) -> list[Issue]:
    return [issue for issue in state.issues if not issue.deferred and not issue.responses]


def _waiting_stance(state: DiscussionState) -> tuple[Issue, Role] | None:
    for issue in state.issues:
        if issue.deferred or not issue.responses or issue.stances:
            continue
        for role in issue.proposers:
            if role != _last_role(state):
                return issue, role
        return issue, issue.proposers[0]
    return None


def _current_issue(state: DiscussionState) -> Issue | None:
    codes = _last_issue_codes(state)
    for issue in state.issues:
        if issue.code in codes:
            return issue
    for issue in state.issues:
        if not issue.deferred:
            return issue
    return None


def _most_related(issue: Issue, state: DiscussionState, *, exclude_proposers: bool) -> Role | None:
    last = _last_role(state)
    preferred = list(CATEGORY_ROLES.get(issue.category, DISCUSSION_ROLES))
    pool = list(DISCUSSION_ROLES)
    ordered = preferred + [role for role in pool if role not in preferred]
    for role in ordered:
        if role == last:
            continue
        if exclude_proposers and role in issue.proposers:
            continue
        return role
    for role in DISCUSSION_ROLES:
        if role != last:
            return role
    return "主持人"


def _all_proposers_withdrew(issue: Issue, state: DiscussionState) -> bool:
    withdrawn = {
        u.role
        for u in state.utterances
        if u.position == "撤回" and any(t.issue == issue.code for t in u.targets)
    }
    return bool(issue.proposers) and set(issue.proposers) <= withdrawn


def _all_proposers_accepted(issue: Issue, state: DiscussionState) -> bool:
    accepted: set[Role] = set()
    rejected: set[Role] = set()
    for u in state.utterances:
        if u.role not in issue.proposers:
            continue
        if not any(t.issue == issue.code for t in u.targets):
            continue
        if u.position in {"不接受", "反对"}:
            rejected.add(u.role)
            accepted.discard(u.role)
        elif u.position in {"接受", "同意", "补充", "撤回"}:
            accepted.add(u.role)
            rejected.discard(u.role)
    return bool(issue.proposers) and set(issue.proposers) <= accepted and not rejected
