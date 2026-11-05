from __future__ import annotations

from typing import Any

from app.agents.runtime import RoleRegistry, call_agent
from app.discussion.rules import (
    DiscussionState,
    can_finish,
    fallback_merge,
    finalize_issue,
    forced_end_status,
    must_finish,
    reopen_issue,
    select_speaker,
    validate_merge,
    validate_round1,
    validate_utterance,
)
from app.ids import IdAllocator
from app.llm.gateway import Gateway
from app.schemas.docs import IdeaCard, Issue, Question, ReviewOpinion, RoundOutput, Utterance

DISCUSSION_AGENT_ROLES = ("产品经理", "用户代表", "付费方代表", "开发", "测试")


async def run_discussion(
    idea: IdeaCard,
    *,
    registry: RoleRegistry,
    gateway: Gateway,
    ids: IdAllocator,
    reopen: bool = False,
    review_opinions: list[Any] | None = None,
    prev_issues: list[Issue] | None = None,
    max_utterances: int = 20,
) -> dict[str, Any]:
    opinions = _as_opinions(review_opinions)
    questions: list[Question] = []
    by_role: dict[str, list[Question]] = {}
    for role in DISCUSSION_AGENT_ROLES:
        visible: dict[str, Any] = {"idea_card": idea.model_dump()}
        if reopen:
            visible["review_opinions"] = [op.model_dump() for op in opinions]
        output = await call_agent(role, visible, registry=registry, gateway=gateway)
        assert isinstance(output, RoundOutput)
        role_qs = []
        for q in output.questions:
            q.code = ids.next("Q")
            q.role = role  # type: ignore[assignment]
            role_qs.append(q)
            questions.append(q)
        by_role[role] = role_qs
        errors = validate_round1({role: role_qs}, reopen=reopen)
        if errors:
            output = await call_agent(role, {**visible, "rewrite": errors}, registry=registry, gateway=gateway)
            assert isinstance(output, RoundOutput)
            role_qs = []
            for q in output.questions:
                q.code = q.code or ids.next("Q")
                q.role = role  # type: ignore[assignment]
                role_qs.append(q)
            by_role[role] = role_qs
            questions = [q for q in questions if q.role != role] + role_qs

    merge_out = await call_agent(
        "moderator_merge",
        {"idea_card": idea.model_dump(), "questions": [q.model_dump() for q in questions]},
        registry=registry,
        gateway=gateway,
    )
    rows = getattr(merge_out, "rows", None) or []
    rows, merge_errors = validate_merge(questions, rows)
    merge_fallback = False
    if merge_errors and any("未覆盖" in e for e in merge_errors):
        merge_out = await call_agent(
            "moderator_merge",
            {"idea_card": idea.model_dump(), "questions": [q.model_dump() for q in questions], "rewrite": merge_errors},
            registry=registry,
            gateway=gateway,
        )
        rows = getattr(merge_out, "rows", None) or []
        rows, merge_errors = validate_merge(questions, rows)
        if merge_errors and any("未覆盖" in e for e in merge_errors):
            rows = fallback_merge(questions)
            merge_fallback = True
    for row in rows:
        if not row.issue or not row.issue.startswith("I-"):
            row.issue = ids.next("I")
        else:
            _, n = IdAllocator.parse(row.issue)
            ids.set_at_least("I", n)

    issues = [
        Issue(
            code=row.issue,
            sources=row.from_questions,
            proposers=row.proposers,
            category=row.category if row.category in {"价值", "范围", "可行性", "可测性", "竞争", "其他"} else "其他",
            text=row.text,
            deferred=row.deferred,
        )
        for row in rows
    ]
    if reopen and prev_issues:
        issues = _merge_reopened(prev_issues, opinions, issues)

    review_codes = tuple({issue.code for issue in issues if any(issue.code in (op.text + (op.code or "")) for op in opinions)})
    state = DiscussionState(
        issues=tuple(issues),
        reopen=reopen,
        max_utterances=max_utterances,
        review_issue_codes=review_codes,
    )
    utterances: list[Utterance] = []
    invalid = 0
    while not must_finish(state):
        if can_finish(state):
            break
        speaker, rule = select_speaker(state)
        utterance = await _speak(speaker, rule, idea, state, rows, utterances, registry, gateway)
        errors = validate_utterance(utterance, state)
        if errors:
            rewritten = await _speak(
                speaker,
                rule,
                idea,
                state,
                rows,
                utterances,
                registry,
                gateway,
                rewrite=errors,
            )
            rewritten.seq = utterance.seq
            rewrite_errors = validate_utterance(rewritten, state)
            if rewrite_errors:
                invalid += 1
                utterances.append(rewritten)
                state = state.with_utterance(rewritten)
                ask = Utterance(
                    seq=len(utterances) + 1,
                    role="主持人",
                    targets=rewritten.targets or _default_targets(state),
                    position="追问",
                    body="上一条发言不合规，请该角色用完整观点和理由重述。",
                    reasons="无效发言追问",
                    mention=[speaker] if speaker != "主持人" else [],
                    rule="1",
                )
                utterances.append(ask)
                state = state.with_utterance(ask)
                continue
            utterance = rewritten
        utterances.append(utterance)
        state = state.with_utterance(utterance)
        if must_finish(state):
            break
        if len(utterances) >= max_utterances:
            break

    if can_finish(state) or utterances:
        try:
            await call_agent(
                "moderator_final",
                {
                    "issue_list": [i.model_dump() for i in state.issues],
                    "transcript": [u.model_dump() for u in utterances],
                },
                registry=registry,
                gateway=gateway,
            )
        except Exception:
            pass

    final_issues = []
    overrides = []
    for issue in state.issues:
        done = finalize_issue(issue, state)
        if must_finish(state) and not issue.responses:
            done = issue.model_copy(update={"status": forced_end_status(issue, state)})
        if done.status != issue.status:
            overrides.append({"code": issue.code, "from": issue.status, "to": done.status})
        final_issues.append(done)
    return {
        "questions": questions,
        "merge_rows": rows,
        "utterances": utterances,
        "issues": final_issues,
        "merge_fallback": merge_fallback,
        "status_overrides": overrides,
        "invalid_utterances": invalid,
        "state": state,
    }


