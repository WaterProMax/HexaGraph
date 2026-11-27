from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.types import LLMResult
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


class FakeProvider:
    def __init__(self, text: str = "你好，我是 Water。", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[list[dict], dict]] = []

    async def complete(self, slot, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return LLMResult(text=self.text, model=kwargs.get("model", ""))

    async def embed(self, texts):
        return [[0.0] for _ in texts]


def _app(tmp_path, provider):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), provider, data_dir=tmp_path), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


async def _bot(client: AsyncClient) -> str:
    res = await client.post(
        "/api/bots",
        json={
            "display_name": "Water",
            "role_template": "coder",
            "provider_ref": "dashscope",
            "model": "qwen3.8-max-0902",
            "slot": "flagship",
            "secret_ref": "DASHSCOPE_API_KEY",
            "api_key": "sk-test-key",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


def _chat(content: str = "你是谁？") -> dict:
    return {"messages": [{"role": "user", "content": content}]}


@pytest.mark.asyncio
async def test_chat_returns_reply_in_plain_text_mode(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        res = await client.post(f"/api/bots/{bot_id}/chat", json=_chat())
        assert res.status_code == 200, res.text
        assert res.json() == {"reply": "你好，我是 Water。", "model": "qwen3.8-max-0902"}
        messages, kwargs = provider.calls[0]
        assert kwargs["json_mode"] is False
        assert messages[0]["role"] == "system" and "Water" in messages[0]["content"]
        assert messages[-1] == {"role": "user", "content": "你是谁？"}


@pytest.mark.asyncio
async def test_chat_history_and_private_memory_reach_the_model(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        mem = await client.post(
            "/api/memory/records",
            json={
                "owner_bot_id": bot_id,
                "visibility": "private",
                "sources": [{"kind": "agent", "ref": "t", "sha": "0" * 64}],
                "body": {"text": "项目负责人是小王", "extra": 1},
                "title": "负责人",
            },
            headers={"X-Bot-Id": bot_id},
        )
        assert mem.status_code == 201, mem.text
        history = {
            "messages": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！"},
                {"role": "user", "content": "谁是负责人？"},
            ]
        }
        res = await client.post(f"/api/bots/{bot_id}/chat", json=history)
        assert res.status_code == 200, res.text
        messages, _ = provider.calls[0]
        assert "项目负责人是小王" in messages[0]["content"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_chat_rejects_bad_input(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        url = f"/api/bots/{bot_id}/chat"
        assert (await client.post(url, json={"messages": []})).status_code == 400
        ends_with_bot = {"messages": [{"role": "assistant", "content": "hi"}]}
        assert (await client.post(url, json=ends_with_bot)).status_code == 400
        blank = await client.post(url, json=_chat("   "))
        assert blank.status_code == 400
        secret = await client.post(url, json=_chat("my key sk-ws-ABCDEFG123456"))
        assert secret.status_code == 400 and secret.json()["error_category"] == "secret_in_body"
        assert (await client.post("/api/bots/nope/chat", json=_chat())).status_code == 404
        assert provider.calls == []


@pytest.mark.asyncio
async def test_archived_bot_cannot_chat(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        archived = await client.post(f"/api/bots/{bot_id}/archive")
        assert archived.status_code == 200, archived.text
        res = await client.post(f"/api/bots/{bot_id}/chat", json=_chat())
        assert res.status_code == 409 and res.json()["error_category"] == "bot_archived"
        assert provider.calls == []


@pytest.mark.asyncio
async def test_model_failure_is_a_controlled_502(tmp_path):
    async with _client(_app(tmp_path, FakeProvider(error=RuntimeError("secret upstream detail")))) as client:
        bot_id = await _bot(client)
        res = await client.post(f"/api/bots/{bot_id}/chat", json=_chat())
        assert res.status_code == 502
        assert "secret upstream detail" not in res.text
