from __future__ import annotations

from typing import Any


def judge_output(exit_code: int, output: str, patterns: dict[str, list[str]] | None = None) -> dict[str, Any]:
    patterns = patterns or {
        "empty": ["no tests ran", "collected 0 items", "no tests collected"],
        "skip": ["skipped", "Skip"],
    }
    low = output.lower()
    empty = any(p.lower() in low for p in patterns["empty"])
    skip_all = any(p.lower() in low for p in patterns["skip"]) and ("passed" not in low)
    passed = exit_code == 0 and not empty and not skip_all
    return {
        "passed": passed,
        "zero_tests": empty,
        "all_skipped": skip_all and not empty,
        "exit_code": exit_code,
    }


def context_pack(task: dict[str, Any], interfaces: list[dict[str, Any]], deps: list[dict[str, Any]], *, limit: int = 8000) -> dict[str, Any]:
    packed = {"task_card": task, "interfaces": interfaces, "dependency_outputs": deps}
    # never include transcript
    text = str(packed)
    if len(text) > limit:
        packed["truncated"] = True
        packed["dependency_outputs"] = deps[:1]
    return packed
