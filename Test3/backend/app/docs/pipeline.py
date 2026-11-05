from __future__ import annotations

from typing import Any, Callable


async def produce_check_review_gate(
    produce: Callable,
    check: Callable,
    review: Callable | None = None,
) -> dict[str, Any]:
    doc = await produce()
    errors = check(doc)
    sheets = await review() if review else []
    return {"doc": doc, "errors": errors, "reviews": sheets}
