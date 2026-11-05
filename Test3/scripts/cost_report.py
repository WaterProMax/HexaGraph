from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = ROOT / "data"
if not data.exists():
    print("no data/ directory; nothing to report")
    raise SystemExit(0)

totals: dict[str, int] = defaultdict(int)
for path in data.rglob("llm/*.json"):
    payload = json.loads(path.read_text(encoding="utf-8"))
    totals["files"] += 1
    totals["chars"] += len(json.dumps(payload))
print(dict(totals))
