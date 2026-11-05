from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["产品经理", "用户代表", "付费方代表", "开发", "测试", "主持人"]
ROLE_ALIASES = {"后勤代表": "付费方代表", "主要用户代表": "用户代表"}
DISCUSSION_ROLES: tuple[Role, ...] = ("产品经理", "用户代表", "付费方代表", "开发", "测试")
FIRST_SPEAK_ORDER: tuple[Role, ...] = ("付费方代表", "测试", "用户代表", "产品经理", "开发")
ALL_ROLES: tuple[Role, ...] = DISCUSSION_ROLES + ("主持人",)
QUESTION_CATEGORIES = ("价值", "范围", "可行性", "可测性", "竞争")
ISSUE_CATEGORIES = QUESTION_CATEGORIES + ("其他",)
FIBONACCI = (1, 2, 3, 5, 8, 13, 21)
TASK_POINTS = (1, 2, 3, 5, 8)
PRIORITIES = ("P0", "P1", "P2")


def normalize_role(role: str) -> Role:
    mapped = ROLE_ALIASES.get(role, role)
    if mapped not in ALL_ROLES:
        raise ValueError(f"unknown role: {role}")
    return mapped  # type: ignore[return-value]


class Claim(BaseModel):
    text: str
    kind: Literal["事实", "假设"]


class Target(BaseModel):
    issue: str
    to_role: Role | None = None


class StatusChange(BaseModel):
    from_status: str
    to_status: str
    reason: str


class DataField(BaseModel):
    name: str
    type: str = "string"
    required: bool = True
    description: str = ""


class AcceptanceCheck(BaseModel):
    cmd: list[str]
    pass_criteria: str
    from_criterion: str


class Budget(BaseModel):
    max_tool_steps: int = 30
    max_tokens: int = 1_500_000
    max_seconds: int = 600


class Event(BaseModel):
    seq: int | None = None
    run_id: str
    ts: datetime | None = None
    actor: str = "system"
    kind: str
    subject: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class Gate(BaseModel):
    id: str | None = None
    run_id: str
    kind: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    kind: Literal["command", "review", "merge", "manual"]
    summary: str
    path: str = ""


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    denied: bool = False


class CheckOpinion(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    notes: str = ""


class CheckReport(BaseModel):
    doc_type: str
    passed: bool
    items: list[dict[str, Any]] = Field(default_factory=list)
    human_handled: list[str] = Field(default_factory=list)


class IdeaCheck(BaseModel):
    user: str = ""
    problem: str = ""
    needs_payer: bool = False
    payer: str = ""
    missing: list[str] = Field(default_factory=list)
    ok: bool = False


class IdeaDraft(BaseModel):
    approach: str
    features: list[str] = Field(default_factory=list)

    @field_validator("features")
    @classmethod
    def _cap_features(cls, value: list[str]) -> list[str]:
        if len(value) > 3:
            raise ValueError("core features must be at most 3")
        return value


class ModeratorTurn(BaseModel):
    body: str
    mention: list[Role] = Field(default_factory=list)
    announce_finish: bool = False


class Estimate(BaseModel):
    role: Literal["开发", "测试", "coder", "tester"]
    points: dict[str, int]
    notes: str = ""


class CodeIssue(BaseModel):
    text: str
    blocking: bool = False
    kind: Literal["缺陷", "任务描述问题", "越权"] = "缺陷"


class CodeReview(BaseModel):
    verdict: Literal["pass", "fail"]
    issues: list[CodeIssue] = Field(default_factory=list)


class CoderDone(BaseModel):
    done: bool = True
    summary: str = ""
    files: list[str] = Field(default_factory=list)


class CRScore(BaseModel):
    dimension: Literal["价值", "影响", "风险"]
    score: Literal[1, 2, 3, 4, 5]
    red_line: bool = False
    blocking: bool = False
    reason: str = ""


class FBScore(BaseModel):
    dimension: Literal["价值", "成本", "风险"]
    score: Literal[1, 2, 3, 4, 5]
    red_line: bool = False
    reason: str = ""


class ImpactReport(BaseModel):
    codes: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    stale_tasks: list[str] = Field(default_factory=list)
    pause_tasks: list[str] = Field(default_factory=list)
    points_added: int = 0
    points_removed: int = 0
    points_redo: int = 0


class ImpactSet(ImpactReport):
    upstream: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)


class ImpactNarrative(BaseModel):
    text: str
    codes: list[str] = Field(default_factory=list)


class FeedbackBatch(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
