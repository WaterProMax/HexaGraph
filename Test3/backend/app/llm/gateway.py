from __future__ import annotations

import asyncio
import json
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.errors import ConfigError, ReplayMissing, classified_llm_error, classify_llm_error
from app.llm.providers import DashScopeProvider, ReplayProvider, ScriptedProvider
from app.llm.types import LLMResult
from app.settings import ModelsFile, get_settings

USAGE_ACCUMULATOR: ContextVar[dict[str, int] | None] = ContextVar("usage_acc", default=None)


def record_usage(tokens_in: int, tokens_out: int) -> None:
    acc = USAGE_ACCUMULATOR.get()
    if acc is None:
        return
    acc["tokens_in"] = int(acc.get("tokens_in") or 0) + int(tokens_in or 0)
    acc["tokens_out"] = int(acc.get("tokens_out") or 0) + int(tokens_out or 0)


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
        self.last_provider_ref = ""

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider_ref: str | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        async with self.sema:
            while not self.bucket.take():
                await asyncio.sleep(0.01)
            return await self._complete_with_retry(
                slot, messages, model=model, provider_ref=provider_ref, **kwargs
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.provider.embed(texts)

    async def _complete_with_retry(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider_ref: str | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        cfg = self.models.slots[slot]
        last_error: Exception | None = None
        chosen_model = model or cfg.model
        # provider_ref is descriptive here: the concrete provider is constructed
        # once by the caller, and providers never receive an unknown keyword.
        self.last_provider_ref = provider_ref or ""
        for attempt in range(3):
            try:
                result = await self.provider.complete(slot, messages, model=chosen_model, **kwargs)
                self.stats["tokens_in"] += result.tokens_in
                self.stats["tokens_out"] += result.tokens_out
                self.stats["calls"] += 1
                record_usage(result.tokens_in, result.tokens_out)
                self._persist(slot, messages, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not _retryable(exc) or attempt == 2:
                    break
                await asyncio.sleep(0.01 * (2**attempt))
        endpoint = kwargs.get("endpoint")
        # Fallback models belong to the configured provider; a bot on another
        # provider's endpoint must not be silently re-routed to them.
        foreign_endpoint = isinstance(endpoint, dict) and endpoint.get("base_url") != self.models.base_url
        if cfg.fallback and not foreign_endpoint:
            self.stats["fallbacks"] += 1
            self.events.append({"kind": "llm.fallback", "slot": slot, "fallback": cfg.fallback})
            try:
                result = await self.provider.complete(slot, messages, model=cfg.fallback, **kwargs)
                self.stats["tokens_in"] += result.tokens_in
                self.stats["tokens_out"] += result.tokens_out
                self.stats["calls"] += 1
                record_usage(result.tokens_in, result.tokens_out)
                self._persist(slot, messages, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise classified_llm_error(last_error) from last_error

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
    if classify_llm_error(exc) in {"rate_limit", "timeout"}:
        return True
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(current, "status", None)
        if status in {429, 500, 502, 503, 504}:
            return True
        name = type(current).__name__.lower()
        if "timeout" in name or "rate" in name:
            return True
        current = current.__cause__ or current.__context__
    return False


def _redact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings()
    blob = json.dumps(messages, ensure_ascii=False)
    if settings.dashscope_api_key:
        blob = blob.replace(settings.dashscope_api_key, "[REDACTED]")
    return json.loads(blob)


def build_provider(kind: str, models: ModelsFile, replay_dir: Path | None = None, queue: list[Any] | None = None) -> Any:
    """Build one of the supported providers.

    Unknown kinds -- including a persisted/configured ``deepseek`` kind -- must not
    silently fall back to DashScope or scripted. The retired dedicated provider is
    rejected explicitly so a stale setting cannot turn into a real model call.
    """
    if kind == "scripted":
        return ScriptedProvider(queue)
    if kind == "replay":
        if not replay_dir:
            raise ReplayMissing("replay dir required")
        return ReplayProvider(replay_dir)
    if kind == "dashscope":
        return DashScopeProvider(models)
    raise ConfigError(f"unsupported TEST3_LLM_PROVIDER: {kind}")
