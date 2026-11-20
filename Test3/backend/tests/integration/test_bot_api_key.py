from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry, _bot_endpoint
from app.llm.bot_secrets import BotSecretStore
from app.llm.catalog import PROVIDER_ENDPOINTS
from app.llm.gateway import Gateway
from app.llm.providers import DashScopeProvider, ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles

SECRET = "sk-test-secret-1234567890"


def _app(tmp_path: Path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider(), data_dir=tmp_path), RoleRegistry(load_roles()), tmp_path
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _body(**overrides) -> dict:
    body = {
        "display_name": "Kimi Bot",
        "role_template": "coder",
        "provider_ref": "moonshot",
        "model": "kimi-k3.1-pro",
        "slot": "coder",
        "secret_ref": "MOONSHOT_API_KEY",
    }
    body.update(overrides)
    return body


def _tree_text(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != "master.key")


@pytest.mark.asyncio
async def test_api_key_is_stored_encrypted_and_never_returned(tmp_path):
    async with _client(_app(tmp_path)) as client:
        created = await client.post("/api/bots", json=_body(api_key=SECRET))
        assert created.status_code == 201
        bot = created.json()
        assert "api_key" not in bot
        assert SECRET not in created.text
        assert SECRET not in (await client.get(f"/api/bots/{bot['bot_id']}")).text
        assert SECRET not in (await client.get("/api/bots")).text

    store = BotSecretStore(tmp_path)
    assert store.get(bot["bot_id"]) == SECRET
    # nothing under the data dir (DB, WAL, json) contains the plaintext key
    assert SECRET.encode() not in _tree_text(tmp_path)
    assert (tmp_path / "secrets" / "master.key").stat().st_mode & 0o777 == 0o600

    con = sqlite3.connect(tmp_path / "test3.db")
    try:
        rows = con.execute("select payload from bots").fetchall()
    finally:
        con.close()
    assert rows and all(SECRET not in str(row[0]) and "api_key" not in str(row[0]) for row in rows)


@pytest.mark.asyncio
async def test_responses_flag_whether_a_key_is_stored_without_exposing_it(tmp_path):
    async with _client(_app(tmp_path)) as client:
        with_key = (await client.post("/api/bots", json=_body(api_key=SECRET))).json()
        without = (await client.post("/api/bots", json=_body(display_name="Plain", provider_ref="dashscope"))).json()
        assert with_key["has_api_key"] is True and without["has_api_key"] is False
        assert (await client.get(f"/api/bots/{with_key['bot_id']}")).json()["has_api_key"] is True
        flags = {i["bot_id"]: i["has_api_key"] for i in (await client.get("/api/bots")).json()["items"]}
        assert flags == {with_key["bot_id"]: True, without["bot_id"]: False}
        patched = (await client.patch(f"/api/bots/{without['bot_id']}", json={"api_key": "sk-late-key-123456"})).json()
        assert patched["has_api_key"] is True
        for response in (await client.get("/api/bots"),):
            assert SECRET not in response.text and "sk-late-key-123456" not in response.text


@pytest.mark.asyncio
async def test_patch_replaces_and_empty_string_removes_key(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot = (await client.post("/api/bots", json=_body(api_key=SECRET))).json()
        patched = await client.patch(f"/api/bots/{bot['bot_id']}", json={"api_key": "sk-new-key-abcdef"})
        assert patched.status_code == 200
        assert "api_key" not in patched.json()
        assert BotSecretStore(tmp_path).get(bot["bot_id"]) == "sk-new-key-abcdef"

        cleared = await client.patch(f"/api/bots/{bot['bot_id']}", json={"api_key": ""})
        assert cleared.status_code == 200
        assert BotSecretStore(tmp_path).get(bot["bot_id"]) is None


@pytest.mark.asyncio
async def test_archive_deletes_key_and_unknown_provider_is_rejected(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bad = await client.post("/api/bots", json=_body(provider_ref="nope", api_key=SECRET))
        assert bad.status_code == 400
        bot = (await client.post("/api/bots", json=_body(api_key=SECRET))).json()
        assert BotSecretStore(tmp_path).get(bot["bot_id"]) == SECRET
        assert (await client.post(f"/api/bots/{bot['bot_id']}/archive")).status_code == 200
        assert BotSecretStore(tmp_path).get(bot["bot_id"]) is None


@pytest.mark.asyncio
async def test_bot_without_key_keeps_env_behaviour(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot = (await client.post("/api/bots", json=_body(provider_ref="dashscope"))).json()
    gateway = SimpleNamespace(data_dir=tmp_path, models=load_models())
    assert _bot_endpoint(gateway, bot["bot_id"], "dashscope") is None


def test_bot_endpoint_uses_provider_base_url(tmp_path):
    BotSecretStore(tmp_path).set("b1", SECRET)
    models = load_models()
    gateway = SimpleNamespace(data_dir=tmp_path, models=models)
    assert _bot_endpoint(gateway, "b1", "moonshot") == {
        "base_url": PROVIDER_ENDPOINTS["moonshot"],
        "api_key": SECRET,
    }
    assert _bot_endpoint(gateway, "b1", "dashscope") == {"base_url": models.base_url, "api_key": SECRET}


@pytest.mark.asyncio
async def test_dashscope_provider_routes_to_bot_endpoint_without_workbench_key(monkeypatch):
    seen: dict = {}

    class _Completions:
        async def create(self, **kwargs):
            seen["kwargs"] = kwargs
            message = SimpleNamespace(content="{}", tool_calls=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                model=kwargs["model"],
            )

    class _Client:
        chat = SimpleNamespace(completions=_Completions())

    models = load_models()
    provider = DashScopeProvider(models)
    monkeypatch.setattr(
        provider, "_bot_client", lambda base_url, api_key: seen.update(base_url=base_url, api_key=api_key) or _Client()
    )
    monkeypatch.setattr(provider, "_client_obj", lambda: pytest.fail("must not use the workbench client"))
    models.slots["coder"].extra_body = {"enable_thinking": False}

    gateway = Gateway(models, provider)
    await gateway.complete(
        "coder",
        [{"role": "user", "content": "hi"}],
        model="kimi-k3.1-pro",
        provider_ref="moonshot",
        endpoint={"base_url": PROVIDER_ENDPOINTS["moonshot"], "api_key": SECRET},
    )
    assert seen["base_url"] == PROVIDER_ENDPOINTS["moonshot"]
    assert seen["api_key"] == SECRET
    assert seen["kwargs"]["model"] == "kimi-k3.1-pro"
    assert "extra_body" not in seen["kwargs"]  # dashscope-only tuning is not forwarded
