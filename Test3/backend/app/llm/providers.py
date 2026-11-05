from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.errors import ReplayMissing
from app.llm.types import LLMResult
from app.settings import ModelsFile, get_settings


class ScriptedProvider:
    def __init__(self, queue: list[Any] | None = None) -> None:
        self.queue: list[Any] = list(queue or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, item: Any) -> None:
        self.queue.append(item)

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
        if not self.queue:
            raise RuntimeError(f"scripted queue empty for slot={slot}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResult):
            return item
        if isinstance(item, dict) and item.get("tool_calls"):
            return LLMResult(tool_calls=item["tool_calls"], parsed=item.get("parsed"), text=item.get("text", ""), model=slot)
        if isinstance(item, dict):
            return LLMResult(text=json.dumps(item, ensure_ascii=False), parsed=item, model=slot)
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

    def _client_obj(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            settings = get_settings()
            key = settings.dashscope_api_key
            self._client = AsyncOpenAI(base_url=self.models.base_url, api_key=key or "missing")
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
        extra: dict[str, Any] = {"extra_body": cfg.extra_body} if cfg.extra_body else {}
        if cfg.json_mode:
            extra["response_format"] = {"type": "json_object"}
        if tools and cfg.tool_calls:
            extra["tools"] = tools
        completion = await self._client_obj().chat.completions.create(
            model=kwargs.get("model") or cfg.model,
            messages=messages,
            temperature=kwargs.get("temperature", cfg.temperature),
            max_tokens=cfg.max_tokens,
            **extra,
        )
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
            tool_calls=[
                {"name": c.function.name, "arguments": json.loads(c.function.arguments or "{}")}
                for c in (choice.message.tool_calls or [])
            ],
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=completion.model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cfg = self.models.slots["embedding"]
        result = await self._client_obj().embeddings.create(model=cfg.model, input=texts)
        return [item.embedding for item in result.data]
