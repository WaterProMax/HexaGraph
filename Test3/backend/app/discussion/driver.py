"""Background driver for a P4 multi-bot discussion session.

A discussion session has no run, so ``call_agent`` (which requires a frozen run
pin) cannot be used.  Every model call follows ``app.bots.chat.chat_reply``:
load the bot's *current* record, build the chat system prompt with private
memory and library files, then ``gateway.complete`` with the bot's own model,
provider reference and (optional) endpoint.

``step`` is the single state advance entry point.  It decides the next action
purely from SQLite state (session status, proposals, reviews, ``paused``), so a
crashed process can resume by calling it again.  ``run_session`` keeps at most
one background task per session on the bench object.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import bot_endpoint
from app.bots.chat import system_prompt
from app.bots.files import BotFileStore, budget_chars, context_window, render_file_slot
from app.bots.registry import BotRegistry
from app.discussion.converge import (
    REQUIRED_HARD_GATE_COUNT,
    build_round_state,
    should_converge,
)
from app.discussion.cross_review import (
    DuplicateReview,
    ProposalNotFound,
    SelfReviewForbidden,
    proposal_totals,
    submit_review,
)
from app.discussion.decision import submit_decision
from app.discussion.messages import LOG
from app.discussion.models import DiscussionSession, ReviewBallot
from app.discussion.proposals import (
    BudgetExhausted,
    DuplicateProposal,
    open_cross_review,
    start_round,
    submit_proposal,
    unseal_if_complete,
)
from app.discussion.session_store import (
    DiscussionSessionStore,
    Forbidden,
    InvalidStatus,
    NotParticipant,
    SessionNotFound,
    retry_locked,
)
from app.errors import AgentOutputError, classify_llm_error
from app.leader.steward import DiscussionSteward, InvalidParticipant
from app.memory.injection import build_memory_slot
from app.schemas.bot import BotInstance
from app.settings import PROMPTS_DIR
from app.storage.models import (
    BotRow,
    DiscussionProposalRow,
    DiscussionReviewRow,
    ProjectMembershipRow,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(
    {"approved", "rejected", "terminated", "budget_exhausted"}
)
MAX_PROPOSAL_CHARS = 6000
BOT_TIMEOUT_SECONDS = 120.0
REVIEW_DIMENSIONS = ("value", "feasibility", "testability", "clarity")

_CONVERGE_STATUS = {
    "budget_exhausted": "budget_exhausted",
    "submit_human": "converged_pending_human",
    "no_improvement": "converged_pending_human",
}

REVIEW_RETRY_HINT = (
    "上面的输出不是合法的评分 JSON。请只输出一个 JSON 对象，字段为 "
    '{"scores": {"value": 1-5 整数, "feasibility": 1-5 整数, '
    '"testability": 1-5 整数, "clarity": 1-5 整数}, '
    '"score_justification": {同上四个键，各一句理由}, '
    '"hard_gate_results": {"coverage": true/false, '
    '"conflicts_closed_or_recorded": true/false, "evidence_complete": true/false}, '
    '"dissent_items": ["..."]}。不要 Markdown 围栏，不要解释。'
)

LEADER_RETRY_HINT = (
    "上面的回复缺少可解析的自查 JSON。请重新输出完整回复：先输出规格 Markdown，"
    "然后空一行，最后输出一个 ```json 围栏块，块内只有 "
    '{"ok": true/false, "reason": "...", "dissent_items": ["..."]}。'
)


class BotFailed(Exception):
    """A bot's model call still failed after the driver's single retry."""

    def __init__(self, bot_id: str, category: str) -> None:
        super().__init__(f"bot {bot_id} failed: {category}")
        self.bot_id = bot_id
        self.category = category


# ---------------------------------------------------------------------------
# bench-scoped state


def _tasks(bench: Any) -> dict[str, asyncio.Task]:
    tasks = getattr(bench, "_discussion_driver_tasks", None)
    if tasks is None:
        tasks = {}
        setattr(bench, "_discussion_driver_tasks", tasks)
    return tasks


def _metrics(bench: Any) -> dict[str, dict[str, float]]:
    metrics = getattr(bench, "_discussion_driver_metrics", None)
    if metrics is None:
        metrics = {}
        setattr(bench, "_discussion_driver_metrics", metrics)
    return metrics


def _metric(bench: Any, session_id: str) -> dict[str, float]:
    entry = _metrics(bench).get(session_id)
    if entry is None:
        entry = {
            "tokens": 0.0,
            "elapsed_base": 0.0,
            "started_at": time.monotonic(),
        }
        _metrics(bench)[session_id] = entry
    return entry


def _seed_metric(
    bench: Any,
    session_id: str,
    record: DiscussionSession,
    *,
    force: bool = False,
) -> dict[str, float]:
    """Seed the in-process counters from the persisted session record.

    A fresh driver task starts from the values SQLite holds, so a process
    restart neither loses usage nor counts the paused interval again.
    """
    metrics = _metrics(bench)
    if not force and session_id in metrics:
        return metrics[session_id]
    entry = {
        "tokens": float(record.tokens_used),
        "elapsed_base": float(record.elapsed_seconds),
        "started_at": time.monotonic(),
    }
    metrics[session_id] = entry
    return entry


def _elapsed(entry: dict[str, float]) -> int:
    started_at = float(entry.get("started_at", time.monotonic()))
    elapsed_base = float(entry.get("elapsed_base", 0.0))
    return max(int(elapsed_base + max(time.monotonic() - started_at, 0.0)), 0)


async def _persist_usage(bench: Any, session_id: str) -> None:
    """Write the in-process counters back without touching concurrent fields."""
    entry = _metrics(bench).get(session_id)
    if entry is None:
        return
    tokens = int(entry.get("tokens", 0.0))
    elapsed = _elapsed(entry)
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)

            async def operation() -> None:
                locked = await store.get_locked(session_id)
                await store.save(
                    locked.model_copy(
                        update={
                            "tokens_used": tokens,
                            "elapsed_seconds": elapsed,
                        }
                    )
                )
                await session.commit()

            await retry_locked(session, operation)
    except Exception:  # noqa: BLE001 - persistence must never kill the driver
        logger.exception(
            "failed to persist discussion usage for session %s", session_id
        )


# ---------------------------------------------------------------------------
# small helpers


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\s"<>]+', "_", name or "").strip("_")
    return cleaned[:40] or "bot"


def _material(name: str, body: str) -> str:
    return f'<资料 name="{name}">\n{body}\n</资料>'


def _prompt_text(filename: str) -> str:
    return (Path(PROMPTS_DIR) / "discussion_p4" / filename).read_text(encoding="utf-8")


def _system_for(
    bot: BotInstance, memory: list[dict] | None, files_text: str, filename: str
) -> str:
    return system_prompt(bot, memory, files_text) + "\n\n" + _prompt_text(filename)


async def _get(bench: Any, session_id: str) -> DiscussionSession:
    async with bench.db_session() as session:
        return await DiscussionSessionStore(session).get(session_id)


async def _emit(
    bench: Any,
    session_id: str,
    kind: str,
    *,
    bot_id: str | None = None,
    round_no: int = 0,
    payload: dict[str, Any] | None = None,
) -> None:
    async with bench.db_session() as session:
        await LOG.append(
            session,
            session_id,
            kind,
            bot_id=bot_id,
            round_no=round_no,
            payload=payload or {},
        )
        await session.commit()


async def _system(
    bench: Any,
    session_id: str,
    event: str,
    text: str,
    *,
    round_no: int = 0,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {"event": event, "text": text}
    payload.update(extra)
    await _emit(bench, session_id, "system", round_no=round_no, payload=payload)


async def _load_bot_context(
    bench: Any, record: DiscussionSession, bot_id: str
) -> tuple[BotInstance, list[dict], str]:
    async with bench.db_session() as session:
        bot = await BotRegistry(session).get(bot_id)
        memory = await build_memory_slot(
            bot_id,
            project_id=record.project_id,
            run_id=None,
            session=session,
        )
        files = await BotFileStore(session).list(bot_id)
    files_text, _omitted = render_file_slot(
        files, budget_chars(context_window(bench.gateway, bot.slot))
    )
    return bot, memory, files_text


async def _call(
    bench: Any,
    session_id: str,
    bot: BotInstance,
    messages: list[dict[str, Any]],
    *,
    operation: str,
    json_mode: bool = False,
    track_discussion_usage: bool = True,
    timeout: float = BOT_TIMEOUT_SECONDS,
) -> Any:
    """One bot model call, retried once; raises ``BotFailed`` after that.

    Long single-shot generations (the Leader plan: SPEC+DESIGN+PLAN in one JSON)
    pass a larger ``timeout``; chat-style operations keep the default.
    """
    try:
        endpoint = bot_endpoint(bench.gateway, bot.bot_id, bot.provider_ref)
    except AgentOutputError as exc:
        # A real-mode bot without its own key fails closed; never fall back to
        # the workbench default credential.
        raise BotFailed(bot.bot_id, getattr(exc, "category", None) or "missing_bot_key") from exc
    last_error: BaseException | None = None
    for _attempt in range(2):
        kwargs: dict[str, Any] = {
            "role": "bot_chat",
            "discussion_operation": operation,
            "model": bot.model,
            "provider_ref": bot.provider_ref,
            "temperature": 0.6,
            "json_mode": json_mode,
        }
        if endpoint is not None:
            kwargs["endpoint"] = endpoint
        try:
            result = await asyncio.wait_for(
                bench.gateway.complete(bot.slot, messages, **kwargs),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            last_error = exc
            continue
        if track_discussion_usage:
            entry = _metric(bench, session_id)
            entry["tokens"] = float(entry.get("tokens", 0)) + int(
                getattr(result, "tokens_in", 0) or 0
            ) + int(getattr(result, "tokens_out", 0) or 0)
        return result
    category = (
        getattr(last_error, "category", None)
        or classify_llm_error(last_error)
        or "model_error"
    )
    raise BotFailed(bot.bot_id, category)


async def _pause_after_failure(
    bench: Any,
    session_id: str,
    *,
    bot_id: str | None,
    category: str,
    round_no: int = 0,
) -> None:
    try:
        async with bench.db_session() as session:
            store = DiscussionSessionStore(session)
            record = await store.get_locked(session_id)
            if record.status in TERMINAL_STATUSES:
                await session.rollback()
                return
            await store.save(record.model_copy(update={"paused": True}))
            await session.commit()
    except SessionNotFound:
        return
    text = "Bot 调用失败，讨论已暂停；可在右栏重试或跳过该 Bot 后继续。"
    await _system(
        bench,
        session_id,
        "bot_failed",
        text,
        round_no=round_no,
        bot_id=bot_id or "",
        category=category,
    )


# ---------------------------------------------------------------------------
# group / round start


async def _active_bot_ids(
    session: AsyncSession, project_id: str, leader_bot_id: str
) -> list[str]:
    stmt = (
        select(ProjectMembershipRow.bot_id)
        .join(BotRow, BotRow.bot_id == ProjectMembershipRow.bot_id)
        .where(
            ProjectMembershipRow.project_id == project_id,
            BotRow.status == "active",
        )
        .order_by(BotRow.created_at, BotRow.bot_id)
    )
    ids = [row[0] for row in (await session.execute(stmt)).all()]
    if leader_bot_id in ids:
        ids.remove(leader_bot_id)
        ids.insert(0, leader_bot_id)
    return ids


async def _step_group(bench: Any, session_id: str) -> bool:
    record = await _get(bench, session_id)
    first = record.status == "draft"
    insufficient = False
    started: DiscussionSession | None = None
    budget_hit = False
    async with bench.db_session() as session:
        ids = await _active_bot_ids(session, record.project_id, record.leader_bot_id)
        store = DiscussionSessionStore(session)
        if len(ids) < 2 or record.leader_bot_id not in ids:
            locked = await store.get_locked(session_id)
            await store.save(locked.model_copy(update={"status": "terminated"}))
            await session.commit()
            insufficient = True
        else:
            steward = DiscussionSteward(
                session, project_exists=lambda pid: pid in bench.projects
            )
            try:
                await steward.group(
                    session_id,
                    actor_bot_id=record.leader_bot_id,
                    participant_bot_ids=ids,
                )
                started = await start_round(
                    session_id,
                    None,
                    actor_bot_id=record.leader_bot_id,
                    session=session,
                )
                await session.commit()
            except InvalidParticipant:
                await session.rollback()
                insufficient = True
                async with bench.db_session() as inner:
                    locked = await DiscussionSessionStore(inner).get_locked(session_id)
                    await DiscussionSessionStore(inner).save(
                        locked.model_copy(update={"status": "terminated"})
                    )
                    await inner.commit()
            except BudgetExhausted:
                await session.commit()
                budget_hit = True
    if insufficient:
        await _system(
            bench, session_id, "terminated", "项目里可用的 Bot 少于 2 个，讨论已终止。"
        )
        return False
    if budget_hit:
        await _system(
            bench,
            session_id,
            "budget_exhausted",
            "讨论预算已耗尽，未开始新一轮。",
            round_no=record.current_round,
        )
        return False
    assert started is not None
    if first:
        await _system(bench, session_id, "session_started", "讨论已开始。")
    if record.previous_session_id:
        await _system(
            bench,
            session_id,
            "restarted_after_rejection",
            "已根据上一轮的用户意见重新开始讨论。",
        )
    await _system(
        bench,
        session_id,
        "round_started",
        f"第 {started.current_round} 轮讨论开始。",
        round_no=started.current_round,
        round=started.current_round,
    )
    return True


# ---------------------------------------------------------------------------
# proposals


async def _prior_blocks(bench: Any, record: DiscussionSession) -> list[str]:
    blocks: list[str] = []
    comment = record.resolution_comment
    previous_package = None
    if record.previous_session_id:
        async with bench.db_session() as session:
            async for previous in DiscussionSessionStore(session).predecessors(record):
                if previous_package is None:
                    previous_package = previous.decision_package
                if not comment and previous.status == "rejected":
                    comment = previous.resolution_comment
                if previous_package is not None and comment:
                    break
    if previous_package is not None:
        blocks.append(_material("上一版规格", previous_package.body_md))
    if comment:
        blocks.append(_material("用户意见", comment))
    return blocks


async def _bot_name_map(session: AsyncSession) -> dict[str, str]:
    bots = await BotRegistry(session).list_all()
    return {bot.bot_id: bot.display_name for bot in bots}


async def _revise_blocks(
    session: AsyncSession,
    record: DiscussionSession,
    bot_id: str,
    names: dict[str, str],
) -> list[str]:
    previous_round = record.current_round - 1
    if previous_round < 1:
        return []
    proposals = list(
        (
            await session.execute(
                select(DiscussionProposalRow)
                .where(
                    DiscussionProposalRow.session_id == record.session_id,
                    DiscussionProposalRow.round == previous_round,
                )
                .order_by(DiscussionProposalRow.author_bot_id)
            )
        ).scalars()
    )
    by_id = {row.proposal_id: row for row in proposals}
    blocks: list[str] = []
    for proposal in proposals:
        if proposal.author_bot_id == bot_id:
            blocks.append(_material("你的上一版方案", proposal.body_md))
        else:
            name = names.get(proposal.author_bot_id, proposal.author_bot_id)
            blocks.append(_material(f"他人方案-{_safe_name(name)}", proposal.body_md))
    review_rows = list(
        (
            await session.execute(
                select(DiscussionReviewRow).where(
                    DiscussionReviewRow.session_id == record.session_id,
                    DiscussionReviewRow.reviewer_bot_id == bot_id,
                    DiscussionReviewRow.proposal_id.in_(list(by_id)),
                )
            )
        ).scalars()
    )
    reviews = []
    for row in review_rows:
        payload = dict(row.payload)
        payload["proposal_author"] = names.get(
            by_id[row.proposal_id].author_bot_id, row.proposal_id
        )
        reviews.append(payload)
    if reviews:
        blocks.append(
            _material(
                "你收到的评审", json.dumps(reviews, ensure_ascii=False, indent=2)
            )
        )
    return blocks


async def _proposal_messages(
    bench: Any,
    record: DiscussionSession,
    bot_id: str,
    *,
    revise: bool,
) -> tuple[BotInstance, list[dict[str, Any]]]:
    bot, memory, files_text = await _load_bot_context(bench, record, bot_id)
    filename = "proposal_revise.md" if revise else "proposal.md"
    blocks: list[str] = []
    if record.requirement_text:
        blocks.append(_material("需求", record.requirement_text))
    blocks.extend(await _prior_blocks(bench, record))
    if revise:
        async with bench.db_session() as session:
            names = await _bot_name_map(session)
            blocks.extend(
                await _revise_blocks(session, record, bot_id, names)
            )
    if revise:
        instruction = (
            "请按系统提示修改你的方案：先逐条回应你收到的评审和用户意见，"
            "再输出完整六段 Markdown。全文不超过 6000 字符。"
        )
    else:
        instruction = (
            "请按系统提示独立写出一份完整方案，输出六段 Markdown。全文不超过 6000 字符。"
            "如果资料中包含用户意见，先在六段之前逐条回应。"
        )
    user = "\n\n".join([*blocks, instruction])
    messages = [
        {"role": "system", "content": _system_for(bot, memory, files_text, filename)},
        {"role": "user", "content": user},
    ]
    return bot, messages


async def _proposal_once(
    bench: Any,
    session_id: str,
    bot: BotInstance,
    messages: list[dict[str, Any]],
) -> tuple[str, bool]:
    result = await _call(bench, session_id, bot, messages, operation="proposal")
    text = (result.text or "").strip()
    truncated = False
    if len(text) > MAX_PROPOSAL_CHARS:
        retry_messages = [
            *messages,
            {"role": "assistant", "content": result.text or ""},
            {
                "role": "user",
                "content": (
                    f"上面的方案有 {len(text)} 字符，超过 6000 字符上限。"
                    "请压缩到 6000 字符以内，保留全部功能编号，重新输出完整方案。"
                ),
            },
        ]
        result = await _call(bench, session_id, bot, retry_messages, operation="proposal")
        text = (result.text or "").strip()
        if len(text) > MAX_PROPOSAL_CHARS:
            text = text[:MAX_PROPOSAL_CHARS]
            truncated = True
    if not text:
        raise BotFailed(bot.bot_id, "empty_output")
    return text, truncated


async def _submit_generated(
    bench: Any,
    session_id: str,
    bot_id: str,
    text: str,
    truncated: bool,
    round_no: int,
) -> bool:
    async with bench.db_session() as session:
        try:
            submitted = await submit_proposal(
                session_id, bot_id, text, session=session
            )
            await session.commit()
        except (InvalidStatus, NotParticipant, DuplicateProposal):
            await session.rollback()
            return False
    await _emit(
        bench,
        session_id,
        "proposal",
        bot_id=bot_id,
        round_no=round_no,
        payload={
            "proposal_id": submitted["proposal_id"],
            "chars": len(text),
            "truncated": truncated,
            "round": round_no,
        },
    )
    return True


async def _settle_round_completion(bench: Any, session_id: str) -> bool:
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        try:
            await unseal_if_complete(session_id, session=session)
        except (InvalidStatus, SessionNotFound):
            await session.rollback()
        record = await store.get(session_id)
        if record.status in {"round1_independent", "round_n_revise"}:
            try:
                await open_cross_review(session_id, session=session)
            except InvalidStatus:
                await session.rollback()
                return False
        await session.commit()
        record = await store.get(session_id)
        round_no = record.current_round
    if record.status == "cross_review":
        await _system(
            bench,
            session_id,
            "proposals_unsealed",
            f"第 {round_no} 轮方案已交齐并解封，进入互评。",
            round_no=round_no,
            round=round_no,
        )
        return True
    return False


async def _step_proposals(bench: Any, session_id: str) -> bool:
    record = await _get(bench, session_id)
    round_no = record.current_round
    async with bench.db_session() as session:
        existing = set(
            (
                await session.execute(
                    select(DiscussionProposalRow.author_bot_id).where(
                        DiscussionProposalRow.session_id == session_id,
                        DiscussionProposalRow.round == round_no,
                    )
                )
            ).scalars()
        )
    missing = [bot_id for bot_id in record.participant_bot_ids if bot_id not in existing]
    if not missing:
        return await _settle_round_completion(bench, session_id)

    revise = record.status == "round_n_revise"
    prepared: list[tuple[BotInstance, list[dict[str, Any]]]] = []
    for bot_id in missing:
        prepared.append(
            await _proposal_messages(bench, record, bot_id, revise=revise)
        )

    results = await asyncio.gather(
        *(
            _proposal_once(bench, session_id, bot, messages)
            for bot, messages in prepared
        ),
        return_exceptions=True,
    )

    failures: list[BotFailed] = []
    for (bot, _messages), outcome in zip(prepared, results):
        if isinstance(outcome, BaseException):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BotFailed):
                failures.append(outcome)
            else:
                failures.append(BotFailed(bot.bot_id, "model_error"))
            continue
        text, truncated = outcome
        await _submit_generated(
            bench, session_id, bot.bot_id, text, truncated, round_no
        )

    if failures:
        for failure in failures:
            await _pause_after_failure(
                bench,
                session_id,
                bot_id=failure.bot_id,
                category=failure.category,
                round_no=round_no,
            )
        return False
    return await _settle_round_completion(bench, session_id)


async def _bot_for(bench: Any, bot_id: str) -> BotInstance:
    async with bench.db_session() as session:
        return await BotRegistry(session).get(bot_id)


# ---------------------------------------------------------------------------
# cross review


def _extract_json(text: str) -> Any:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, re.S)
    for block in reversed(fenced):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _valid_scores(scores: Any) -> bool:
    if not isinstance(scores, dict) or set(scores) != set(REVIEW_DIMENSIONS):
        return False
    for value in scores.values():
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if not 1 <= value <= 5:
            return False
    return True


def _ballot_from(
    payload: Any, reviewer_bot_id: str, proposal_id: str
) -> ReviewBallot | None:
    if not isinstance(payload, dict):
        return None
    if not _valid_scores(payload.get("scores")):
        return None
    data = {
        "reviewer_bot_id": reviewer_bot_id,
        "proposal_id": proposal_id,
        "scores": payload.get("scores"),
        "score_justification": payload.get("score_justification"),
        "hard_gate_results": payload.get("hard_gate_results"),
        "dissent_items": payload.get("dissent_items", []),
    }
    try:
        return ReviewBallot.model_validate(data)
    except ValidationError:
        return None


_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")


def _summary(justification: dict[str, str]) -> str:
    for key in REVIEW_DIMENSIONS:
        text = (justification or {}).get(key) or ""
        match = _SENTENCE.search(text.strip())
        if match and match.group(0).strip():
            return match.group(0).strip()[:120]
    return ""


async def _review_ballot(
    bench: Any,
    session_id: str,
    bot: BotInstance,
    messages: list[dict[str, Any]],
    proposal_id: str,
) -> ReviewBallot | None:
    current = messages
    for _attempt in range(2):
        result = await _call(bench, session_id, bot, current, operation="review", json_mode=True)
        payload = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
        ballot = _ballot_from(payload, bot.bot_id, proposal_id)
        if ballot is not None:
            return ballot
        current = [
            *current,
            {"role": "assistant", "content": result.text or ""},
            {"role": "user", "content": REVIEW_RETRY_HINT},
        ]
    return None


def _review_materials(
    requirement: str,
    author_name: str,
    proposal: DiscussionProposalRow,
) -> str:
    blocks = [
        _material("需求", requirement),
        _material(
            "被评方案",
            f"作者：{author_name}\n轮次：第 {proposal.round} 轮\n\n{proposal.body_md}",
        ),
    ]
    return "\n\n".join(
        [
            *blocks,
            "请只给上面这一份方案打分，输出严格 JSON（四个维度各 1-5 整数、"
            "三个硬门槛、未解决分歧）。",
        ]
    )


async def _step_reviews(bench: Any, session_id: str) -> bool:
    record = await _get(bench, session_id)
    round_no = record.current_round
    async with bench.db_session() as session:
        proposals = list(
            (
                await session.execute(
                    select(DiscussionProposalRow).where(
                        DiscussionProposalRow.session_id == session_id,
                        DiscussionProposalRow.round == round_no,
                    )
                )
            ).scalars()
        )
        names = await _bot_name_map(session)
        existing = {
            (row[0], row[1])
            for row in (
                await session.execute(
                    select(
                        DiscussionReviewRow.reviewer_bot_id,
                        DiscussionReviewRow.proposal_id,
                    ).where(DiscussionReviewRow.session_id == session_id)
                )
            ).all()
        }
    order = {bot_id: index for index, bot_id in enumerate(record.participant_bot_ids)}
    proposals.sort(key=lambda row: order.get(row.author_bot_id, len(order)))
    work = [
        (reviewer, proposal)
        for reviewer in record.participant_bot_ids
        for proposal in proposals
        if proposal.author_bot_id != reviewer
        and (reviewer, proposal.proposal_id) not in existing
    ]
    if not work:
        return await _converge_round(bench, session_id, record)

    for reviewer, proposal in work:
        try:
            messages = await _review_messages(bench, record, reviewer, proposal, names)
            bot = await _bot_for(bench, reviewer)
            ballot = await _review_ballot(
                bench, session_id, bot, messages, proposal.proposal_id
            )
        except BotFailed as failure:
            await _pause_after_failure(
                bench,
                session_id,
                bot_id=failure.bot_id,
                category=failure.category,
                round_no=round_no,
            )
            return False
        if ballot is None:
            await _system(
                bench,
                session_id,
                "review_abstained",
                f"{names.get(reviewer, reviewer)} 对一份方案的评分格式无效，已弃权。",
                round_no=round_no,
                reviewer_bot_id=reviewer,
                proposal_id=proposal.proposal_id,
            )
            continue
        async with bench.db_session() as session:
            try:
                await submit_review(session_id, ballot, session=session)
                await session.commit()
            except (
                InvalidStatus,
                DuplicateReview,
                SelfReviewForbidden,
                ProposalNotFound,
                NotParticipant,
            ):
                await session.rollback()
                continue
        await _emit(
            bench,
            session_id,
            "review",
            bot_id=reviewer,
            round_no=round_no,
            payload={
                "proposal_id": proposal.proposal_id,
                "reviewer_bot_id": reviewer,
                "total": sum(ballot.scores.values()),
                "scores": ballot.scores,
                "hard_gate_results": ballot.hard_gate_results,
                "summary": _summary(ballot.score_justification),
            },
        )
    return await _converge_round(bench, session_id, record)


async def _review_messages(
    bench: Any,
    record: DiscussionSession,
    reviewer: str,
    proposal: DiscussionProposalRow,
    names: dict[str, str],
) -> list[dict[str, Any]]:
    bot, memory, files_text = await _load_bot_context(bench, record, reviewer)
    author_name = names.get(proposal.author_bot_id, proposal.author_bot_id)
    user = _review_materials(record.requirement_text, author_name, proposal)
    return [
        {"role": "system", "content": _system_for(bot, memory, files_text, "review.md")},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# convergence


async def _converge_round(
    bench: Any, session_id: str, record: DiscussionSession
) -> bool:
    entry = _metric(bench, session_id)
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        locked = await store.get_locked(session_id)
        state = await build_round_state(
            session,
            locked,
            tokens_used=int(entry.get("tokens", 0)),
            elapsed_seconds=_elapsed(entry),
        )
        action, reason = should_converge(state)
        if action != "revise":
            status = _CONVERGE_STATUS.get(action, "converged_pending_human")
            await store.save(locked.model_copy(update={"status": status}))
            await session.commit()
        else:
            await session.rollback()
    round_no = locked.current_round
    threshold = state.budget.score_gap_threshold
    conditions_met = (
        state.all_required_hard_gates_pass
        and state.score_spread is not None
        and threshold is not None
        and state.score_spread <= threshold
    )

    if action == "budget_exhausted":
        await _system(
            bench,
            session_id,
            "budget_exhausted",
            "讨论预算已耗尽。",
            round_no=round_no,
            reason=reason,
        )
        return False
    if action == "submit_human" and threshold is not None and not conditions_met:
        # 聊天文案只留结论；分差、阈值与硬门槛细节保留在消息 payload 里供活动与排查使用。
        await _system(
            bench,
            session_id,
            "forced_submit",
            f"已达第 {round_no} 轮上限，仍未达成一致，交由 Leader 综合。",
            round_no=round_no,
            action=action,
            reason=reason,
        )
        return True
    if action in {"submit_human", "no_improvement"}:
        await _system(
            bench,
            session_id,
            "converged",
            f"第 {round_no} 轮达到收敛条件，交由 Leader 综合。",
            round_no=round_no,
            action=action,
            reason=reason,
        )
        return True
    if action == "revise":
        return await _start_revision(bench, session_id, record.leader_bot_id, reason)
    return False


async def _start_revision(
    bench: Any, session_id: str, leader_bot_id: str, reason: str
) -> bool:
    started: DiscussionSession | None = None
    exhausted = False
    async with bench.db_session() as session:
        try:
            started = await start_round(
                session_id, None, actor_bot_id=leader_bot_id, session=session
            )
            await session.commit()
        except BudgetExhausted:
            await session.commit()
            exhausted = True
        except InvalidStatus:
            await session.rollback()
            return False
    if exhausted:
        await _system(
            bench,
            session_id,
            "budget_exhausted",
            "讨论轮次或预算已耗尽。",
        )
        return False
    assert started is not None
    await _system(
        bench,
        session_id,
        "round_started",
        f"第 {started.current_round} 轮讨论开始。",
        round_no=started.current_round,
        round=started.current_round,
        reason=reason,
    )
    return True


# ---------------------------------------------------------------------------
# leader synthesis


def _parse_leader_output(text: str) -> tuple[str, dict[str, Any] | None]:
    blocks = list(re.finditer(r"```json\s*(.*?)```", text or "", re.S))
    if not blocks:
        return (text or "").strip(), None
    match = blocks[-1]
    try:
        data = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return (text or "")[: match.start()].strip(), None
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return (text or "")[: match.start()].strip(), None
    reason = data.get("reason", "")
    dissent = data.get("dissent_items", [])
    if not isinstance(reason, str) or not isinstance(dissent, list):
        return (text or "")[: match.start()].strip(), None
    if not all(isinstance(item, str) for item in dissent):
        return (text or "")[: match.start()].strip(), None
    return (text or "")[: match.start()].strip(), {
        "ok": data["ok"],
        "reason": reason,
        "dissent_items": dissent,
    }


async def _leader_materials(
    bench: Any, record: DiscussionSession
) -> tuple[list[str], list[str]]:
    async with bench.db_session() as session:
        names = await _bot_name_map(session)
        proposals = list(
            (
                await session.execute(
                    select(DiscussionProposalRow)
                    .where(
                        DiscussionProposalRow.session_id == record.session_id,
                        DiscussionProposalRow.round == record.current_round,
                    )
                    .order_by(DiscussionProposalRow.author_bot_id)
                )
            ).scalars()
        )
        proposal_ids = [row.proposal_id for row in proposals]
        review_rows = (
            list(
                (
                    await session.execute(
                        select(DiscussionReviewRow).where(
                            DiscussionReviewRow.session_id == record.session_id,
                            DiscussionReviewRow.proposal_id.in_(proposal_ids),
                        )
                    )
                ).scalars()
            )
            if proposal_ids
            else []
        )
        ballots = [ReviewBallot.model_validate(row.payload) for row in review_rows]
        totals = proposal_totals(ballots)
        state = await build_round_state(session, record)
    blocks: list[str] = []
    if record.requirement_text:
        blocks.append(_material("需求", record.requirement_text))
    blocks.extend(await _prior_blocks(bench, record))
    for proposal in proposals:
        name = names.get(proposal.author_bot_id, proposal.author_bot_id)
        blocks.append(_material(f"方案-{_safe_name(name)}", proposal.body_md))
    review_view = []
    author_by_id = {row.proposal_id: row.author_bot_id for row in proposals}
    for row in review_rows:
        payload = dict(row.payload)
        payload["proposal_author"] = names.get(
            author_by_id.get(row.proposal_id, ""), row.proposal_id
        )
        payload["reviewer"] = names.get(row.reviewer_bot_id, row.reviewer_bot_id)
        review_view.append(payload)
    summary = {
        "proposal_totals": {
            names.get(author_by_id.get(pid, ""), pid): total
            for pid, total in totals.items()
        },
        "reviews": review_view,
    }
    blocks.append(
        _material("评分与硬门槛", json.dumps(summary, ensure_ascii=False, indent=2))
    )
    if state.dissent_items:
        blocks.append(
            _material(
                "未解决分歧",
                json.dumps(state.dissent_items, ensure_ascii=False, indent=2),
            )
        )
    return blocks, state.dissent_items


async def _forced_convergence_note(
    bench: Any, record: DiscussionSession
) -> str | None:
    async with bench.db_session() as session:
        state = await build_round_state(session, record)
    threshold = state.budget.score_gap_threshold
    if threshold is None or state.current_round < state.budget.max_rounds:
        return None
    conditions_met = (
        state.all_required_hard_gates_pass
        and state.score_spread is not None
        and state.score_spread <= threshold
    )
    if conditions_met:
        return None
    latest = state.hard_gate_pass_counts[-1] if state.hard_gate_pass_counts else 0
    unmet = max(0, REQUIRED_HARD_GATE_COUNT - latest)
    spread_text = (
        "分差无法计算"
        if state.score_spread is None
        else f"分差 {state.score_spread:g}"
    )
    return (
        f"未达成一致：第 {state.current_round} 轮上限，{spread_text}"
        f"（阈值 {threshold:g}），未通过硬门槛 {unmet} 项"
    )


async def _step_leader(bench: Any, session_id: str) -> bool:
    record = await _get(bench, session_id)
    round_no = record.current_round
    leader_bot_id = record.leader_bot_id
    bot, memory, files_text = await _load_bot_context(bench, record, leader_bot_id)
    blocks, review_dissent = await _leader_materials(bench, record)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _system_for(bot, memory, files_text, "leader_synthesis.md"),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    *blocks,
                    "请综合资料写出完整需求规格 Markdown，并在最后用一个 json 围栏块"
                    "输出自查结果。若有用户驳回意见，请把每条修改落实到相关章节和验收标准，"
                    "并指出对应的修改。保持原规格正文不变的版本无法获批。",
                ]
            ),
        },
    ]
    spec = ""
    verdict: dict[str, Any] | None = None
    try:
        for _attempt in range(2):
            result = await _call(bench, session_id, bot, messages, operation="synthesis")
            spec, verdict = _parse_leader_output(result.text or "")
            if verdict is not None:
                break
            messages = [
                *messages,
                {"role": "assistant", "content": result.text or ""},
                {"role": "user", "content": LEADER_RETRY_HINT},
            ]
    except BotFailed as failure:
        await _pause_after_failure(
            bench,
            session_id,
            bot_id=failure.bot_id,
            category=failure.category,
            round_no=round_no,
        )
        return False

    if verdict is None:
        verdict = {
            "ok": False,
            "reason": "Leader 的自查 JSON 无法解析",
            "dissent_items": [],
        }
        spec = spec or "（Leader 未输出可解析的规格）"
    forced_note = await _forced_convergence_note(bench, record)
    dissent = list(
        dict.fromkeys(
            [
                *verdict["dissent_items"],
                *review_dissent,
                *([forced_note] if forced_note else []),
            ]
        )
    )
    if verdict["ok"]:
        return await _leader_submit(bench, session_id, leader_bot_id, spec, dissent, round_no)
    return await _leader_request_revision(
        bench,
        session_id,
        leader_bot_id,
        spec,
        dissent,
        str(verdict.get("reason") or "").strip() or "未通过自查",
        round_no,
    )


async def _leader_submit(
    bench: Any,
    session_id: str,
    leader_bot_id: str,
    spec: str,
    dissent: list[str],
    round_no: int,
) -> bool:
    async with bench.db_session() as session:
        try:
            await submit_decision(
                session_id,
                spec,
                dissent,
                actor_bot_id=leader_bot_id,
                session=session,
            )
            await session.commit()
        except (Forbidden, InvalidStatus):
            await session.rollback()
            return False
    await _emit(
        bench,
        session_id,
        "leader",
        bot_id=leader_bot_id,
        round_no=round_no,
        payload={
            "action": "submit",
            "text": f"已提交需求规格，未解决分歧 {len(dissent)} 条。",
        },
    )
    return True


async def _leader_request_revision(
    bench: Any,
    session_id: str,
    leader_bot_id: str,
    spec: str,
    dissent: list[str],
    reason: str,
    round_no: int,
) -> bool:
    await _emit(
        bench,
        session_id,
        "leader",
        bot_id=leader_bot_id,
        round_no=round_no,
        payload={"action": "request_revision", "text": reason},
    )
    started: DiscussionSession | None = None
    forced = False
    forced_dissent: list[str] = dissent
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        try:
            started = await start_round(
                session_id, None, actor_bot_id=leader_bot_id, session=session
            )
            await session.commit()
        except BudgetExhausted:
            locked = await store.get_locked(session_id)
            await store.save(
                locked.model_copy(update={"status": "converged_pending_human"})
            )
            forced_dissent = list(
                dict.fromkeys([*dissent, f"Leader 未满意：{reason}"])
            )
            try:
                await submit_decision(
                    session_id,
                    spec,
                    forced_dissent,
                    actor_bot_id=leader_bot_id,
                    session=session,
                )
                await session.commit()
            except (Forbidden, InvalidStatus):
                await session.rollback()
                return False
            forced = True
        except InvalidStatus:
            await session.rollback()
            return False
    if forced:
        await _system(
            bench,
            session_id,
            "forced_submit",
            f"已达到 {round_no} 轮上限，Leader 未满意也强制提交：{reason}",
            round_no=round_no,
        )
        await _emit(
            bench,
            session_id,
            "leader",
            bot_id=leader_bot_id,
            round_no=round_no,
            payload={
                "action": "submit",
                "text": f"轮次到顶，已强制提交需求规格，未解决分歧 {len(forced_dissent)} 条。",
            },
        )
        return True
    assert started is not None
    await _system(
        bench,
        session_id,
        "round_started",
        f"第 {started.current_round} 轮讨论开始，Leader 要求再改一轮。",
        round_no=started.current_round,
        round=started.current_round,
        reason=reason,
    )
    return True


# ---------------------------------------------------------------------------
# public API


def _needs_recovery(record: DiscussionSession) -> bool:
    # ``draft`` never started a driver (create is immediately followed by run),
    # so pausing it would claim work was interrupted when none was.
    if record.status in TERMINAL_STATUSES or record.paused or record.status == "draft":
        return False
    if record.status == "converged_pending_human" and record.decision_package is not None:
        return False
    return True


async def recover_interrupted_sessions(bench: Any) -> list[str]:
    """Pause sessions whose in-process driver died with the previous process.

    A restarted server has no driver tasks, so sessions left unpaused would
    stall forever: the UI never calls ``run`` on its own.  Walking the whole
    table and pausing each interrupted session makes the next user action an
    explicit ``resume``.
    """
    async with bench.db_session() as session:
        records = await DiscussionSessionStore(session).list_all()
    recovered: list[str] = []
    for record in records:
        if not _needs_recovery(record):
            continue
        session_id = record.session_id
        try:
            async with bench.db_session() as session:
                store = DiscussionSessionStore(session)
                locked = await store.get_locked(session_id)
                if not _needs_recovery(locked):
                    await session.rollback()
                    continue
                await store.save(locked.model_copy(update={"paused": True}))
                await session.commit()
                round_no = locked.current_round
            await _system(
                bench,
                session_id,
                "paused",
                "服务已重启，讨论已暂停。点击“继续”从中断处接着跑。",
                round_no=round_no,
                reason="server_restart",
            )
        except Exception:  # noqa: BLE001 - one bad session must not block startup
            logger.exception(
                "discussion recovery failed for session %s", session_id
            )
            continue
        recovered.append(session_id)
    return recovered


async def step(bench: Any, session_id: str) -> bool:
    """Advance the session by one state-machine action.

    Returns ``True`` when work was done and another step may follow; ``False``
    for terminal, paused or non-actionable states.  Usage counters are written
    back on every return path, including cancellation and failures.
    """
    record = await _get(bench, session_id)
    if record.status in TERMINAL_STATUSES or record.paused:
        return False
    _seed_metric(bench, session_id, record)
    try:
        if record.status in {"draft", "grouping"}:
            return await _step_group(bench, session_id)
        if record.status in {"round1_independent", "round_n_revise"}:
            return await _step_proposals(bench, session_id)
        if record.status == "cross_review":
            return await _step_reviews(bench, session_id)
        if record.status == "converged_pending_human":
            if record.decision_package is not None:
                return False
            return await _step_leader(bench, session_id)
        return False
    finally:
        await _persist_usage(bench, session_id)


async def run_session(bench: Any, session_id: str) -> None:
    """Start the background driver once per session (idempotent)."""
    record = await _get(bench, session_id)
    if record.status in TERMINAL_STATUSES or record.paused:
        return
    if record.status == "converged_pending_human" and record.decision_package is not None:
        return
    tasks = _tasks(bench)
    existing = tasks.get(session_id)
    if existing is not None and not existing.done():
        return
    _seed_metric(bench, session_id, record, force=True)
    tasks[session_id] = asyncio.create_task(_drive(bench, session_id))


def is_running(bench: Any, session_id: str) -> bool:
    task = _tasks(bench).get(session_id)
    return task is not None and not task.done()


async def _drive(bench: Any, session_id: str) -> None:
    try:
        while True:
            record = await _get(bench, session_id)
            if record.status in TERMINAL_STATUSES or record.paused:
                return
            if not await step(bench, session_id):
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - background task must not vanish
        await _pause_after_failure(
            bench,
            session_id,
            bot_id=None,
            category=classify_llm_error(exc) or "internal",
        )
    finally:
        await _persist_usage(bench, session_id)
        tasks = _tasks(bench)
        if tasks.get(session_id) is asyncio.current_task():
            tasks.pop(session_id, None)


async def _cancel_task(bench: Any, session_id: str) -> None:
    task = _tasks(bench).pop(session_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 - cancellation must not surface
        pass


async def pause_session(bench: Any, session_id: str) -> DiscussionSession:
    await _cancel_task(bench, session_id)
    await _persist_usage(bench, session_id)
    already_paused = False
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        record = await store.get_locked(session_id)
        if record.status in TERMINAL_STATUSES:
            await session.rollback()
            _metrics(bench).pop(session_id, None)
            return record
        already_paused = record.paused
        updated = record.model_copy(update={"paused": True})
        await store.save(updated)
        await session.commit()
    _metrics(bench).pop(session_id, None)
    if not already_paused:
        await _system(bench, session_id, "paused", "讨论已暂停。")
    return updated


async def resume_session(
    bench: Any, session_id: str, skip_bot_ids: list[str] | None = None
) -> DiscussionSession:
    skipped: list[str] = []
    terminated = False
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        record = await store.get_locked(session_id)
        if record.status in TERMINAL_STATUSES:
            await session.rollback()
            return record
        participants = list(record.participant_bot_ids)
        skipped = [
            bot_id
            for bot_id in dict.fromkeys(skip_bot_ids or [])
            if bot_id in participants
        ]
        remaining = [bot_id for bot_id in participants if bot_id not in skipped]
        terminated = (
            len(remaining) < 2 or record.leader_bot_id not in remaining
        )
        fields: dict[str, Any] = {
            "paused": False,
            "participant_bot_ids": remaining,
        }
        if terminated:
            fields["status"] = "terminated"
        updated = record.model_copy(update=fields)
        await store.save(updated)
        await session.commit()
    round_no = updated.current_round
    for bot_id in skipped:
        await _system(
            bench,
            session_id,
            "bot_skipped",
            f"已跳过 Bot {bot_id}。",
            round_no=round_no,
            bot_id=bot_id,
        )
    if terminated:
        await _cancel_task(bench, session_id)
        _metrics(bench).pop(session_id, None)
        await _system(
            bench,
            session_id,
            "terminated",
            "参与者少于 2 人，讨论已终止。",
            round_no=round_no,
        )
        return updated
    await _system(bench, session_id, "resumed", "讨论已继续。", round_no=round_no)
    await run_session(bench, session_id)
    return updated


async def terminate_session(bench: Any, session_id: str) -> DiscussionSession:
    await _cancel_task(bench, session_id)
    await _persist_usage(bench, session_id)
    async with bench.db_session() as session:
        store = DiscussionSessionStore(session)
        record = await store.get_locked(session_id)
        if record.status in TERMINAL_STATUSES:
            await session.rollback()
            _metrics(bench).pop(session_id, None)
            return record
        updated = record.model_copy(
            update={"status": "terminated", "paused": False}
        )
        await store.save(updated)
        await session.commit()
    _metrics(bench).pop(session_id, None)
    await _system(
        bench, session_id, "terminated", "讨论已终止。", round_no=updated.current_round
    )
    return updated


__all__ = [
    "BotFailed",
    "TERMINAL_STATUSES",
    "is_running",
    "pause_session",
    "recover_interrupted_sessions",
    "resume_session",
    "run_session",
    "step",
    "terminate_session",
]
