from __future__ import annotations

from typing import Any


def tokens_budget(points: int, tokens_per_point: int = 1_500_000) -> int:
    return points * tokens_per_point


def check_budget(
    used: int,
    limit: int,
    *,
    warn_ratio: float = 0.8,
) -> dict[str, Any]:
    if limit <= 0:
        return {"ok": True, "warn": False, "exceeded": False, "ratio": 0.0}
    ratio = used / limit
    return {
        "ok": used < limit,
        "warn": ratio >= warn_ratio,
        "exceeded": used >= limit,
        "ratio": ratio,
    }
