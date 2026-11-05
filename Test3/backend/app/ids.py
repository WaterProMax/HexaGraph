from __future__ import annotations

import threading
from collections import defaultdict

HYPHEN_KINDS = {"Q", "I", "T", "A", "CR", "FB", "R"}
PLAIN_KINDS = {"F", "N", "M", "C"}
ALL_KINDS = HYPHEN_KINDS | PLAIN_KINDS


class IdAllocator:
    """Per-run strictly increasing codes. Thread-safe for concurrent allocate()."""

    def __init__(self, start: dict[str, int] | None = None) -> None:
        self._seq: dict[str, int] = defaultdict(int)
        if start:
            self._seq.update(start)
        self._lock = threading.Lock()

    def peek(self, kind: str) -> int:
        kind = kind.upper()
        self._check(kind)
        return self._seq[kind]

    def next(self, kind: str) -> str:
        kind = kind.upper()
        self._check(kind)
        with self._lock:
            self._seq[kind] += 1
            n = self._seq[kind]
        return self.format(kind, n)

    def allocate_many(self, kind: str, count: int) -> list[str]:
        return [self.next(kind) for _ in range(count)]

    def set_at_least(self, kind: str, value: int) -> None:
        kind = kind.upper()
        self._check(kind)
        with self._lock:
            if value > self._seq[kind]:
                self._seq[kind] = value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._seq)

    @staticmethod
    def format(kind: str, n: int) -> str:
        kind = kind.upper()
        if kind in HYPHEN_KINDS:
            return f"{kind}-{n:02d}"
        return f"{kind}{n}"

    @staticmethod
    def parse(code: str) -> tuple[str, int]:
        if "-" in code:
            kind, num = code.split("-", 1)
            return kind.upper(), int(num)
        for kind in sorted(PLAIN_KINDS, key=len, reverse=True):
            if code.startswith(kind) and code[len(kind) :].isdigit():
                return kind, int(code[len(kind) :])
        raise ValueError(f"cannot parse code: {code}")

    @staticmethod
    def _check(kind: str) -> None:
        if kind not in ALL_KINDS:
            raise ValueError(f"unknown id kind: {kind}")
