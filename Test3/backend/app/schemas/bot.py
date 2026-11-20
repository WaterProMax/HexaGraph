from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BotStatus = Literal["active", "archived"]


class BotSkillBinding(BaseModel):
    skill_id: str
    pinned_version: str


class BotInstance(BaseModel):
    bot_id: str
    display_name: str
    role_template: str
    provider_ref: str
    model: str
    slot: str
    secret_ref: str
    tool_policy: list[str]
    skill_bindings: list[BotSkillBinding]
    token_budget: int | None = Field(default=40_000)
    status: BotStatus = "active"


class BotCreate(BaseModel):
    display_name: str
    role_template: str
    provider_ref: str
    model: str
    slot: str
    secret_ref: str
    tool_policy: list[str] = Field(default_factory=list)
    skill_bindings: list[BotSkillBinding] = Field(default_factory=list)
    token_budget: int | None = 40_000


class BotPatch(BaseModel):
    display_name: str | None = None
    provider_ref: str | None = None
    model: str | None = None
    slot: str | None = None
    secret_ref: str | None = None
    tool_policy: list[str] | None = None
    skill_bindings: list[BotSkillBinding] | None = None
    token_budget: int | None = None
    # role_template / status / bot_id are intentionally absent; archiving has
    # its own endpoint and identity fields are server-owned.


__all__ = [
    "BotCreate",
    "BotInstance",
    "BotPatch",
    "BotSkillBinding",
    "BotStatus",
]