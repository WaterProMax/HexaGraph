"""Card 2: a real-mode bot without its own key fails closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import bot_endpoint
from app.errors import AgentOutputError
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.settings import load_models


class _DummyRealProvider:
    def __init__(self) -> None:
        self.calls = []


def _gateway(tmp_path: Path, provider) -> Gateway:
    return Gateway(load_models(), provider, data_dir=tmp_path)


def test_scripted_mode_may_return_none_for_default_key(tmp_path: Path) -> None:
    gateway = _gateway(tmp_path, ScriptedProvider([]))
    assert bot_endpoint(gateway, "bot-missing", "dashscope") is None


def test_real_mode_without_bot_key_is_rejected(tmp_path: Path) -> None:
    gateway = _gateway(tmp_path, _DummyRealProvider())
    with pytest.raises(AgentOutputError) as exc:
        bot_endpoint(gateway, "bot-missing", "dashscope")
    assert exc.value.category == "missing_bot_key"
    assert "key" in str(exc.value).lower()


def test_real_mode_without_data_dir_is_rejected(tmp_path: Path) -> None:
    gateway = Gateway(load_models(), _DummyRealProvider())
    with pytest.raises(AgentOutputError) as exc:
        bot_endpoint(gateway, "bot-missing", "dashscope")
    assert exc.value.category == "missing_bot_key"