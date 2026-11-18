"""Structured LLM / design-import error categories. No secrets in user-facing text."""

from __future__ import annotations

import asyncio

import pytest

from app.errors import AgentOutputError, classify_llm_error, user_message_for_category
from app.llm.gateway import Gateway
from app.llm.providers import DashScopeProvider, ScriptedProvider
from app.llm.types import LLMResult
from app.settings import load_models


class HttpStatusError(Exception):
    def __init__(self, status: int, text: str = "") -> None:
        self.status_code = status
        super().__init__(text or f"status {status}")


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (ConnectionError("Connection refused"), "connection"),
        (ConnectionResetError("peer closed"), "connection"),
        (HttpStatusError(401, "Authorization: Bearer sk-secret-key"), "auth"),
        (HttpStatusError(403, "forbidden"), "auth"),
        (ValueError("DASHSCOPE_API_KEY is not configured. Cannot initialize DashScope client."), "auth"),
        (HttpStatusError(429, "rate limit"), "rate_limit"),
        (TimeoutError("timed out"), "timeout"),
        (asyncio.TimeoutError(), "timeout"),
        (AgentOutputError("spec_importer output invalid after retry: field required", category="invalid_structure"), "invalid_structure"),
        (ImportError("Using SOCKS proxy, but the 'socksio' package is not installed."), "environment"),
    ],
)
def test_classify_llm_error_maps_categories(exc: BaseException, category: str) -> None:
    assert classify_llm_error(exc) == category


def test_unclassified_agent_output_is_not_invalid_structure() -> None:
    assert classify_llm_error(AgentOutputError("模型调用失败")) is None


def test_user_messages_match_ui_titles_and_exclude_secrets() -> None:
    expected = {
        "connection": "无法连接模型服务，未完成整理",
        "auth": "模型配置或凭据不可用",
        "rate_limit": "模型服务繁忙或请求受限",
        "timeout": "整理超过 10 分钟，未进入设计确认",
        "missing_fields": "文档缺项",
        "invalid_structure": "模型输出未通过结构校验",
        "environment": "本地运行环境错误，未完成整理",
    }
    for category, title in expected.items():
        message = user_message_for_category(category)
        assert message == title
        blob = message.lower()
        assert "sk-" not in blob
        assert "authorization" not in blob
        assert "traceback" not in blob
        assert "exception" not in blob


@pytest.mark.asyncio
async def test_gateway_auth_failure_is_classified_without_secret_dump() -> None:
    class Always(ScriptedProvider):
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise HttpStatusError(401, "Authorization: Bearer sk-secret-key /etc/passwd")

    gw = Gateway(load_models(), Always())
    with pytest.raises(AgentOutputError) as caught:
        await gw.complete("fast", [{"role": "user", "content": "hi"}])
    err = caught.value
    assert err.category == "auth"
    blob = str(err).lower()
    assert "sk-secret" not in blob
    assert "authorization" not in blob
    assert "/etc/passwd" not in blob
    assert "traceback" not in blob


@pytest.mark.asyncio
async def test_gateway_rate_limit_after_retries_keeps_category() -> None:
    class Always(ScriptedProvider):
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise HttpStatusError(429, "Too Many Requests")

    gw = Gateway(load_models(), Always())
    with pytest.raises(AgentOutputError) as caught:
        await gw.complete("fast", [{"role": "user", "content": "hi"}])
    assert caught.value.category == "rate_limit"
    assert "too many requests" not in str(caught.value).lower()


@pytest.mark.asyncio
async def test_gateway_connection_failure_keeps_category() -> None:
    class Always(ScriptedProvider):
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise ConnectionError("Connection refused to api.example")

    gw = Gateway(load_models(), Always())
    with pytest.raises(AgentOutputError) as caught:
        await gw.complete("fast", [{"role": "user", "content": "hi"}])
    assert caught.value.category == "connection"
    assert "api.example" not in str(caught.value)


def test_dashscope_missing_key_classifies_as_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "dashscope_api_key", "")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = DashScopeProvider(load_models())
    with pytest.raises(Exception) as caught:  # noqa: BLE001
        provider._client_obj()
    assert classify_llm_error(caught.value) == "auth"
    blob = str(caught.value).lower()
    assert "sk-" not in blob
    assert "authorization" not in blob


@pytest.mark.asyncio
async def test_gateway_timeout_keeps_category() -> None:
    class Always(ScriptedProvider):
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise TimeoutError("read timed out")

    gw = Gateway(load_models(), Always())
    with pytest.raises(AgentOutputError) as caught:
        await gw.complete("fast", [{"role": "user", "content": "hi"}])
    assert caught.value.category == "timeout"


@pytest.mark.asyncio
async def test_gateway_fallback_success_is_not_classified_as_failure() -> None:
    class Boom(Exception):
        status_code = 429

    class Flaky(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__([Boom(), LLMResult(text="{}", parsed={"ok": True}, model="x")])

    gw = Gateway(load_models(), Flaky())
    result = await gw.complete("fast", [{"role": "user", "content": "hi"}])
    assert result.parsed == {"ok": True}
