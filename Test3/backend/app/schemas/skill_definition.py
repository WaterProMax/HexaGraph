from __future__ import annotations

from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    skill_id: str
    version: str
    description_md: str
    allowed_tool_refs: list[str]


class SkillCreate(BaseModel):
    skill_id: str
    version: str
    description_md: str
    allowed_tool_refs: list[str]


class ErrorBody(BaseModel):
    error_category: str
    detail: str
    extras: dict = Field(default_factory=dict)


__all__ = ["ErrorBody", "SkillCreate", "SkillDefinition"]