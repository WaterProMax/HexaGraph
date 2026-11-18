from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResult:
    text: str = ""
    parsed: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""
    finish_reason: str = ""
    raw: Any = None


class LLMProvider(Protocol):
    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
