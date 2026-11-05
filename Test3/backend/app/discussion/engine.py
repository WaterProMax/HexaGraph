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
    select_speaker,
    validate_merge,
    validate_round1,
    validate_utterance,
)
from app.ids import IdAllocator
from app.llm.gateway import Gateway
from app.schemas.docs import IdeaCard, Issue, Question, RoundOutput, Utterance

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
    questions: list[Question] = []
    by_role: dict[str, list[Question]] = {}
    for role in DISCUSSION_AGENT_ROLES:
        visible = {"idea_card": idea.model_dump()}
        if reopen:
            visible["review_opinions"] = [op.model_dump() if hasattr(op, "model_dump") else op for op in (review_opinions or [])]
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
            assumption_critical=_assumption_flag(row.issue),
        )
        for row in rows
    ]
    state = DiscussionState(issues=tuple(issues), reopen=reopen, max_utterances=max_utterances)
    utterances: list[Utterance] = []
    invalid = 0
    while not must_finish(state) and not (can_finish(state) and utterances and utterances[-1].role == "主持人" and utterances[-1].position == "小结"):
        if can_finish(state):
            speaker, rule = "主持人", "finish"
        else:
            speaker, rule = select_speaker(state)
        if speaker == "主持人":
            turn = await call_agent(
                "moderator_turn",
                {"idea_card": idea.model_dump(), "issue_list": [i.model_dump() for i in state.issues], "transcript": [u.model_dump() for u in utterances]},
                registry=registry,
                gateway=gateway,
            )
            utterance = Utterance(
                seq=len(utterances) + 1,
                role="主持人",
                targets=getattr(turn, "targets", []) or _default_targets(state),
                position="小结" if getattr(turn, "announce_finish", False) or can_finish(state) else "追问",
                body=getattr(turn, "body", ""),
                reasons="主持推进",
                mention=list(getattr(turn, "mention", []) or []),
            )
        else:
            out = await call_agent(
                speaker,
                {
                    "idea_card": idea.model_dump(),
                    "merge_table": [r.model_dump() for r in rows],
                    "transcript": [u.model_dump() for u in utterances],
                    "issue_list": [i.model_dump() for i in state.issues],
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
        errors = validate_utterance(utterance, state)
        if errors:
            invalid += 1
            # still counts toward the 20-cap
        utterances.append(utterance)
        state = state.with_utterance(utterance)
        if must_finish(state):
            break
        if can_finish(state) and utterance.role == "主持人" and utterance.position == "小结":
            break
        if len(utterances) >= max_utterances:
            break

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


def _default_targets(state: DiscussionState):
    from app.schemas.common import Target

    for issue in state.issues:
        if not issue.deferred:
            return [Target(issue=issue.code)]
    return []


def _assumption_flag(code: str) -> bool | None:
    if code in {"I-03", "I-04"}:
        return True
    if code in {"I-05", "I-06"}:
        return False
    return None
