from __future__ import annotations

import os

import pytest

from app.llm.providers import DashScopeProvider
from app.settings import get_settings, load_models

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_dashscope_json_once() -> None:
    if not (os.getenv("DASHSCOPE_API_KEY") or get_settings().dashscope_api_key):
        pytest.skip("DASHSCOPE_API_KEY not set")
    provider = DashScopeProvider(load_models())
    result = await provider.complete(
        "fast",
        [{"role": "user", "content": '只输出 JSON：{"ok": true}'}],
    )
    assert result.text