async def _speak(
    speaker: str,
    rule: str,
    idea: IdeaCard,
    state: DiscussionState,
    rows: list[Any],
    utterances: list[Utterance],
    registry: RoleRegistry,
    gateway: Gateway,
    rewrite: list[str] | None = None,
) -> Utterance:
    extra = {"rewrite": rewrite} if rewrite else {}
    if speaker == "主持人":
        turn = await call_agent(
            "moderator_turn",
            {
                "idea_card": idea.model_dump(),
                "issue_list": [i.model_dump() for i in state.issues],
                "transcript": [u.model_dump() for u in utterances],
                **extra,
            },
            registry=registry,
            gateway=gateway,
        )
        return Utterance(
            seq=len(utterances) + 1,
            role="主持人",
            targets=getattr(turn, "targets", []) or _default_targets(state),
            position="小结" if getattr(turn, "announce_finish", False) or can_finish(state) else "追问",
            body=getattr(turn, "body", ""),
            reasons="主持推进",
            mention=list(getattr(turn, "mention", []) or []),
            rule=rule,
        )
    out = await call_agent(
        speaker,
        {
            "idea_card": idea.model_dump(),
            "merge_table": [r.model_dump() for r in rows],
            "transcript": [u.model_dump() for u in utterances],
            "issue_list": [i.model_dump() for i in state.issues],
            **extra,
        },
        registry=registry,
        gateway=gateway,
    )
    utterance = out.utterance if isinstance(out, RoundOutput) and out.utterance else Utterance(
        role=speaker,  # type: ignore[arg-type]
        body=str(out),
        reasons="scripted",
        targets=_default_targets(state),
    )
    utterance.role = speaker  # type: ignore[assignment]
    utterance.seq = len(utterances) + 1
    utterance.rule = rule
    return utterance


def _as_opinions(raw: list[Any] | None) -> list[ReviewOpinion]:
    items: list[ReviewOpinion] = []
    for item in raw or []:
        if isinstance(item, ReviewOpinion):
            items.append(item)
        elif isinstance(item, dict):
            items.append(ReviewOpinion.model_validate(item))
    return items


def _merge_reopened(prev_issues: list[Issue], opinions: list[ReviewOpinion], fresh: list[Issue]) -> list[Issue]:
    hits: list[Issue] = []
    for prev in prev_issues:
        op = next((o for o in opinions if prev.code in ((o.text or "") + (o.code or ""))), None)
        if op:
            hits.append(reopen_issue(prev, op))
    if not hits and opinions:
        hits = [reopen_issue(prev, opinions[0]) for prev in prev_issues if prev.status == "待定"]
    taken = {i.code for i in hits}
    kept = hits + [i for i in fresh if i.code not in taken]
    return kept or list(fresh)


def _default_targets(state: DiscussionState):
    from app.schemas.common import Target

    for issue in state.issues:
        if not issue.deferred:
            return [Target(issue=issue.code)]
    return []
