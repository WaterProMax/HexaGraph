from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import (
    PRIORITIES,
    TASK_POINTS,
    AcceptanceCheck,
    Budget,
    Claim,
    CRScore,
    DataField,
    ImpactReport,
    Role,
    StatusChange,
    Target,
)


class Question(BaseModel):
    code: str | None = None
    role: Role
    category: Literal["价值", "范围", "可行性", "可测性", "竞争"]
    text: str
    reason: str


class MergeRow(BaseModel):
    issue: str
    from_questions: list[str]
    proposers: list[Role]
    text: str
    category: str
    deferred: bool = False
    defer_reason: str | None = None


class MergeOutput(BaseModel):
    rows: list[MergeRow]
    notes: str = ""


class Utterance(BaseModel):
    seq: int | None = None
    role: Role
    targets: list[Target] = Field(default_factory=list)
    position: Literal["同意", "反对", "补充", "接受", "不接受", "撤回", "追问", "小结"] = "补充"
    body: str
    reasons: str = ""
    claims: list[Claim] = Field(default_factory=list)
    mention: list[Role] = Field(default_factory=list)
    rule: str = ""


class Issue(BaseModel):
    code: str
    sources: list[str] = Field(default_factory=list)
    proposers: list[Role] = Field(default_factory=list)
    category: Literal["价值", "范围", "可行性", "可测性", "竞争", "其他"] = "其他"
    text: str
    status: Literal["采纳", "撤回", "待定", "未讨论"] = "未讨论"
    conclusion: str = ""
    supporters: list[Role] = Field(default_factory=list)
    opponents: list[Role] = Field(default_factory=list)
    basis: Literal["共识", "事实", "假设（不影响结论）", "待真人验证", "人工裁决"] = "共识"
    destination: Literal["功能", "验收标准", "非功能", "本版不做", "风险与待定", "无"] | list[str] = "无"
    responses: list[int] = Field(default_factory=list)
    stances: list[int] = Field(default_factory=list)
    history: list[StatusChange] = Field(default_factory=list)
    assumption_critical: bool | None = None
    deferred: bool = False


class RoundOutput(BaseModel):
    questions: list[Question] = Field(default_factory=list)
    utterance: Utterance | None = None
    persona: str = ""


class FinalSummary(BaseModel):
    issues: list[Issue]
    notes: str = ""


class IdeaCard(BaseModel):
    raw: str
    user: str = ""
    problem: str = ""
    needs_payer: bool = False
    payer: str = ""
    approach: str = ""
    features: list[str] = Field(default_factory=list)
    supplements: list[str] = Field(default_factory=list)


class ProposalFeature(BaseModel):
    name: str
    sources: list[str]
    points_dev: int = 3
    points_qa: int = 3
    points: int = 3
    disagreed: bool = False


class ProposalRisk(BaseModel):
    code: str
    verification: str
    fallback: str


class ProposalDoc(BaseModel):
    elevator: str
    nabcd: dict[str, str] = Field(default_factory=dict)
    do: list[dict[str, Any]] = Field(default_factory=list)
    dont: list[dict[str, Any]] = Field(default_factory=list)
    implementation: str = ""
    features: list[ProposalFeature] = Field(default_factory=list)
    risks: list[ProposalRisk] = Field(default_factory=list)
    estimate_total: int = 0
    capacity: int = 40
    chapters: list[str] = Field(default_factory=list)


class ReviewOpinion(BaseModel):
    code: str | None = None
    text: str
    kind: Literal["争议类", "方案类", "验证类", "设计类", "需求类"]
    blocking: bool = False


class ReviewSheet(BaseModel):
    reviewer: str
    dimension: str
    score: Literal[1, 2, 3, 4, 5]
    opinions: list[ReviewOpinion] = Field(default_factory=list)


class SpecItem(BaseModel):
    code: str
    kind: Literal["功能", "非功能"]
    title: str
    story: str | None = None
    scenario: str | None = None
    priority: Literal["P0", "P1", "P2"] | None = None
    impact: str | None = None
    acceptance: list[str]
    manual: list[bool] = Field(default_factory=list)
    sources: list[str]
    out_of_scope: bool = False


