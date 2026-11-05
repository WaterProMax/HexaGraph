from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Protocol

from app.schemas.docs import RawFeedback


class Collector(Protocol):
    def fetch(self) -> list[RawFeedback]: ...


class ManualCollector:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []

    def fetch(self) -> list[RawFeedback]:
        return [RawFeedback.model_validate(row) if not isinstance(row, RawFeedback) else row for row in self.rows]

    @staticmethod
    def from_file(path: Path) -> "ManualCollector":
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get("rows", [])
        elif path.suffix == ".csv":
            rows = list(csv.DictReader(text.splitlines()))
        else:
            rows = [{"text": line, "author": "anon"} for line in text.splitlines() if line.strip()]
        return ManualCollector(rows)
