from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.types import LLMResult
from app.main import create_app
from app.memory.injection import build_memory_slot
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

NOTE_SOURCE = [{"kind": "note", "ref": "ui", "sha": "0" * 64}]


class FakeProvider:
    def __init__(self, parsed=None, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error
        self.calls: list[list[dict]] = []

    async def complete(self, slot, messages, **kwargs):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return LLMResult(text="{}", parsed=self.parsed)

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
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


def _payload(bot_id: str, text: str) -> dict:
    return {"owner_bot_id": bot_id, "visibility": "private", "sources": NOTE_SOURCE, "body": {"text": text}}


@pytest.mark.asyncio
async def test_free_note_becomes_one_paragraph_and_original_is_dropped(tmp_path):
    provider = FakeProvider({"title": "项目角色", "text": "本 Bot 是项目的总负责人。"})
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        res = await client.post(
            "/api/memory/records", json=_payload(bot_id, "你是我们项目的总负责人"), headers={"X-Bot-Id": bot_id}
        )
        assert res.status_code == 201, res.text
        record = res.json()
        assert record["title"] == "项目角色"
        assert record["body"] == {"text": "本 Bot 是项目的总负责人。"}
        assert provider.calls[0][-1]["content"] == "你是我们项目的总负责人"

        slot = await build_memory_slot(
            bot_id, project_id=None, run_id=None, db_path=tmp_path / "test3.db"
        )
        assert slot[0]["body"] == {"text": "本 Bot 是项目的总负责人。"}


@pytest.mark.asyncio
async def test_llm_failure_stores_original_note(tmp_path):
    async with _client(_app(tmp_path, FakeProvider(error=RuntimeError("boom")))) as client:
        bot_id = await _bot(client)
        res = await client.post(
            "/api/memory/records", json=_payload(bot_id, "记得先跑测试"), headers={"X-Bot-Id": bot_id}
        )
        assert res.status_code == 201, res.text
        assert res.json()["body"] == {"text": "记得先跑测试"}


@pytest.mark.asyncio
async def test_invalid_llm_output_stores_original_note(tmp_path):
    async with _client(_app(tmp_path, FakeProvider({"title": "x"}))) as client:
        bot_id = await _bot(client)
        res = await client.post(
            "/api/memory/records", json=_payload(bot_id, "原文"), headers={"X-Bot-Id": bot_id}
        )
        assert res.status_code == 201
        assert res.json()["body"] == {"text": "原文"}


@pytest.mark.asyncio
async def test_secret_note_is_rejected_and_never_sent_to_llm(tmp_path):
    provider = FakeProvider({"text": "x"})
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        res = await client.post(
            "/api/memory/records",
            json=_payload(bot_id, "我的 key 是 sk-ws-ABCDEFG123456"),
            headers={"X-Bot-Id": bot_id},
        )
        assert res.status_code == 400
        assert res.json()["error_category"] == "secret_in_body"
        assert provider.calls == []


@pytest.mark.asyncio
async def test_structured_body_is_not_reorganized(tmp_path):
    provider = FakeProvider({"text": "x"})
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        payload = _payload(bot_id, "t")
        payload["body"] = {"text": "t", "extra": 1}
        res = await client.post("/api/memory/records", json=payload, headers={"X-Bot-Id": bot_id})
        assert res.status_code == 201
        assert provider.calls == []
