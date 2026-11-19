"""Pydantic models for ExecutionGrant (contracts.md C.4).

``execution_profile`` is a literal: callers can only create ``granted_v1``
grants, and no API accepts a client-supplied downgrade to ``legacy``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExecutionProfile = Literal["legacy", "granted_v1"]
GrantStatus = Literal["active", "stale", "revoked", "consumed"]


class ExecutionGrant(BaseModel):
    grant_id: str
    run_id: str
    execution_profile: Literal["granted_v1"]
    task_codes: list[str]
    approved_baseline_hashes: dict[str, str]
    repo_remote: str
    repo_owner: str
    repo_name: str
    base_branch: str
    feature_branch: str
    allowed_tool_refs: list[str] = Field(default_factory=list)
    status: GrantStatus = "active"
    github_pr_url: str | None = None
    created_at: str


class ExecutionGrantCreate(BaseModel):
    execution_profile: Literal["granted_v1"]
    task_codes: list[str] = Field(min_length=1)
    approved_baseline_hashes: dict[str, str]
    repo_remote: str
    repo_owner: str
    repo_name: str
    base_branch: str
    feature_branch: str
    allowed_tool_refs: list[str] = Field(default_factory=list)


__all__ = ["ExecutionGrant", "ExecutionGrantCreate", "ExecutionProfile", "GrantStatus"]