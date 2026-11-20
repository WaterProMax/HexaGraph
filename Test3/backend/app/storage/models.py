from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "project"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    profile: Mapped[str] = mapped_column(String, default="python-pytest")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RunRow(Base):
    __tablename__ = "run"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"))
    status: Mapped[str] = mapped_column(String, default="active")
    current_stage: Mapped[str] = mapped_column(String, default="0")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    limits_json: Mapped[str] = mapped_column(Text, default="{}")
    idea: Mapped[str] = mapped_column(Text, default="")
    paused: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StageRunRow(Base):
    __tablename__ = "stage_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    stage: Mapped[str] = mapped_column(String)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="running")
    reason: Mapped[str] = mapped_column(Text, default="")


class ArtifactRow(Base):
    __tablename__ = "artifact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    type: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    parent_version: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    content_json: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str] = mapped_column(String, default="system")


class BaselineRow(Base):
    __tablename__ = "baseline"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    artifact_id: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class GateRow(Base):
    __tablename__ = "gate"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class DiscussionMsgRow(Base):
    __tablename__ = "discussion_msg"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    round: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="utterance")
    body: Mapped[str] = mapped_column(Text)
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    rule: Mapped[str] = mapped_column(String, default="")


class IssueRow(Base):
    __tablename__ = "issue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


class SpecItemRow(Base):
    __tablename__ = "spec_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


class ModuleRow(Base):
    __tablename__ = "module"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


class InterfaceRow(Base):
    __tablename__ = "interface"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


class TaskRow(Base):
    __tablename__ = "task"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    card_json: Mapped[str] = mapped_column(Text)
    depends_json: Mapped[str] = mapped_column(Text, default="[]")
    write_set_json: Mapped[str] = mapped_column(Text, default="[]")
    points: Mapped[int] = mapped_column(Integer, default=1)
    locked_by: Mapped[str] = mapped_column(String, default="")
    paused: Mapped[int] = mapped_column(Integer, default=0)
    plan_version: Mapped[str] = mapped_column(String, default="1.0")


class AttemptRow(Base):
    __tablename__ = "attempt"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"))
    code: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    outcome: Mapped[str] = mapped_column(String, default="")
    failure_signature: Mapped[str] = mapped_column(String, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    workspace_ref: Mapped[str] = mapped_column(String, default="")
    commit_sha: Mapped[str] = mapped_column(String, default="")


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(String, default="")


class LlmCallRow(Base):
    __tablename__ = "llm_call"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, default="")
    attempt_id: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String, default="")
    slot: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(default=0.0)
    request_path: Mapped[str] = mapped_column(String, default="")
    response_path: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="ok")


class TraceLinkRow(Base):
    __tablename__ = "trace_link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    from_code: Mapped[str] = mapped_column(String)
    to_code: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, default="1.0")


class ChangeRequestRow(Base):
    __tablename__ = "change_request"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="submitted")


class RawFeedbackRow(Base):
    __tablename__ = "raw_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    batch_id: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="manual")
    ts: Mapped[str] = mapped_column(String, default="")
    text_masked: Mapped[str] = mapped_column(Text)
    author_hash: Mapped[str] = mapped_column(String, default="")


class FeedbackItemRow(Base):
    __tablename__ = "feedback_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    code: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="new")


class EventRow(Base):
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actor: Mapped[str] = mapped_column(String, default="system")
    kind: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ExecutionGrantRow(Base):
    """SQLite authority for the P1 grant domain (contracts.md C.6)."""

    __tablename__ = "execution_grants"
    __table_args__ = (Index("ix_execution_grants_run", "run_id"),)

    grant_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    payload: Mapped[str] = mapped_column(Text)


class SkillDefinitionRow(Base):
    """Immutable versioned skill definition keyed by (skill_id, version)."""

    __tablename__ = "skill_definitions"

    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class BotRow(Base):
    """Current bot payload; history lives in ``bot_pin_revisions``."""

    __tablename__ = "bots"

    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


Index("uq_bots_display_name_ci", func.lower(BotRow.display_name), unique=True)


class BotPinRevisionRow(Base):
    __tablename__ = "bot_pin_revisions"

    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    provider_ref: Mapped[str] = mapped_column(String, nullable=False)
    skill_bindings: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class ProjectMembershipRow(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        Index(
            "uq_project_one_leader",
            "project_id",
            unique=True,
            sqlite_where=text("is_leader = 1"),
        ),
    )

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.bot_id"), primary_key=True)
    role_in_project: Mapped[str] = mapped_column(String, nullable=False)
    is_leader: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class RunBotPinSnapshotRow(Base):
    """Run-scoped frozen bot pin; immutable once written."""

    __tablename__ = "run_bot_pin_snapshots"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class MemoryRecordRow(Base):
    """Versioned memory payload; old bodies are protected by a SQLite trigger."""

    __tablename__ = "memory_records"
    __table_args__ = (Index("ix_memory_owner", "owner_bot_id", "visibility"),)

    mem_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_bot_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class DiscussionSessionRow(Base):
    __tablename__ = "discussion_sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class DiscussionProposalRow(Base):
    __tablename__ = "discussion_proposals"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "author_bot_id",
            "round",
            name="uq_discussion_proposals_author_round",
        ),
    )

    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    author_bot_id: Mapped[str] = mapped_column(String, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    sealed: Mapped[int] = mapped_column(Integer, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)


class DiscussionReviewRow(Base):
    __tablename__ = "discussion_reviews"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "reviewer_bot_id",
            "proposal_id",
            name="uq_discussion_reviews_reviewer_proposal",
        ),
    )

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    reviewer_bot_id: Mapped[str] = mapped_column(String, nullable=False)
    proposal_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class ModuleAcceptanceRow(Base):
    """Human module acceptance (P5, contracts C.6)."""

    __tablename__ = "module_acceptances"

    acceptance_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    module_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class DefectRow(Base):
    """Defect flowing back from a module acceptance (P5, contracts C.6)."""

    __tablename__ = "defects"

    defect_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    task_code: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class RunExecutionStateRow(Base):
    """SQLite authority for a run's execution profile and approved hashes.

    Runs are still restored from JSON snapshots for legacy compatibility, but the
    execution profile / baseline hashes for granted runs must come from this
    table.  A missing row is *unspecified*, never an implicit legacy downgrade.
    """

    __tablename__ = "run_execution_state"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_profile: Mapped[str] = mapped_column(String, nullable=False)
    approved_baseline_hashes: Mapped[str] = mapped_column(Text, default="{}")
    approved_plan_hash: Mapped[str] = mapped_column(String, default="")
    allowed_tool_refs: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
