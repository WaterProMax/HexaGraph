from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.settings import load_models  # noqa: E402


async def probe(slot: str, cfg, client) -> dict:
    row = {"slot": slot, "model": cfg.model, "chat": "skip", "json": "skip", "tools": "skip", "embed": "skip", "ms": 0, "tokens": 0}
    if not os.getenv("DASHSCOPE_API_KEY"):
        row["chat"] = "no-key"
        return row
    started = time.perf_counter()
    try:
        if slot == "embedding":
            result = await client.embeddings.create(model=cfg.model, input=["hello"])
            row["embed"] = "ok" if result.data else "fail"
            row["ms"] = int((time.perf_counter() - started) * 1000)
            return row
        chat = await client.chat.completions.create(model=cfg.model, messages=[{"role": "user", "content": "只回答pong"}])
        row["chat"] = "ok" if chat.choices else "fail"
        row["tokens"] = getattr(chat.usage, "total_tokens", 0) or 0
        js = await client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": '输出 JSON {"ok":true}'}],
            response_format={"type": "json_object"} if cfg.json_mode else None,
        )
        text = js.choices[0].message.content or ""
        try:
            json.loads(text)
            row["json"] = "ok"
        except json.JSONDecodeError:
            row["json"] = "fail"
        if cfg.tool_calls:
            tools = [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}]
            tc = await client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "user", "content": "调用 ping"}],
                tools=tools,
            )
            row["tools"] = "ok" if tc.choices[0].message.tool_calls else "prompt-fallback"
    except Exception as exc:  # noqa: BLE001
        row["chat"] = f"error:{exc.__class__.__name__}"
    row["ms"] = int((time.perf_counter() - started) * 1000)
    return row


async def main() -> None:
    models = load_models()
    client = None
    key = os.getenv("DASHSCOPE_API_KEY")
    if key:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=models.base_url, api_key=key)
    print(f"{'slot':<14}{'model':<22}{'chat':<16}{'json':<8}{'tools':<16}{'ms':<8}{'tokens'}")
    for name, cfg in models.slots.items():
        row = await probe(name, cfg, client)
        print(f"{row['slot']:<14}{row['model']:<22}{row['chat']:<16}{row['json']:<8}{row['tools']:<16}{row['ms']:<8}{row['tokens']}")


if __name__ == "__main__":
    asyncio.run(main())
