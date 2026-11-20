from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

MemoryVisibility = Literal["private", "project", "run"]
MemoryStatus = Literal["pending", "published", "superseded"]


class MemorySource(BaseModel):
    kind: str
    ref: str
    sha: str


def _validate_scope(visibility: str, project_id: str | None, run_id: str | None) -> None:
    if visibility == "private":
        if project_id is not None or run_id is not None:
            raise ValueError("private memory must not set project_id or run_id")
    elif visibility == "project":
        if not project_id:
            raise ValueError("project memory requires project_id")
    elif visibility == "run":
        if not run_id:
            raise ValueError("run memory requires run_id")


class MemoryRecord(BaseModel):
    mem_id: str
    owner_bot_id: str
    project_id: str | None
    visibility: MemoryVisibility
    version: int
    status: MemoryStatus
    sources: list[MemorySource]
    body: dict
    title: str = ""
    run_id: str | None = None
    # 契约扩展（P3-report 登记）：publish 记录人工晋升者/时间
    promoted_by: str | None = None
    promoted_at: str | None = None

    @model_validator(mode="after")
    def _check_scope(self) -> "MemoryRecord":
        _validate_scope(self.visibility, self.project_id, self.run_id)
        return self


class MemoryCreate(BaseModel):
    owner_bot_id: str
    project_id: str | None = None
    visibility: MemoryVisibility
    sources: list[MemorySource]
    body: dict
    title: str = ""
    run_id: str | None = None

    @model_validator(mode="after")
    def _check_scope(self) -> "MemoryCreate":
        _validate_scope(self.visibility, self.project_id, self.run_id)
        return self


__all__ = [
    "MemoryCreate",
    "MemoryRecord",
    "MemorySource",
    "MemoryStatus",
    "MemoryVisibility",
]