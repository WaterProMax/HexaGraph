"""Generation ids for a run's write path (P5).

A late LLM/tool reply from an older generation must be dropped: it may not
mutate task state or write files.  ``bump`` invalidates every id issued before
it and returns the new current id.  ``new_id`` issues a fresh id without
invalidating siblings, so concurrent tasks inside one schedule loop keep
working.
"""

from __future__ import annotations

import uuid


class GenerationGuard:
    def __init__(self) -> None:
        self._current: dict[str, set[str]] = {}

    def new_id(self, run_id: str) -> str:
        generation_id = uuid.uuid4().hex
        self._current.setdefault(run_id, set()).add(generation_id)
        return generation_id

    def is_current(self, run_id: str, generation_id: str) -> bool:
        return generation_id in self._current.get(run_id, set())

    def bump(self, run_id: str) -> str:
        generation_id = uuid.uuid4().hex
        self._current[run_id] = {generation_id}
        return generation_id

    def current_ids(self, run_id: str) -> set[str]:
        return set(self._current.get(run_id, set()))


__all__ = ["GenerationGuard"]