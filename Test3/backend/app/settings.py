from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"


class SlotConfig(BaseModel):
    model: str
    temperature: float = 0.3
    max_tokens: int = 4096
    fallback: str = ""
    json_mode: bool = True
    tool_calls: bool = False
    context_window: int = 32768
    price_per_1k_in: float = 0.0
    price_per_1k_out: float = 0.0
    extra_body: dict[str, Any] = Field(default_factory=dict)
    dimensions: int | None = None


class ModelsFile(BaseModel):
    provider: str
    base_url: str
    api_key_env: str
    limits: dict[str, Any]
    slots: dict[str, SlotConfig]


class RoleConfig(BaseModel):
    slot: str
    temperature: float = 0.2
    prompt: str
    output_schema: str
    visible: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class RolesFile(BaseModel):
    visible_types: list[str]
    roles: dict[str, RoleConfig]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    dashscope_api_key: str = ""
    # 本机 shell 常导出 all_proxy=http(s):// 或 socks5h://；httpx 默认读取这些变量，
    # 未安装 socksio 时会在建连接前直接报 ImportError。本地工作台默认直连，
    # 确需走代理时在 .env 设 TEST3_HTTP_TRUST_ENV=1。
    test3_http_trust_env: bool = False
    feedback_hash_key: str = ""
    test3_data_dir: str = ""
    test3_llm_provider: str = "scripted"
    test3_scripted_fixture: str = "study-room"
    host: str = "127.0.0.1"
    port: int = 8765

    def data_dir(self) -> Path:
        if self.test3_data_dir:
            return Path(self.test3_data_dir)
        return ROOT / "data"


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_models(path: Path | None = None) -> ModelsFile:
    return ModelsFile.model_validate(load_yaml(path or CONFIG_DIR / "models.yaml"))


def load_roles(path: Path | None = None) -> RolesFile:
    return RolesFile.model_validate(load_yaml(path or CONFIG_DIR / "roles.yaml"))


def load_limits(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or CONFIG_DIR / "limits.yaml")


def load_profile(name: str = "python-pytest") -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "profiles" / f"{name}.yaml")


def validate_config(
    models: ModelsFile | None = None,
    roles: RolesFile | None = None,
    prompts_dir: Path | None = None,
) -> None:
    models = models or load_models()
    roles = roles or load_roles()
    prompts_dir = prompts_dir or PROMPTS_DIR
    visible = set(roles.visible_types)
    errors: list[str] = []
    for name, role in roles.roles.items():
        if role.slot not in models.slots:
            errors.append(f"roles.yaml:{name}.slot -> missing slot {role.slot!r}")
        prompt_path = ROOT / role.prompt if not Path(role.prompt).is_absolute() else Path(role.prompt)
        if not prompt_path.exists():
            errors.append(f"roles.yaml:{name}.prompt -> missing file {role.prompt}")
        for item in role.visible:
            if item not in visible:
                errors.append(f"roles.yaml:{name}.visible -> unknown type {item!r}")
    if errors:
        raise ConfigError("config validation failed:\n" + "\n".join(errors))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
