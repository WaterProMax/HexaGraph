from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.errors import AgentOutputError, ReplayMissing
from app.llm.providers import DashScopeProvider, ReplayProvider, ScriptedProvider
from app.llm.types import LLMResult
from app.settings import ModelsFile, get_settings


class TokenBucket:
    def __init__(self, rate: int, clock=time.monotonic) -> None:
        self.rate = rate
        self.clock = clock
        self.tokens = float(rate)
        self.updated = clock()

    def take(self, n: int = 1) -> bool:
        now = self.clock()
        elapsed = now - self.updated
        self.updated = now
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / 60))
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class Gateway:
    def __init__(
        self,
        models: ModelsFile,
        provider: Any,
        *,
        data_dir: Path | None = None,
        clock=time.monotonic,
    ) -> None:
        self.models = models
        self.provider = provider
        self.data_dir = data_dir
        self.sema = asyncio.Semaphore(int(models.limits.get("max_concurrency", 6)))
        self.bucket = TokenBucket(int(models.limits.get("requests_per_minute", 120)), clock=clock)
        self.stats = {"tokens_in": 0, "tokens_out": 0, "calls": 0, "fallbacks": 0}
        self.events: list[dict[str, Any]] = []

    async def complete(self, slot: str, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        async with self.sema:
            while not self.bucket.take():
                await asyncio.sleep(0.01)
            return await self._complete_with_retry(slot, messages, **kwargs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.provider.embed(texts)

    async def _complete_with_retry(self, slot: str, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        cfg = self.models.slots[slot]
        last_error: Exception | None = None
        model = cfg.model
        for attempt in range(3):
            try:
                result = await self.provider.complete(slot, messages, model=model, **kwargs)
                self.stats["tokens_in"] += result.tokens_in
                self.stats["tokens_out"] += result.tokens_out
                self.stats["calls"] += 1
                self._persist(slot, messages, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not _retryable(exc) or attempt == 2:
                    break
                await asyncio.sleep(0.01 * (2**attempt))
        if cfg.fallback:
            self.stats["fallbacks"] += 1
            self.events.append({"kind": "llm.fallback", "slot": slot, "fallback": cfg.fallback})
            try:
                result = await self.provider.complete(slot, messages, model=cfg.fallback, **kwargs)
                self._persist(slot, messages, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise AgentOutputError(f"llm failed for slot {slot}: {last_error}")

    def _persist(self, slot: str, messages: list[dict[str, Any]], result: LLMResult) -> None:
        if not self.data_dir:
            return
        folder = self.data_dir / "llm"
        folder.mkdir(parents=True, exist_ok=True)
        n = self.stats["calls"]
        (folder / f"{n:04d}-{slot}.json").write_text(
            json.dumps({"messages": _redact(messages), "result": result.text[:4000]}, ensure_ascii=False),
            encoding="utf-8",
        )


def _retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "rate" in name


def _redact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    key = get_settings().dashscope_api_key
    blob = json.dumps(messages, ensure_ascii=False)
    if key:
        blob = blob.replace(key, "[REDACTED]")
    return json.loads(blob)


def build_provider(kind: str, models: ModelsFile, replay_dir: Path | None = None, queue: list[Any] | None = None) -> Any:
    if kind == "scripted":
        return ScriptedProvider(queue)
    if kind == "replay":
        if not replay_dir:
            raise ReplayMissing("replay dir required")
        return ReplayProvider(replay_dir)
    return DashScopeProvider(models)
