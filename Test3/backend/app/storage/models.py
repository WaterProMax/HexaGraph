from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
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
