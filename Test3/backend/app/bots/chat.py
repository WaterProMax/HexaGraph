"""One-shot chat with a bot, using the bot's own model and its encrypted API key.

The conversation lives in the browser; every request carries the history.  The
bot's private memory is injected into the system prompt so the bot "remembers".
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.agents.runtime import _render_memory_slot, bot_endpoint
from app.bots.files import budget_chars, context_window, render_file_slot
from app.llm.gateway import Gateway
from app.schemas.bot import BotInstance
from app.storage.models import BotFileRow

MAX_MESSAGES = 40
MAX_CHARS = 8000
TIMEOUT_SECONDS = 120.0


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHARS)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)

    @field_validator("messages")
    @classmethod
    def _ends_with_user(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if value[-1].role != "user":
            raise ValueError("last message must be from the user")
        return value


def system_prompt(bot: BotInstance, memory: list[dict] | None, files_text: str = "") -> str:
    parts = [
        f"你是 {bot.display_name}，一个担任「{bot.role_template}」角色的 AI 开发助手。",
        "用中文回答，简洁、准确；不确定的事直接说明，不要编造。",
    ]
    block = _render_memory_slot(memory)
    if block:
        parts.append("下面是你的长期记忆，回答时参考，但不必逐条复述。\n" + block)
    if files_text:
        parts.append(files_text)
    return "\n\n".join(parts)


async def chat_reply(
    gateway: Gateway,
    bot: BotInstance,
    history: list[ChatMessage],
    memory: list[dict] | None,
    files: list[BotFileRow] | None = None,
) -> dict[str, Any]:
    """Return ``{"reply", "model"}`` (plus ``files_omitted`` when the library did not fit).

    Raises ``AgentOutputError`` on model failure.
    """
    files_text, omitted = render_file_slot(
        files or [], budget_chars(context_window(gateway, bot.slot))
    )
    messages = [{"role": "system", "content": system_prompt(bot, memory, files_text)}]
    messages.extend({"role": item.role, "content": item.content} for item in history)
    kwargs: dict[str, Any] = {
        "model": bot.model,
        "provider_ref": bot.provider_ref,
        "temperature": 0.6,
        "json_mode": False,
    }
    endpoint = bot_endpoint(gateway, bot.bot_id, bot.provider_ref)
    if endpoint is not None:
        kwargs["endpoint"] = endpoint
    result = await asyncio.wait_for(
        gateway.complete(bot.slot, messages, role="bot_chat", **kwargs),
        timeout=TIMEOUT_SECONDS,
    )
    reply: dict[str, Any] = {
        "reply": (result.text or "").strip(),
        "model": result.model or bot.model,
    }
    if omitted:
        reply["files_omitted"] = omitted
    return reply


__all__ = ["ChatMessage", "ChatRequest", "chat_reply", "system_prompt"]
