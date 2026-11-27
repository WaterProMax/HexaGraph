"""Turn free-form user notes into structured, agent-readable memory.

Runs inside ``POST /api/memory/records`` for notes typed in the UI.  It uses the
owning bot's own model and its encrypted API key (never a hard-coded one) and is
strictly best-effort: any failure returns ``None`` and the caller stores the
note unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.agents.runtime import bot_endpoint
from app.llm.gateway import Gateway
from app.memory.store import SecretInBody, assert_no_secrets
from app.schemas.bot import BotInstance

TIMEOUT_SECONDS = 25.0
logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 8000
_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._\-]{5,}")

SYSTEM_PROMPT = (
    "你是 AI 开发助手的记忆整理员。用户会给你一段随手写下的原始笔记，格式不固定。"
    "请把它整合成一段通顺完整的话，作为这个 Agent 的长期记忆，供开发 Agent 之后直接阅读。\n"
    "要求：\n"
    "1. 只整理，不增删事实，不臆测；保留所有名称、数字、路径、约束。\n"
    "2. 使用与原文相同的语言；写成一段连贯的话，不要列表、不要标题、不要多余的客套。\n"
    "3. 不要输出任何密钥、令牌或口令。\n"
    "只输出一个 JSON 对象："
    '{"title": "不超过 20 字的标题", "text": "整合后的一段话"}'
)


def contains_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text))


def _clean(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    text = parsed.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    title = parsed.get("title")
    result: dict[str, Any] = {
        "title": title.strip()[:40] if isinstance(title, str) else "",
        "text": text.strip()[:MAX_INPUT_CHARS],
    }
    try:
        assert_no_secrets(result)
    except SecretInBody:
        return None
    if contains_secret(result["title"] + " " + result["text"]):
        return None
    return result


async def organize_note(gateway: Gateway, bot: BotInstance, raw: str) -> dict[str, Any] | None:
    """Return ``{title, text}`` or ``None`` when unavailable."""
    raw = raw.strip()
    if not raw or len(raw) > MAX_INPUT_CHARS:
        return None
    try:
        kwargs: dict[str, Any] = {"model": bot.model, "provider_ref": bot.provider_ref, "temperature": 0.2}
        endpoint = bot_endpoint(gateway, bot.bot_id, bot.provider_ref)
        if endpoint is not None:
            kwargs["endpoint"] = endpoint
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw},
        ]
        result = await asyncio.wait_for(
            gateway.complete(bot.slot, messages, role="memory_organizer", **kwargs),
            timeout=TIMEOUT_SECONDS,
        )
        return _clean(result.parsed)
    except Exception as exc:  # noqa: BLE001 - best effort, caller keeps the raw note
        category = getattr(exc, "category", "") or exc.__class__.__name__
        logger.warning("memory organize skipped (%s); raw note kept", category)
        return None


__all__ = ["contains_secret", "organize_note"]
