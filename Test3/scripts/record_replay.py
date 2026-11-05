from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy recorded llm calls into a replay folder")
    parser.add_argument("src")
    parser.add_argument("dst")
    args = parser.parse_args()
    src = Path(args.src)
    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(sorted(src.glob("*.json")), start=1):
        data = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(data, ensure_ascii=False)
        if "sk-" in text:
            raise SystemExit(f"refusing to copy {path}: looks like a secret")
        (dst / f"{i:03d}-recorded.json").write_text(text, encoding="utf-8")
    print("copied", i if src.exists() else 0)


if __name__ == "__main__":
    main()
