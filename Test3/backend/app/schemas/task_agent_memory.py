"""Schemas for task/role scoped manual memory (M subsystem).

Memory is scoped by ``run_id + task_code + role`` where ``role`` is the task
card role ("coder" or "tester"), never a bot assignment.  The view returns the
fully resolved context pieces the API and the runtime integrator need; it does
not expose which bot happens to execute the task.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TaskRole = Literal["coder", "tester"]
TASK_ROLES: tuple[str, ...] = ("coder", "tester")


class TaskRoleSourceRef(BaseModel):
    """One provenance source for the automatic role context block."""

    kind: str
    ref: str
    sha256: str


class TaskRoleSnapshot(BaseModel):
    """Deterministic version marker of the automatic role context."""

    text: str
    sources: list[TaskRoleSourceRef] = Field(default_factory=list)
    matcher_version: str


class TaskRoleMemoryView(BaseModel):
    run_id: str
    project_id: str
    task_code: str
    role: TaskRole
    revision: int = Field(ge=0)
    manual_text: str = ""
    manual_updated_by: str | None = None
    manual_updated_at: str | None = None
    role_snapshot: TaskRoleSnapshot
    # ``ContextSection`` shaped dicts: kind/source_id/source_version/text/
    # sha256/summary.  Kept as dicts so the shared agent-context type does not
    # become a schema dependency of the HTTP layer.
    manual_section: dict[str, Any] | None = None
    role_section: dict[str, Any]
    context_hash: str
    frozen: bool = False
    frozen_context: dict[str, Any] = Field(default_factory=dict)
    effective: Literal["current", "next_attempt"] = "current"


class TaskRoleMemoryUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    manual_text: str


__all__ = [
    "TASK_ROLES",
    "TaskRole",
    "TaskRoleMemoryUpdate",
    "TaskRoleMemoryView",
    "TaskRoleSnapshot",
    "TaskRoleSourceRef",
]