class SpecDoc(BaseModel):
    users: list[dict[str, Any]] = Field(default_factory=list)
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    features: list[SpecItem] = Field(default_factory=list)
    out_of_scope: list[dict[str, Any]] = Field(default_factory=list)
    nonfunc: list[SpecItem] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    review_followup: list[dict[str, Any]] = Field(default_factory=list)
    chapters: list[str] = Field(default_factory=list)


class Module(BaseModel):
    code: str
    name: str
    responsibility: str
    sources: list[str]
    provides: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)


class Interface(BaseModel):
    code: str
    provider: str
    consumers: list[str]
    inputs: list[DataField] = Field(default_factory=list)
    outputs: list[DataField] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DesignDoc(BaseModel):
    chapters: list[str] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    interfaces: list[Interface] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    contingencies: list[dict[str, Any]] = Field(default_factory=list)
    appendix: str = ""


class TaskCard(BaseModel):
    code: str
    title: str
    kind: Literal["scaffold", "stub", "impl", "test", "integration", "spike", "doc"]
    module: str
    sources: list[str]
    description: str
    inputs: list[str] = Field(default_factory=list)
    write_set: list[str]
    outputs: list[str] = Field(default_factory=list)
    acceptance: list[AcceptanceCheck]
    depends_on: list[str] = Field(default_factory=list)
    points: Literal[1, 2, 3, 5, 8]
    priority: Literal["P0", "P1", "P2"]
    role: Literal["coder", "tester"]
    budget: Budget = Field(default_factory=Budget)

    @field_validator("points")
    @classmethod
    def _points(cls, value: int) -> int:
        if value not in TASK_POINTS:
            raise ValueError("points must be a Fibonacci subset 1|2|3|5|8")
        return value

    @field_validator("priority")
    @classmethod
    def _priority(cls, value: str) -> str:
        if value not in PRIORITIES:
            raise ValueError("priority must be P0-P2")
        return value


class TaskGraph(BaseModel):
    tasks: list[TaskCard]
    notes: str = ""
    capacity: int = 40


class ChangeRequest(BaseModel):
    code: str
    source: str
    description: str
    level: Literal["澄清", "小变更", "大变更"] | None = None
    impact: ImpactReport | None = None
    scores: list[CRScore] = Field(default_factory=list)
    decision: Literal["批准", "拒绝", "暂缓", "需要讨论"] | None = None
    decision_note: str | None = None
    kind: str = ""
    add_or_remove_feature: bool = False
    changes_p0: bool = False
    overturns_issue: bool = False


class RawFeedback(BaseModel):
    id: int | None = None
    source: str = "manual"
    ts: str = ""
    text: str
    text_masked: str = ""
    author: str = ""
    author_hash: str = ""
    link: str = ""


class FeedbackItem(BaseModel):
    code: str | None = None
    category: Literal["缺陷", "新需求", "体验问题", "咨询", "噪声"]
    summary: str
    quotes: list[int]
    count: int
    basis: Literal["用户原话", "归纳"]
    scope: list[str] = Field(default_factory=list)
    status: str = "new"
    route: str = ""
    linked_issue: str = ""
    red_line: bool = False


class AcceptanceItem(BaseModel):
    code: str
    kind: Literal["功能", "非功能"]
    priority: str | None = None
    result: Literal["通过", "未通过", "未验证"]
    evidence_path: str = ""
    manual: bool = False
    tasks: list[str] = Field(default_factory=list)
    reason: str = ""


class ClusterBatch(BaseModel):
    groups: list[list[int]] = Field(default_factory=list)


class AcceptanceReport(BaseModel):
    features: list[AcceptanceItem] = Field(default_factory=list)
    nonfunc: list[AcceptanceItem] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    leftovers: list[str] = Field(default_factory=list)
    matrix: list[dict[str, Any]] = Field(default_factory=list)
    cost: dict[str, Any] = Field(default_factory=dict)
    manual_passes: list[str] = Field(default_factory=list)
