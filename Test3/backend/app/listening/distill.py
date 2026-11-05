from __future__ import annotations

import re
from typing import Any


def validate_distill(item: dict[str, Any], raw_by_id: dict[int, str]) -> list[str]:
    errors: list[str] = []
    quotes = item.get("quotes") or []
    for qid in quotes:
        if qid not in raw_by_id:
            errors.append(f"引用不存在: {qid}")
    if item.get("count") != len(quotes):
        errors.append("条数与引用不一致")
    summary = item.get("summary") or ""
    blob = " ".join(raw_by_id.get(q, "") for q in quotes)
    for number in re.findall(r"\d+", summary):
        if number not in blob:
            errors.append(f"摘要数字未在原文出现: {number}")
    for quoted in re.findall(r"「([^」]+)」|\"([^\"]+)\"", summary):
        text = quoted[0] or quoted[1]
        if text and text not in blob:
            errors.append(f"摘要引文未在原文出现: {text}")
    return errors
