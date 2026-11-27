from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.errors import AgentOutputError, ReplayMissing, classified_llm_error
from app.llm.types import LLMResult
from app.settings import ModelsFile, get_settings


def validate_tool_protocol(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> None:
    if tools:
        for spec in tools:
            fn = spec.get("function") if isinstance(spec, dict) else None
            params = (fn or spec or {}).get("parameters") if isinstance(fn or spec, dict) else None
            if not isinstance(params, dict) or "properties" not in params:
                raise ValueError("tool schema missing properties")
            if params.get("type") != "object":
                raise ValueError("tool schema type must be object")
    pending_ids: set[str] | None = None
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            pending_ids = set()
            for call in message["tool_calls"]:
                call_id = str(call.get("id") or "")
                if not call_id:
                    raise ValueError("assistant tool_calls missing id")
                pending_ids.add(call_id)
            continue
        if role == "tool":
            if not pending_ids:
                raise ValueError("tool message without assistant tool_calls")
            call_id = str(message.get("tool_call_id") or "")
            if not call_id:
                raise ValueError("tool message missing tool_call_id")
            if call_id not in pending_ids:
                raise ValueError("tool_call_id mismatch")
            pending_ids.discard(call_id)
            if not pending_ids:
                pending_ids = None
            continue
        if pending_ids:
            raise ValueError("missing tool responses for assistant tool_calls")
        pending_ids = None


def _item_tokens(item: dict[str, Any]) -> tuple[int, int]:
    return int(item.get("tokens_in") or 0), int(item.get("tokens_out") or 0)


class ScriptedProvider:
    def __init__(self, queue: list[Any] | None = None) -> None:
        self.queue: list[Any] = list(queue or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, item: Any) -> None:
        self.queue.append(item)

    def next_item(self, slot: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        if not self.queue:
            raise RuntimeError(f"scripted queue empty for slot={slot}")
        return self.queue.pop(0)

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self.calls.append({"slot": slot, "messages": messages, "schema": schema, "tools": tools})
        validate_tool_protocol(messages, tools)
        item = self.next_item(slot, messages, **kwargs)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResult):
            return item
        if isinstance(item, dict) and item.get("tool_calls"):
            tokens_in, tokens_out = _item_tokens(item)
            return LLMResult(
                tool_calls=item["tool_calls"],
                parsed=item.get("parsed"),
                text=item.get("text", ""),
                model=slot,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        if isinstance(item, dict):
            tokens_in, tokens_out = _item_tokens(item)
            parsed = {k: v for k, v in item.items() if k not in {"tokens_in", "tokens_out", "tool_calls", "text"}}
            if item.get("parsed") is not None:
                parsed = item["parsed"]
            return LLMResult(
                text=item.get("text") or json.dumps(parsed or item, ensure_ascii=False),
                parsed=parsed or item,
                model=slot,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        return LLMResult(text=str(item), model=slot)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.queue and isinstance(self.queue[0], list):
            return self.queue.pop(0)
        return [[float((sum(ord(c) for c in t) + i) % 13) for i in range(8)] for t in texts]


class ReplayProvider:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.index = 0

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self.index += 1
        role = kwargs.get("role") or "unknown"
        path = self.folder / f"{self.index:03d}-{role}.json"
        if not path.exists():
            raise ReplayMissing(f"missing replay {path.name} for role={role} index={self.index}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(
            text=data.get("text", json.dumps(data.get("parsed") or {}, ensure_ascii=False)),
            parsed=data.get("parsed"),
            tool_calls=data.get("tool_calls") or [],
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            model=data.get("model", slot),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        path = self.folder / "embeddings.json"
        if not path.exists():
            raise ReplayMissing("missing replay embeddings.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data[: len(texts)]


class DashScopeProvider:
    def __init__(self, models: ModelsFile) -> None:
        self.models = models
        self._client = None
        self._bot_clients: dict[tuple[str, str], Any] = {}

    def _bot_client(self, base_url: str, api_key: str) -> Any:
        """Client for a bot's own provider key; cached per (base_url, key)."""
        cache_key = (base_url, hashlib.sha256(api_key.encode("utf-8")).hexdigest())
        client = self._bot_clients.get(cache_key)
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                http_client=httpx.AsyncClient(
                    timeout=httpx.Timeout(600.0, connect=10.0),
                    trust_env=bool(get_settings().test3_http_trust_env),
                ),
            )
            self._bot_clients[cache_key] = client
        return client

    def _client_obj(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            settings = get_settings()
            key = settings.dashscope_api_key
            # 【修改点】没有密钥时显式报错，不要带 "missing" 去发请求
            if not key:
                raise AgentOutputError("模型配置或凭据不可用", category="auth")
            # Default to a direct connection: do not inherit shell http(s)_proxy / all_proxy,
            # so a socks5h:// proxy without socksio cannot fail before the request is built.
            self._client = AsyncOpenAI(
                base_url=self.models.base_url,
                api_key=key,
                http_client=httpx.AsyncClient(
                    timeout=httpx.Timeout(600.0, connect=10.0),
                    trust_env=bool(settings.test3_http_trust_env),
                ),
            )
        return self._client

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        cfg = self.models.slots[slot]
        started = time.perf_counter()
        # A bot's own endpoint (base_url + its API key) replaces the workbench client.
        endpoint = kwargs.get("endpoint")
        own_endpoint = isinstance(endpoint, dict) and endpoint.get("api_key") and endpoint.get("base_url")
        foreign = bool(own_endpoint) and endpoint["base_url"] != self.models.base_url
        # extra_body is tuned for the configured provider; do not leak it to others.
        extra: dict[str, Any] = {"extra_body": cfg.extra_body} if cfg.extra_body and not foreign else {}
        # Callers that want free text (bot chat) pass json_mode=False.
        if kwargs.get("json_mode", cfg.json_mode):
            extra["response_format"] = {"type": "json_object"}
        
        if tools:
            if cfg.tool_calls:
                extra["tools"] = tools
            else:
                # 【修改点】不支持 tool calls 的模型必须显式报错，不能静默忽略
                raise ValueError(f"Model {cfg.model} for slot {slot} does not support tool_calls (cfg.tool_calls is false).")

        try:
            client = (
                self._bot_client(endpoint["base_url"], endpoint["api_key"]) if own_endpoint else self._client_obj()
            )
            completion = await client.chat.completions.create(
                model=kwargs.get("model") or cfg.model,
                messages=messages,
                temperature=kwargs.get("temperature", cfg.temperature),
                max_tokens=cfg.max_tokens,
                **extra,
            )
        except AgentOutputError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise classified_llm_error(exc) from exc
        choice = completion.choices[0]
        text = choice.message.content or ""
        parsed = None
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = None
        usage = completion.usage
        return LLMResult(
            text=text,
            parsed=parsed,
            tool_calls=_dashscope_tool_calls(choice.message),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=completion.model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cfg = self.models.slots["embedding"]
        result = await self._client_obj().embeddings.create(model=cfg.model, input=texts)
        return [item.embedding for item in result.data]


def _dashscope_tool_calls(message: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        raw_args = getattr(getattr(call, "function", None), "arguments", None) or "{}"
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            arguments = {}
        fn = getattr(call, "function", None)
        calls.append(
            {
                "id": getattr(call, "id", None) or f"call_{index}",
                "type": getattr(call, "type", None) or "function",
                "name": getattr(fn, "name", "") if fn is not None else "",
                "arguments": arguments,
            }
        )
    return calls
