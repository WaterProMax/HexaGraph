from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import time
import traceback
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.agents.runtime import RoleRegistry, call_agent, run_tool_agent
from app.change.classify import classify_cr, evaluation_pass
from app.discussion import planning as discussion_planning
from app.discussion.driver import BotFailed
from app.discussion.engine import run_discussion
from app.discussion.models import DiscussionSession
from app.discussion.session_store import DiscussionSessionStore
from app.docs.acceptance import acceptance_pass
from app.docs.checks import (
    check_design,
    check_proposal,
    check_spec,
    check_task_graph,
    review_pass,
    route_design_review,
    route_review,
)
from app.errors import (
    AgentOutputError,
    CommandDenied,
    DeepSeekRetired,
    GrantRejected,
    IllegalTransition,
    ImportInProgress,
    IsolationUnavailable,
    RevisionConflict,
    ValidationFailed,
    classify_llm_error,
    user_message_for_category,
    user_message_for_error,
)
from app.events.bus import BUS, rebuild_task_states
from app.execution.acceptance import (
    DefectCreate,
    DefectRecord,
    ModuleAcceptance,
    ModuleAcceptanceCreate,
    create_defect,
    record_acceptance,
)
from app.execution.baseline import hash_artifact, write_approved_baseline_hash
from app.execution.dag import dag_blocked_tasks, edges_from_tasks
from app.execution.generation import GenerationGuard
from app.execution.grant_policy import grant_stale_reason
from app.execution.grant_refresh import refresh_grant_status
from app.execution.grant_repo import GrantRepo, read_grants_for_run
from app.execution.isolated import WriteSpec, execute_task_granted
from app.execution.isolation import preflight_isolation
from app.execution.run_lock import RunLockRegistry
from app.execution.run_profile import (
    PROFILE_CONFLICT,
    PROFILE_GRANTED,
    PROFILE_LEGACY,
    PROFILE_UNSPECIFIED,
    run_approved_baseline_hashes,
    run_execution_profile,
    set_approved_baseline_hashes,
    store_approved_baseline_hash,
)
from app.execution.run_profile import (
    set_run_execution_profile as _apply_run_execution_profile,
)
from app.execution.run_state_store import (
    RunExecutionState,
    RunExecutionStateRepo,
    read_run_execution_state,
)
from app.execution.tool_policy import authorize_granted_command
from app.ids import IdAllocator
from app.listening.cluster import cluster
from app.listening.distill import validate_distill
from app.listening.known import match_known
from app.listening.mask import hash_author, mask_text
from app.listening.route import route as route_feedback
from app.llm.gateway import USAGE_ACCUMULATOR, Gateway
from app.orchestrator.budget import check_budget, tokens_budget
from app.orchestrator.classify import classify, failure_signature
from app.orchestrator.control import require_control
from app.orchestrator.recovery import recover_tasks
from app.orchestrator.replan import propose_replan
from app.orchestrator.scheduler import select_tasks
from app.orchestrator.states import can_transition
from app.orchestrator.transition import apply_transition, restore_task_state
from app.orchestrator.validator import judge_output
from app.schemas.common import IdeaCheck, IdeaDraft
from app.schemas.design_input import DesignSource
from app.schemas.docs import (
    AcceptanceItem,
    AcceptanceReport,
    DesignDoc,
    IdeaCard,
    Issue,
    ProposalDoc,
    ReviewSheet,
    SpecDoc,
    TaskCard,
    TaskGraph,
)
from app.schemas.execution_grant import ExecutionGrant, ExecutionProfile
from app.services import design_input as design_input_service
from app.services.monitor import build_monitor_snapshot
from app.settings import get_settings, load_limits, load_models, load_profile, load_roles
from app.stage.engine import StageEngine
from app.storage.db import make_engine, session_factory, sqlite_url
from app.storage.migrate import upgrade_database
from app.storage.models import EventRow
from app.tools.sandbox import in_write_set, run_command
from app.tools.taskset import TaskToolset
from app.trace.service import TraceGraph
from app.workspace.gitops import (
    changed_files,
    commit,
    create_worktree,
    dirty_files,
    init_repo_sync,
    merge,
    remove_worktree,
    rollback_merge,
    tag_build,
)


@dataclass
class RunState:
    id: str
    project_id: str
    idea: str
    status: str = "active"
    revision: int = 1
    paused: bool = False
    pending_human: bool = False
    engine: StageEngine = field(default_factory=StageEngine)
    ids: IdAllocator = field(default_factory=IdAllocator)
    artifacts: dict[str, Any] = field(default_factory=dict)
    gates: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    crs: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    raw_feedback: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    trace: TraceGraph = field(default_factory=TraceGraph)
    limits: dict[str, Any] = field(default_factory=dict)
    skip_continue: set[str] = field(default_factory=set)
    # Unknown top-level snapshot keys are kept verbatim so a read-only restore does
    # not silently drop fields written by an older build.
    extra: dict[str, Any] = field(default_factory=dict)
    # SQLite is the authority for these two; artifacts is only a compatibility copy.
    execution_profile: str = ""
    approved_baseline_hashes: dict[str, str] = field(default_factory=dict)


_SNAPSHOT_KINDS = {
    "task.state_changed",
    "gate.created",
    "gate.resolved",
    "baseline.frozen",
    "baseline.hash",
    "execution_profile.changed",
    "stage.started",
    "stage.changed",
    "budget.exceeded",
    "runtime.recovery_failed",
    "design_input.received",
    "design_input.rejected",
    "design_input.needs_input",
    "design_input.accepted",
    "model.stage_started",
    "model.stage_failed",
}

DEFAULT_IMPORT_TIMEOUT_S = 600.0
_GRANT_COMPLETED_STATES = {"done", "skipped", "cancelled"}
UNEXPECTED_IMPORT_FAILURE = "设计规格整理失败（本地异常，详见运行目录 import-error.txt）"


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Workbench:
    def __init__(self, gateway: Gateway, registry: RoleRegistry, data_dir: Path) -> None:
        self.gateway = gateway
        self.registry = registry
        self.data_dir = data_dir
        self.projects: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, RunState] = {}
        self.limits = load_limits()
        self.models = load_models()
        self.roles = load_roles()
        self.profile = load_profile()
        self._loop_task: asyncio.Task[None] | None = None
        self._loop_stop: asyncio.Event | None = None
        self.schedule_interval = 5.0
        self._merge_locks: dict[str, asyncio.Lock] = {}
        self._gate_locks: dict[str, asyncio.Lock] = {}
        self._discussion_plan_locks: dict[str, asyncio.Lock] = {}
        self._run_locks = RunLockRegistry()
        self._generations = GenerationGuard()
        self._import_tasks: dict[str, asyncio.Task[None]] = {}
        self.import_timeout_s = DEFAULT_IMPORT_TIMEOUT_S
        self.clock = time.time
        self.schedule_mode = "manual"
        self.db_path = self.data_dir / "test3.db"
        self._db_engine = None
        self._db_factory = None
        self._db_ready = False
        self._db_lock: asyncio.Lock | None = None
        self._grant_write_lock: asyncio.Lock | None = None
        self._grant_cache: dict[str, list[ExecutionGrant]] = {}
        # Server-owned readiness flag.  It stays false until the isolation
        # backend (F-06) and the unified grant boundary (F-05) are in place; no
        # client input may set it.
        self.execution_safety_ready = False
        self.restore_runs()

    def start_loop(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._loop_stop = asyncio.Event()
        self._loop_task = asyncio.create_task(self._schedule_loop())
        self.schedule_mode = "auto"

    async def stop_loop(self) -> None:
        self.schedule_mode = "manual"
        if self._loop_stop:
            self._loop_stop.set()
        for import_task in list(self._import_tasks.values()):
            import_task.cancel()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, RuntimeError):
                pass
            self._loop_task = None

    async def _schedule_loop(self) -> None:
        stop = self._loop_stop
        while stop and not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.schedule_interval)
                break
            except TimeoutError:
                pass
            for run in list(self.runs.values()):
                if run.paused or run.status in {"done", "terminated"}:
                    continue
                # Retired DeepSeek-only runs stay readable but must never re-enter a model call
                # after a restart, including the first tick after start_loop().
                if self._is_retired_run(run):
                    continue
                if run.artifacts.get("plan") and run.tasks:
                    try:
                        await self.schedule_once(run)
                    except Exception:  # noqa: BLE001
                        continue

    def emit(self, run: RunState, kind: str, subject: str = "", payload: dict[str, Any] | None = None, actor: str = "system") -> None:
        event = {
            "seq": len(run.events) + 1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "subject": subject,
            "payload": payload or {},
            "actor": actor,
        }
        run.events.append(event)
        BUS.emit_sync(run.id, kind, subject, event["payload"], actor, seq=event["seq"])
        self._persist_event(run, event)

    def _persist_event(self, run: RunState, event: dict[str, Any]) -> None:
        folder = self.data_dir / "runs" / run.id
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if event["kind"] in _SNAPSHOT_KINDS or int(event["seq"]) % 20 == 0:
            self._persist_snapshot(run)

    def _persist_snapshot(self, run: RunState) -> None:
        folder = self.data_dir / "runs" / run.id
        payload = self._serialize_run(run)
        payload["events"] = []
        payload["event_seq"] = len(run.events)
        _atomic_write(folder / "snapshot.json", json.dumps(payload, ensure_ascii=False))
        _atomic_write(self.data_dir / "projects.json", json.dumps(self.projects, ensure_ascii=False))

    def _serialize_run(self, run: RunState) -> dict[str, Any]:
        payload = {
            "id": run.id,
            "project_id": run.project_id,
            "idea": run.idea,
            "status": run.status,
            "revision": run.revision,
            "paused": run.paused,
            "pending_human": run.pending_human,
            "tokens_used": run.tokens_used,
            "engine": {
                "current": run.engine.current,
                "returns": run.engine.returns,
                "supplements": run.engine.supplements,
                "fix_cycles": run.engine.fix_cycles,
                "history": run.engine.history,
            },
            "ids": run.ids.snapshot(),
            "artifacts": run.artifacts,
            "gates": run.gates,
            "events": run.events,
            "tasks": run.tasks,
            "crs": run.crs,
            "feedback": run.feedback,
            "raw_feedback": run.raw_feedback,
            "trace": run.trace.links,
            "limits": run.limits,
            "skip_continue": sorted(run.skip_continue),
            "execution_profile": run.execution_profile,
            "approved_baseline_hashes": run.approved_baseline_hashes,
        }
        payload.update(run.extra)
        return payload

    def _deserialize_run(self, data: dict[str, Any]) -> RunState:
        known = {
            "id",
            "project_id",
            "idea",
            "status",
            "revision",
            "paused",
            "pending_human",
            "tokens_used",
            "engine",
            "ids",
            "artifacts",
            "gates",
            "events",
            "tasks",
            "crs",
            "feedback",
            "raw_feedback",
            "trace",
            "limits",
            "skip_continue",
            "execution_profile",
            "approved_baseline_hashes",
        }
        run = RunState(
            id=data["id"],
            project_id=data["project_id"],
            idea=data.get("idea") or "",
            status=data.get("status") or "active",
            revision=int(data.get("revision") or 1),
            paused=bool(data.get("paused")),
            pending_human=bool(data.get("pending_human")),
            tokens_used=int(data.get("tokens_used") or 0),
            artifacts=data.get("artifacts") or {},
            gates=data.get("gates") or [],
            events=data.get("events") or [],
            tasks=data.get("tasks") or {},
            crs=data.get("crs") or [],
            feedback=data.get("feedback") or [],
            raw_feedback=data.get("raw_feedback") or [],
            limits=data.get("limits") or copy.deepcopy(self.limits),
            skip_continue=set(data.get("skip_continue") or []),
            extra={key: value for key, value in data.items() if key not in known},
            execution_profile=str(data.get("execution_profile") or ""),
            approved_baseline_hashes={
                str(key): str(value)
                for key, value in (data.get("approved_baseline_hashes") or {}).items()
            }
            if isinstance(data.get("approved_baseline_hashes"), dict)
            else {},
        )
        engine = data.get("engine") or {}
        run.engine.current = engine.get("current") or "0"
        run.engine.returns = int(engine.get("returns") or 0)
        run.engine.supplements = int(engine.get("supplements") or 0)
        run.engine.fix_cycles = int(engine.get("fix_cycles") or 0)
        run.engine.history = list(engine.get("history") or [])
        run.ids = IdAllocator(data.get("ids") or {})
        run.trace.links = list(data.get("trace") or [])
        if not run.execution_profile:
            raw_profile = run.artifacts.get("execution_profile")
            if raw_profile in (PROFILE_LEGACY, PROFILE_GRANTED):
                run.execution_profile = str(raw_profile)
        if not run.approved_baseline_hashes:
            raw_hashes = run.artifacts.get("approved_baseline_hashes")
            if isinstance(raw_hashes, dict):
                run.approved_baseline_hashes = {str(key): str(value) for key, value in raw_hashes.items()}
        return run

    def restore_runs(self) -> None:
        projects_path = self.data_dir / "projects.json"
        loaded_projects = self._read_json_file(projects_path)
        if isinstance(loaded_projects, dict):
            self.projects.update(loaded_projects)
        elif projects_path.exists():
            self._record_recovery_failure("", "projects_corrupt")
        root = self.data_dir / "runs"
        if not root.exists():
            return
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            snap = run_dir / "snapshot.json"
            events = self._read_jsonl(run_dir / "events.jsonl")
            data = self._read_json_file(snap)
            if data is None:
                self._record_recovery_failure(run_dir.name, "snapshot_corrupt_or_missing")
                if not events and not snap.exists():
                    continue
                data = self._run_skeleton_from_events(run_dir.name, events)
            run = self._deserialize_run(data)
            if events:
                run.events = events
            self._restore_execution_profile(run, data)
            self._ensure_tasks_from_events(run)
            self._rebuild_task_states(run)
            release = run_dir / "release"
            if (
                run.engine.current == "done"
                and run.status == "waiting"
                and any(g.get("kind") == "验收确认" and g.get("status") == "approved" for g in run.gates)
                and (release / "acceptance.json").is_file()
            ):
                run.status = "done"
                run.pending_human = False
                run.artifacts["release_dir"] = str(release)
            repo = run_dir / "repo"
            if (repo / ".git").exists() and run.tasks:
                recover_tasks(run.tasks, repo, lambda code: f"task/{code}")
            self.runs[run.id] = run
            # SQLite is the authority for grants: a fresh process must not keep
            # an empty cache and later re-bind specs with an empty grant_id.
            self._grant_cache[run.id] = read_grants_for_run(self.db_path, run.id)
            self._interrupt_stale_import(run)
            if (run.artifacts.get("model_stage") or {}).get("status") == "running":
                message = "服务重启中断了模型任务分解，未自动生成或执行计划；请人工重试"
                if self._is_retired_run(run):
                    message = "服务重启中断了模型任务分解；该运行使用已下线的 DeepSeek 专用模式，仅支持只读查看，不支持继续调用。"
                run.artifacts["model_stage"]["status"] = "interrupted"
                run.artifacts["model_stage"]["error"] = message
                self._doc_check_failed(run, retry="plan", errors=[message], extra={"error_category": "interrupted"})
            self._persist_snapshot(run)

    def _restore_execution_profile(self, run: RunState, data: dict[str, Any]) -> None:
        """Apply SQLite authority after a snapshot/events restore.

        A corrupt or missing snapshot must never downgrade a granted run to
        legacy.  A missing profile is ``unspecified``; contradictory evidence is
        ``conflict``; both fail closed in scheduling and execution.
        """
        db_state = read_run_execution_state(self.db_path, run.id)
        artifacts = data.get("artifacts") if isinstance(data.get("artifacts"), dict) else {}
        snapshot_profile = str(data.get("execution_profile") or artifacts.get("execution_profile") or "")
        snapshot_hashes = data.get("approved_baseline_hashes") or artifacts.get("approved_baseline_hashes") or {}
        if db_state is not None:
            profile = db_state.execution_profile
            hashes = dict(db_state.approved_baseline_hashes)
            if profile == PROFILE_CONFLICT or snapshot_profile == PROFILE_CONFLICT:
                resolved = PROFILE_CONFLICT
            elif snapshot_profile in (PROFILE_LEGACY, PROFILE_GRANTED) and snapshot_profile != profile:
                resolved = PROFILE_CONFLICT
            elif (
                profile == PROFILE_GRANTED
                and isinstance(snapshot_hashes, dict)
                and snapshot_hashes
                and {str(k): str(v) for k, v in snapshot_hashes.items()} != hashes
            ):
                resolved = PROFILE_CONFLICT
            else:
                resolved = profile
        elif snapshot_profile == PROFILE_GRANTED:
            # Residual JSON cannot make a run granted without the SQLite authority.
            resolved = PROFILE_CONFLICT
            hashes = {}
        elif snapshot_profile == PROFILE_LEGACY:
            resolved = PROFILE_LEGACY
            hashes = {}
        else:
            resolved = PROFILE_UNSPECIFIED
            hashes = {}
        run.execution_profile = resolved
        run.approved_baseline_hashes = hashes if resolved == PROFILE_GRANTED else {}
        if resolved in (PROFILE_LEGACY, PROFILE_GRANTED):
            run.artifacts["execution_profile"] = resolved
            if resolved == PROFILE_GRANTED:
                run.artifacts["approved_baseline_hashes"] = dict(hashes)
        else:
            run.artifacts.pop("execution_profile", None)
            run.artifacts.pop("approved_baseline_hashes", None)

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _record_recovery_failure(self, run_id: str, reason: str) -> None:
        event = {"kind": "runtime.recovery_failed", "run_id": run_id, "reason": reason, "actor": "system"}
        with (self.data_dir / "recovery.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if run_id:
            folder = self.data_dir / "runs" / run_id
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"seq": 0, "kind": "runtime.recovery_failed", "subject": run_id, "payload": {"reason": reason}, "actor": "system"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _run_skeleton_from_events(self, run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        idea = ""
        for event in events:
            if event.get("kind") == "stage.started":
                idea = str((event.get("payload") or {}).get("idea") or "")
                break
        return {
            "id": run_id,
            "project_id": "",
            "idea": idea,
            "events": events,
            "tasks": {},
            "artifacts": {},
            "gates": [],
        }

    def _ensure_tasks_from_events(self, run: RunState) -> None:
        for event in run.events:
            if event.get("kind") != "task.state_changed":
                continue
            payload = event.get("payload") or {}
            code = str(payload.get("code") or event.get("subject") or "")
            if not code or code in run.tasks:
                continue
            run.tasks[code] = {
                "id": f"{run.id}:{code}",
                "code": code,
                "state": "pending",
                "revision": 1,
                "card": {"code": code, "depends_on": [], "write_set": [], "outputs": [], "acceptance": [], "sources": [], "role": "coder", "points": 1, "kind": "impl", "title": code, "description": "", "module": "M1", "priority": "P1"},
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
                "tokens_used": 0,
                "prev_output": "",
                "review_issues": [],
            }

    def _rebuild_task_states(self, run: RunState) -> None:
        if not run.tasks:
            return
        rows = [
            EventRow(
                run_id=run.id,
                seq=int(event.get("seq") or index + 1),
                kind=str(event.get("kind") or ""),
                subject=str(event.get("subject") or ""),
                actor=str(event.get("actor") or "system"),
                payload_json=json.dumps(event.get("payload") or {}, ensure_ascii=False),
            )
            for index, event in enumerate(run.events)
        ]
        rebuilt = rebuild_task_states(rows, {code: "pending" for code in run.tasks})
        for code, state in rebuilt.items():
            if code in run.tasks:
                restore_task_state(run.tasks[code], state)

    def _set_state(
        self,
        run: RunState,
        task: dict[str, Any],
        event: str,
        *,
        reason: str = "",
        extra: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> str:
        prev = task["state"]
        try:
            nxt = apply_transition(task, event, reason=reason, extra=extra)
        except IllegalTransition:
            self.emit(
                run,
                "orchestrator.illegal_transition",
                str(task.get("code") or ""),
                {"from": prev, "event": event, "reason": reason},
                actor,
            )
            raise
        payload = {"code": task["code"], "from": prev, "to": nxt, "event": event, "reason": reason, **(extra or {})}
        self.emit(run, "task.state_changed", task["code"], payload, actor)
        return nxt

    def _merge_lock_for(self, run: RunState) -> asyncio.Lock:
        lock = self._merge_locks.get(run.id)
        if lock is None:
            lock = asyncio.Lock()
            self._merge_locks[run.id] = lock
        return lock

    def _gate_lock_for(self, run: RunState) -> asyncio.Lock:
        lock = self._gate_locks.get(run.id)
        if lock is None:
            lock = asyncio.Lock()
            self._gate_locks[run.id] = lock
        return lock

    def _schedule_lock_for(self, run: RunState) -> asyncio.Lock:
        # P5: scheduling and task writes share one per-run lock.
        return self._run_locks.lock_for(run.id)

    @contextmanager
    def _usage_scope(self, run: RunState, task: dict[str, Any] | None = None):
        acc = {"tokens_in": 0, "tokens_out": 0}
        token = USAGE_ACCUMULATOR.set(acc)
        try:
            yield acc
        finally:
            USAGE_ACCUMULATOR.reset(token)
            self._apply_usage(run, task, acc)

    def _apply_usage(self, run: RunState, task: dict[str, Any] | None, acc: dict[str, int]) -> None:
        delta = int(acc.get("tokens_in") or 0) + int(acc.get("tokens_out") or 0)
        if delta:
            run.tokens_used += delta
            if task is not None:
                task["tokens_used"] = int(task.get("tokens_used") or 0) + delta
        self._drain_gateway(run)
        self._emit_budget(run, task)

    def create_project(self, name: str, profile: str = "python-pytest") -> dict[str, Any]:
        pid = str(uuid.uuid4())
        self.projects[pid] = {"id": pid, "name": name, "profile": profile}
        # Projects without runs (e.g. discussion-only) never reach a run snapshot,
        # so persist the registry here or they vanish on restart.
        _atomic_write(self.data_dir / "projects.json", json.dumps(self.projects, ensure_ascii=False))
        return self.projects[pid]

    def set_project_archived(self, project_id: str, archived: bool) -> dict[str, Any]:
        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        if archived:
            project["archived"] = True
            project["archived_at"] = datetime.now(timezone.utc).isoformat()
        else:
            project.pop("archived", None)
            project.pop("archived_at", None)
        _atomic_write(self.data_dir / "projects.json", json.dumps(self.projects, ensure_ascii=False))
        return project

    def create_run(self, project_id: str, idea: str) -> RunState:
        self._prepare_scripted()
        rid = str(uuid.uuid4())
        run = RunState(id=rid, project_id=project_id, idea=idea, limits=copy.deepcopy(self.limits))
        # New runs are explicitly legacy server-side.  A missing profile is not a
        # legacy default: restored runs without any evidence resolve unspecified.
        run.execution_profile = PROFILE_LEGACY
        self.runs[rid] = run
        run.artifacts["idea_raw"] = idea
        self.emit(run, "stage.started", "0", {"idea": idea})
        return run

    def create_discussion_plan_run(
        self, record: DiscussionSession, output: discussion_planning.LeaderPlan, run_id: str
    ) -> None:
        package = record.decision_package
        assert package is not None
        run = RunState(
            id=run_id, project_id=record.project_id, idea=record.requirement_text,
            limits=copy.deepcopy(self.limits), execution_profile=PROFILE_LEGACY,
        )
        run.engine.current = "6"
        run.artifacts.update(
            idea_raw=record.requirement_text,
            discussion_session_id=record.session_id,
            decision_package=package.model_dump(),
            spec=output.spec.model_dump(),
            design=output.design.model_dump(),
            plan=output.plan.model_dump(),
            plan_errors=[],
            provenance=self._provenance(),
        )
        store_approved_baseline_hash(run, "DecisionPackage", package.sha256)
        store_approved_baseline_hash(run, "SPEC", hash_artifact(run.artifacts["spec"]))
        run.artifacts["baseline_SPEC"] = "1.0"
        self._gate(run, "PLAN基线确认", {"plan": run.artifacts["plan"], "design": run.artifacts["design"]})
        self.runs[run.id] = run

    # --- ExecutionGrant domain (P1) ---------------------------------------------
    async def _ensure_db(self) -> None:
        if self._db_ready:
            return
        if self._db_lock is None:
            self._db_lock = asyncio.Lock()
        async with self._db_lock:
            if self._db_ready:
                return
            # Alembic is the single schema authority.  ``create_all`` is no longer
            # allowed on the production path: it desynchronises alembic_version.
            url = sqlite_url(self.db_path)
            await asyncio.to_thread(upgrade_database, self.db_path)
            engine = make_engine(url)
            self._db_engine = engine
            self._db_factory = session_factory(engine)
            self._db_ready = True
            # Same authority rule for runs restored before the engine existed:
            # re-read every run's grants from SQLite rather than trusting the
            # process-local cache.
            if self.runs:
                async with self._db_factory() as session:
                    repo = GrantRepo(session)
                    for run_id in self.runs:
                        self._grant_cache[run_id] = await repo.list_for_run(run_id)

    @asynccontextmanager
    async def db_session(self):
        await self._ensure_db()
        assert self._db_factory is not None
        async with self._db_factory() as session:
            yield session

    async def close(self) -> None:
        if self._db_engine is not None:
            await self._db_engine.dispose()
            self._db_engine = None
            self._db_factory = None
            self._db_ready = False

    def set_run_execution_profile(self, run_id: str, profile: ExecutionProfile) -> None:
        """Internal/test fixture only; no HTTP route exposes this setter."""
        run = self.runs.get(run_id)
        if run is None:
            raise ValidationFailed("run not found")
        _apply_run_execution_profile(run, profile)

    def set_run_approved_baseline_hashes(self, run_id: str, hashes: dict[str, str]) -> None:
        """Internal/test fixture: mirror a human-approved artifact baseline."""
        run = self.runs.get(run_id)
        if run is None:
            raise ValidationFailed("run not found")
        set_approved_baseline_hashes(run, hashes)

    async def persist_run_execution_state(
        self,
        run_id: str,
        profile: str,
        approved_baseline_hashes: dict[str, str],
        *,
        approved_plan_hash: str = "",
        allowed_tool_refs: list[str] | None = None,
    ) -> None:
        """Persist the authoritative profile/hashes; server-side callers only."""
        run = self.runs.get(run_id)
        if run is None:
            raise ValidationFailed("run not found")
        if profile not in (PROFILE_LEGACY, PROFILE_GRANTED):
            raise ValidationFailed(f"unknown execution profile: {profile}")
        state = RunExecutionState(
            run_id=run_id,
            execution_profile=profile,
            approved_baseline_hashes={str(key): str(value) for key, value in approved_baseline_hashes.items()},
            approved_plan_hash=str(approved_plan_hash or ""),
            allowed_tool_refs=tuple(str(item) for item in (allowed_tool_refs or [])),
        )
        async with self._grant_lock():
            async with self.db_session() as session:
                await RunExecutionStateRepo(session).upsert(state)
                await session.commit()
        run.execution_profile = profile
        set_approved_baseline_hashes(run, state.approved_baseline_hashes)
        run.artifacts["execution_profile"] = profile
        self.emit(
            run,
            "execution_profile.changed",
            run_id,
            {"profile": profile, "hashes": state.approved_baseline_hashes, "plan_hash": state.approved_plan_hash},
        )
        self._attach_granted_specs(run)

    @staticmethod
    def _plan_fingerprint(run: RunState) -> str:
        """Same digest the PLAN gate records as the human-approved baseline.

        Reusing ``hash_artifact`` keeps ``approved_plan_hash`` comparable with
        ``approved_baseline_hashes["PLAN"]``; a separately formatted digest
        would never match.
        """
        plan = run.artifacts.get("plan")
        if not isinstance(plan, dict):
            return ""
        return hash_artifact(plan)

    def _active_grant_for(self, run: RunState, code: str) -> ExecutionGrant | None:
        for grant in reversed(self._grant_cache.get(run.id, [])):
            if grant.status == "active" and code in grant.task_codes:
                return grant
        return None

    async def _authoritative_execution_state(self, run_id: str) -> RunExecutionState | None:
        async with self.db_session() as session:
            return await RunExecutionStateRepo(session).get(run_id)

    def _validated_granted_spec(
        self,
        run: RunState,
        code: str,
        task: dict[str, Any],
        grant: ExecutionGrant,
    ) -> dict[str, Any]:
        """The server-produced spec must belong to this run/task/grant.

        A missing or corrupt spec is an explicit rejection: granted_v1 never
        falls back to the legacy agent, commit or merge path.
        """
        spec = task.get("granted_execution")
        if spec is None:
            raise GrantRejected(
                "granted_spec_missing",
                f"granted_v1 task {code} has no server execution spec",
                status_code=409,
            )
        if not isinstance(spec, dict) or not spec:
            raise GrantRejected(
                "granted_spec_invalid",
                f"granted_v1 task {code} has an invalid execution spec",
                status_code=409,
            )
        if str(spec.get("execution_profile") or "") != PROFILE_GRANTED:
            raise GrantRejected(
                "granted_spec_invalid",
                f"granted_v1 task {code} has an invalid execution spec",
                status_code=409,
            )
        if str(spec.get("task_code") or "") != code:
            raise GrantRejected(
                "grant_binding_mismatch",
                f"execution spec is bound to another task, not {code}",
                status_code=409,
            )
        spec_codes = spec.get("task_codes")
        if not isinstance(spec_codes, list) or code not in {str(item) for item in spec_codes}:
            raise GrantRejected(
                "grant_binding_mismatch",
                f"execution spec does not include task {code}",
                status_code=409,
            )
        if str(spec.get("grant_id") or "") not in {"", grant.grant_id} or grant.run_id != run.id:
            raise GrantRejected(
                "grant_binding_mismatch",
                f"execution spec is not bound to the active grant for {code}",
                status_code=409,
            )
        return spec

    async def _assert_plan_authority(self, run: RunState, spec: dict[str, Any]) -> None:
        """PLAN artifact, approved baselines, spec and SQLite must all agree."""
        plan = run.artifacts.get("plan")
        if not isinstance(plan, dict) or not plan:
            raise GrantRejected(
                "baseline_stale",
                "granted_v1 run has no PLAN artifact",
                status_code=409,
            )
        current = hash_artifact(plan)
        approved = run_approved_baseline_hashes(run)
        if str(approved.get("PLAN") or "") != current:
            raise GrantRejected(
                "baseline_stale",
                "PLAN artifact no longer matches the approved baseline",
                status_code=409,
            )
        materialized = str(run.artifacts.get("plan_materialized") or "")
        if materialized and materialized != current:
            raise GrantRejected(
                "baseline_stale",
                "materialized plan does not match the current PLAN artifact",
                status_code=409,
            )
        if str(spec.get("approved_plan_hash") or "") != current:
            raise GrantRejected(
                "baseline_stale",
                "materialized task spec has a different approved_plan_hash",
                status_code=409,
            )
        spec_hashes = spec.get("approved_baseline_hashes")
        if not isinstance(spec_hashes, dict) or str(spec_hashes.get("PLAN") or "") != current:
            raise GrantRejected(
                "baseline_stale",
                "materialized task spec has a stale PLAN baseline",
                status_code=409,
            )
        state = await self._authoritative_execution_state(run.id)
        if state is None or state.execution_profile != PROFILE_GRANTED:
            raise GrantRejected(
                "profile_unspecified",
                "run has no authoritative granted execution state",
                status_code=409,
            )
        if str(state.approved_plan_hash or "") != current:
            raise GrantRejected(
                "baseline_stale",
                "persisted approved_plan_hash does not match the current PLAN",
                status_code=409,
            )
        if str(state.approved_baseline_hashes.get("PLAN") or "") != current:
            raise GrantRejected(
                "baseline_stale",
                "persisted PLAN baseline does not match the current PLAN",
                status_code=409,
            )

    def _block_unless_isolated(self, run: RunState, task: dict[str, Any], code: str) -> dict[str, Any] | None:
        """F-06: granted execution needs a preflighted isolation backend.

        Returns a BLOCKED result (no state change, no worktree, no process) when
        the probe failed.  Production never reaches this while the safety flag
        is false; tests flip the flag in-process only.
        """
        preflight = preflight_isolation()
        if preflight.available:
            return None
        task["last_error"] = "isolation_preflight_failed"
        self.emit(
            run,
            "task.isolation_blocked",
            code,
            {"reason": preflight.reason, "backend": preflight.backend, "details": preflight.details},
        )
        return {
            "state": task["state"],
            "kind": "BLOCKED",
            "isolation_backend": preflight.backend,
            "reason": preflight.reason,
        }

    async def _authorize_granted_execution(
        self, run: RunState, code: str
    ) -> tuple[ExecutionGrant, dict[str, Any]]:
        """The single gate every real granted execution entry must pass.

        It runs before revision bumps, state transitions, worktrees and
        commands.  There is no fallback to "the latest grant regardless of
        status": revoked/consumed/stale grants and out-of-scope tasks fail
        closed.
        """
        profile = run_execution_profile(run)
        if profile != PROFILE_GRANTED:
            category = "profile_conflict" if profile == PROFILE_CONFLICT else "profile_unspecified"
            raise GrantRejected(category, "run execution profile is not usable", status_code=409)
        task = run.tasks.get(code)
        if task is None:
            raise GrantRejected(
                "grant_binding_mismatch",
                f"task {code} does not belong to run {run.id}",
                status_code=409,
            )
        grants = await self.grants_for_run(run.id)
        if not grants:
            raise GrantRejected(
                "grant_required",
                "granted_v1 run has no execution grant",
                status_code=403,
            )
        active = [
            grant
            for grant in grants
            if grant.status == "active" and grant.run_id == run.id and code in grant.task_codes
        ]
        if not active:
            covering = [
                grant for grant in grants if grant.run_id == run.id and code in grant.task_codes
            ]
            if not covering:
                raise GrantRejected(
                    "scope_mismatch",
                    f"task {code} is outside the approved grant scope",
                    status_code=409,
                )
            latest = covering[-1]
            if latest.status == "stale":
                raise GrantRejected("baseline_stale", "execution grant is stale", status_code=409)
            if latest.status in {"revoked", "consumed"}:
                raise GrantRejected(
                    f"grant_{latest.status}",
                    f"execution grant is {latest.status}",
                    status_code=409,
                )
            raise GrantRejected(
                "grant_not_active",
                f"execution grant is not active (status={latest.status})",
                status_code=409,
            )
        grant = active[-1]
        reason = grant_stale_reason(
            grant,
            approved_baseline_hashes=run_approved_baseline_hashes(run),
            requested_task_codes={code},
        )
        if reason is not None:
            category = "baseline_stale" if reason.startswith("baseline_changed:") else reason
            status_code = 403 if reason == "grant_required" else 409
            raise GrantRejected(category, reason, status_code=status_code)
        spec = self._validated_granted_spec(run, code, task, grant)
        await self._assert_plan_authority(run, spec)
        return grant, spec

    def _granted_spec_for(self, run: RunState, task: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        card = TaskCard.model_validate(task["card"])
        grant = self._active_grant_for(run, str(task["code"]))
        command: list[str] = []
        for check in card.acceptance:
            command = [str(part) for part in check.cmd]
            break
        if not command:
            command = [str(part) for part in (self.profile.get("test_command") or ["python", "-m", "pytest", "-q"])]
        existing = task.get("granted_execution")
        spec: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
        spec.update(
            {
                "execution_profile": PROFILE_GRANTED,
                "approved_plan_hash": fingerprint,
                "approved_baseline_hashes": run_approved_baseline_hashes(run),
                "grant_id": grant.grant_id if grant is not None else "",
                "task_codes": list(grant.task_codes) if grant is not None else [str(task["code"])],
                "task_code": str(task["code"]),
                "write_set": list(card.write_set),
                "command": command,
                "tool_refs": list(grant.allowed_tool_refs) if grant is not None else [],
                "feature_branch": grant.feature_branch if grant is not None else "",
                "source": "server_materialize_tasks",
            }
        )
        spec.setdefault("writes", [])
        return spec

    def _attach_granted_specs(self, run: RunState) -> None:
        """Give every materialized task a server-produced execution spec.

        Legacy / unspecified runs never get one.  Existing writes/commands are
        preserved only as a compatibility detail; hash, scope and tool refs are
        always rebound from the current authoritative state.
        """
        if run_execution_profile(run) != PROFILE_GRANTED:
            for task in run.tasks.values():
                task.pop("granted_execution", None)
            return
        fingerprint = self._plan_fingerprint(run)
        for task in run.tasks.values():
            task["granted_execution"] = self._granted_spec_for(run, task, fingerprint)

    def _bind_grant_to_tasks(self, run: RunState, grant: ExecutionGrant) -> None:
        if run_execution_profile(run) != PROFILE_GRANTED:
            return
        fingerprint = self._plan_fingerprint(run)
        for code in grant.task_codes:
            task = run.tasks.get(code)
            if task is None:
                continue
            spec = self._granted_spec_for(run, task, fingerprint)
            spec.update(
                {
                    "grant_id": grant.grant_id,
                    "task_codes": list(grant.task_codes),
                    "tool_refs": list(grant.allowed_tool_refs),
                    "feature_branch": grant.feature_branch,
                    "approved_baseline_hashes": dict(grant.approved_baseline_hashes),
                }
            )
            task["granted_execution"] = spec

    async def enable_granted_execution(
        self,
        run_id: str,
        approved_baseline_hashes: dict[str, str],
        *,
        approved_plan_hash: str = "",
        allowed_tool_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Server-side enable path used by the HTTP endpoint only.

        A client cannot set ``legacy`` here; the route schema is
        ``Literal["granted_v1"]``.  Enabling does not make execution ready: the
        safety flag remains server-owned and false until F-05/F-06 land.

        The baseline must already exist as a human-approved record: this path
        never lets a caller invent hashes for a run that has none, and the plan
        hash always resolves to the recorded PLAN digest.
        """
        run = self.runs.get(run_id)
        if run is None:
            raise ValidationFailed("run not found")
        hashes = {str(key): str(value) for key, value in (approved_baseline_hashes or {}).items()}
        if not hashes:
            raise ValidationFailed("approved_baseline_hashes is required")
        current = run_approved_baseline_hashes(run)
        if not current:
            raise GrantRejected(
                "baseline_stale",
                "run has no human-approved baseline hashes yet",
                status_code=409,
            )
        if hashes != current:
            raise GrantRejected(
                "baseline_stale",
                "approved_baseline_hashes do not match the run baseline",
                status_code=409,
            )
        approved_plan = str(current.get("PLAN") or "")
        if not approved_plan:
            raise GrantRejected(
                "baseline_stale",
                "run has no human-approved PLAN baseline",
                status_code=409,
            )
        if approved_plan_hash and approved_plan_hash != approved_plan:
            raise ValidationFailed("approved_plan_hash does not match the approved plan")
        resolved_plan_hash = approved_plan
        await self.persist_run_execution_state(
            run_id,
            PROFILE_GRANTED,
            hashes,
            approved_plan_hash=resolved_plan_hash,
            allowed_tool_refs=allowed_tool_refs,
        )
        self._attach_granted_specs(run)
        return {
            "run_id": run_id,
            "execution_profile": PROFILE_GRANTED,
            "approved_baseline_hashes": hashes,
            "approved_plan_hash": resolved_plan_hash,
            "execution_safety_ready": self.execution_safety_ready,
        }

    def _require_execution_authorization(self, run: RunState, action: str) -> None:
        """Unified decision shared by schedule/execute/task control/accept."""
        from app.execution.authorization import decide_execution

        decision = decide_execution(self, run, action)
        if not decision.allowed:
            raise GrantRejected(
                decision.error_category or "execution_not_authorized",
                decision.detail or "execution is not authorized",
                status_code=decision.status_code,
            )

    def _require_execution_safety(self, run: RunState, code: str = "") -> None:
        profile = run_execution_profile(run)
        if profile in (PROFILE_UNSPECIFIED, PROFILE_CONFLICT):
            category = "profile_conflict" if profile == PROFILE_CONFLICT else "profile_unspecified"
            raise GrantRejected(category, "run execution profile is not usable", status_code=409)
        if profile == PROFILE_GRANTED and not self.execution_safety_ready:
            # F-04 stops here on purpose: the legacy worker/auto-merge chain is
            # never reachable until F-05/F-06 install the real boundary.
            raise GrantRejected(
                "execution_safety_not_ready",
                "granted execution isolation and authorization are not ready",
                status_code=409,
            )

    def _grant_lock(self) -> asyncio.Lock:
        if self._grant_write_lock is None:
            self._grant_write_lock = asyncio.Lock()
        return self._grant_write_lock

    async def add_grant(self, grant: ExecutionGrant) -> None:
        async with self._grant_lock():
            async with self.db_session() as session:
                await GrantRepo(session).add(grant)
                await session.commit()
        self._grant_cache.setdefault(grant.run_id, []).append(grant)
        run = self.runs.get(grant.run_id)
        if run is not None:
            self._bind_grant_to_tasks(run, grant)

    def _record_gate_approval(self, run: RunState, gate: dict[str, Any], actor: str) -> None:
        """Append an immutable approval record bound to project/run/session."""
        record = {
            "kind": str(gate.get("kind") or ""),
            "gate_id": str(gate.get("id") or ""),
            "actor": actor,
            "at": str(gate.get("resolved_at") or ""),
            "project_id": run.project_id,
            "run_id": run.id,
            "session_id": run.artifacts.get("discussion_session_id"),
            "approved_baseline_hashes": dict(run_approved_baseline_hashes(run)),
        }
        run.artifacts.setdefault("approvals", []).append(record)

    def _record_approved_baseline(self, run: RunState, key: str, value: Any) -> str:
        digest = write_approved_baseline_hash(run, key, value)
        self.emit(run, "baseline.hash", key, {"key": key, "sha256": digest})
        return digest

    async def _refresh_grant_statuses(self, run: RunState) -> None:
        """Mark only active grants whose baseline hashes actually changed."""
        if run_execution_profile(run) != "granted_v1":
            return
        hashes = run_approved_baseline_hashes(run)
        async with self._grant_lock():
            async with self.db_session() as session:
                repo = GrantRepo(session)
                changed = False
                for grant in await repo.list_for_run(run.id):
                    if grant.status != "active":
                        continue
                    updated = refresh_grant_status(grant, approved_baseline_hashes=hashes)
                    if updated.status != grant.status:
                        await repo.update_status(grant.grant_id, updated.status)
                        changed = True
                # Keep SQLite hashes current: a later restart must not see a false
                # SQLite/snapshot conflict after a human-approved baseline update.
                state_repo = RunExecutionStateRepo(session)
                state = await state_repo.get(run.id)
                if state is not None and state.execution_profile == PROFILE_GRANTED and state.approved_baseline_hashes != hashes:
                    await state_repo.upsert(
                        RunExecutionState(
                            run_id=run.id,
                            execution_profile=PROFILE_GRANTED,
                            approved_baseline_hashes=hashes,
                            approved_plan_hash=state.approved_plan_hash,
                            allowed_tool_refs=state.allowed_tool_refs,
                        )
                    )
                    changed = True
                if changed:
                    await session.commit()
        # A status refresh must keep the in-memory cache identical to SQLite.
        self._grant_cache[run.id] = await self.grants_for_run(run.id)

    async def grants_for_run(self, run_id: str) -> list[ExecutionGrant]:
        async with self.db_session() as session:
            return await GrantRepo(session).list_for_run(run_id)

    # --- Module acceptance / defects (P5) ---------------------------------------
    async def record_module_acceptance(
        self, run: RunState, payload: dict[str, Any], *, actor: str
    ) -> ModuleAcceptance:
        """Persist a human module acceptance; a rejection opens defects.

        This is deliberately a new path: the legacy whole-run ``accept()``,
        force-pass and takeover stay untouched and unavailable for granted runs.
        """
        data = ModuleAcceptanceCreate.model_validate(payload)
        async with self._run_locks.write_scope(run.id):
            async with self.db_session() as session:
                acceptance, defects = await record_acceptance(session, run, data, actor=actor)
                await session.commit()
            if acceptance.status == "rejected":
                for defect in defects:
                    self._mark_task_defect(run, defect.task_code, actor=actor, reason=defect.detail)
        return acceptance

    async def record_defect(self, run: RunState, payload: dict[str, Any], *, actor: str) -> DefectRecord:
        data = DefectCreate.model_validate(payload)
        async with self._run_locks.write_scope(run.id):
            async with self.db_session() as session:
                defect = await create_defect(session, run, data, actor=actor)
                await session.commit()
            self._mark_task_defect(run, defect.task_code, actor=actor, reason=defect.detail)
        return defect

    def _mark_task_defect(self, run: RunState, code: str, *, actor: str, reason: str) -> None:
        task = run.tasks.get(code)
        if task is None:
            return
        if can_transition(task["state"], "defect_found"):
            self._set_state(run, task, "defect_found", reason=reason, actor=actor)
        self._refresh_ready(run)

    @staticmethod
    def _is_retired_run(run: RunState) -> bool:
        """Historical DeepSeek-only runs remain readable but must not call a model again.

        The snapshot mode is left untouched; nothing is rewritten into DashScope/scripted.
        """
        return (run.artifacts.get("provenance") or {}).get("mode") == "deepseek"

    def _reject_retired(self, run: RunState) -> None:
        if self._is_retired_run(run):
            raise DeepSeekRetired()

    def _provenance(self) -> dict[str, Any]:
        """区分“计划/文档由谁生成”和“任务如何执行”，供页面与验收记录使用。"""
        provider = type(self.gateway.provider).__name__
        model = str(self.models.slots["flagship"].model)
        if provider == "ScriptedProvider":
            return {
                "generation": "preset",
                "generation_label": "预置测试输出（scripted）",
                "execution": "simulated",
                "execution_label": "模拟执行（预置工具调用）",
                "provider": provider,
            }
        if provider == "ReplayProvider":
            return {
                "generation": "replay",
                "generation_label": "回放输出（replay）",
                "execution": "simulated",
                "execution_label": "模拟执行（回放工具调用）",
                "provider": provider,
            }
        return {
            "generation": "model",
            "generation_label": f"真实模型生成（{model}）",
            "execution": "real_tool",
            "execution_label": "真实工具执行（模型驱动）",
            "provider": provider,
            "model": model,
        }

    def _gateway_for(self, run: RunState) -> Gateway:
        # Historical ``mode=deepseek`` snapshots are read-only. Never fall back to
        # DashScope or scripted here: the caller asked for a model this build no
        # longer ships, so reject before constructing any client or reading keys.
        self._reject_retired(run)
        return self.gateway

    def _active_import_run(self, project_id: str) -> RunState | None:
        for run in self.runs.values():
            if run.project_id == project_id and run.artifacts.get("design_input_status") == "importing":
                return run
        return None

    def _design_run_result(self, run: RunState, *, meta: Any | None = None, message: str = "") -> dict[str, Any]:
        raw = run.artifacts.get("design_input") or {}
        source = raw.get("source") or {}
        if meta is None:
            input_meta = {
                "kind": source.get("kind") or "text",
                "name": source.get("name") or "",
                "note": source.get("note") or "",
                "bytes": raw.get("bytes") or 0,
                "chars": raw.get("chars") or 0,
                "sha256": raw.get("sha256") or "",
            }
        else:
            input_meta = meta.model_dump() if hasattr(meta, "model_dump") else meta
        pending = next((g for g in run.gates if g.get("status") == "pending"), None)
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "status": run.artifacts.get("design_input_status") or "importing",
            "input": input_meta,
            "spec": run.artifacts.get("spec"),
            "design": run.artifacts.get("design"),
            "missing": list(run.artifacts.get("design_input_missing") or []),
            "errors": list(run.artifacts.get("design_input_errors") or []),
            "error_category": run.artifacts.get("design_input_error_category") or None,
            "checks": run.artifacts.get("design_input_checks") or {},
            "gate": pending,
            "provenance": run.artifacts.get("provenance") or {},
            "message": message or run.artifacts.get("design_input_message") or "",
        }

    def _import_writable(self, run: RunState, generation: int) -> bool:
        if run.status in {"terminated", "done"}:
            return False
        if run.artifacts.get("design_input_status") != "importing":
            return False
        return int(run.artifacts.get("design_input_generation") or 0) == generation

    def _fail_import(self, run: RunState, generation: int, message: str, *, category: str | None = None) -> None:
        if run.artifacts.get("design_input_status") != "importing":
            return
        if int(run.artifacts.get("design_input_generation") or 0) != generation:
            return
        run.artifacts["design_input_generation"] = generation + 1
        run.artifacts["design_input_status"] = "failed"
        run.artifacts["design_input_step"] = ""
        run.artifacts["design_input_message"] = message
        run.artifacts["design_input_errors"] = [message]
        if category:
            run.artifacts["design_input_error_category"] = category
        else:
            run.artifacts.pop("design_input_error_category", None)
        if run.status not in {"terminated", "done"}:
            run.status = "stopped"
        self.emit(run, "design_input.rejected", "", {"reason": message, "error_category": category}, "system")
        self._persist_snapshot(run)

    def _record_import_exception(self, run: RunState, exc: BaseException) -> None:
        """把未预期的整理异常写进运行目录，便于事后定位；不写回界面，避免泄露密钥。"""
        try:
            text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            settings = get_settings()
            for key in (settings.dashscope_api_key, settings.feedback_hash_key):
                if key:
                    text = text.replace(key, "[REDACTED]")
            folder = self.data_dir / "runs" / run.id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "import-error.txt").write_text(text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _interrupt_stale_import(self, run: RunState) -> None:
        if run.artifacts.get("design_input_status") != "importing":
            return
        message = "整理在服务中断后停止，未自动续跑。可以修改后重新提交。"
        run.artifacts["design_input_status"] = "failed"
        run.artifacts["design_input_step"] = ""
        run.artifacts["design_input_message"] = message
        run.artifacts["design_input_errors"] = [message]
        run.artifacts["design_input_generation"] = int(run.artifacts.get("design_input_generation") or 0) + 1
        if run.status not in {"terminated", "done"}:
            run.status = "stopped"

    def _cancel_import_task(self, run_id: str) -> None:
        import_task = self._import_tasks.get(run_id)
        if import_task and not import_task.done():
            import_task.cancel()

    async def wait_design_import(self, run_id: str, timeout: float = 10.0) -> dict[str, Any]:
        import_task = self._import_tasks.get(run_id)
        if import_task is not None:
            await asyncio.wait_for(import_task, timeout=timeout)
        return self._design_run_result(self.runs[run_id])

    async def create_design_run(
        self,
        project_id: str,
        text: str,
        source: DesignSource,
        title: str = "",
        provider: str = "existing",
    ) -> dict[str, Any]:
        """从设计规格原文创建一次运行：尽快返回 run_id，后台整理 SPEC/DESIGN。

        不生成任务、不调度。校验失败时不写“已确认”的 SPEC/DESIGN，也不建关卡。
        """
        # Retired dedicated entry: reject before touching settings, disk, or network.
        if provider == "deepseek":
            raise DeepSeekRetired()
        errors = design_input_service.validate_input(text)
        if errors:
            raise ValidationFailed("；".join(errors))
        active = self._active_import_run(project_id)
        if active:
            raise ImportInProgress("该项目已有正在整理的设计规格，未启动新的导入", run_id=active.id)
        meta = design_input_service.measure_input(text, source)
        budget_error = design_input_service.model_budget_error(meta)
        rid = str(uuid.uuid4())
        run = RunState(
            id=rid,
            project_id=project_id,
            idea=title or source.name or "设计规格导入",
            limits=copy.deepcopy(self.limits),
        )
        # Design-spec runs are ordinary legacy runs until a server-side enable.
        run.execution_profile = PROFILE_LEGACY
        self.runs[rid] = run
        # 整理期间只标记当前阶段；SPEC 的历史推进必须等导入和检查成功。
        run.engine.current = "5"
        started = float(self.clock())
        timeout_s = float(getattr(self, "import_timeout_s", DEFAULT_IMPORT_TIMEOUT_S) or DEFAULT_IMPORT_TIMEOUT_S)
        run.artifacts["design_input"] = {
            "title": title,
            "source": source.model_dump(),
            "bytes": meta.bytes,
            "chars": meta.chars,
            "sha256": meta.sha256,
            "text": text,
        }
        run.artifacts["provenance"] = self._provenance()
        run.artifacts["design_input_status"] = "importing"
        run.artifacts["design_input_step"] = ""
        run.artifacts["design_input_started_at"] = _iso_utc(started)
        run.artifacts["design_input_deadline_at"] = _iso_utc(started + timeout_s)
        run.artifacts["design_input_generation"] = int(run.artifacts.get("design_input_generation") or 0) + 1
        run.artifacts["design_input_message"] = "正在整理设计规格"
        folder = self.data_dir / "runs" / run.id
        _atomic_write(folder / "design-input.txt", text)
        _atomic_write(
            folder / "design-input.json",
            json.dumps(
                {
                    "title": title,
                    "source": source.model_dump(),
                    "bytes": meta.bytes,
                    "chars": meta.chars,
                    "sha256": meta.sha256,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        self.emit(
            run,
            "design_input.received",
            "",
            {"source": source.model_dump(), "chars": meta.chars, "bytes": meta.bytes, "sha256": meta.sha256},
            "owner",
        )
        self._persist_snapshot(run)

        if budget_error:
            run.status = "stopped"
            run.artifacts["design_input_errors"] = [budget_error]
            run.artifacts["design_input_status"] = "needs_split"
            run.artifacts["design_input_message"] = budget_error
            self.emit(run, "design_input.rejected", "", {"reason": budget_error}, "system")
            self._persist_snapshot(run)
            return self._design_run_result(run, meta=meta, message=budget_error)

        generation = int(run.artifacts["design_input_generation"])
        import_task = asyncio.create_task(
            self._run_design_import(run, generation, text, title, source, meta, timeout_s),
            name=f"design-import-{run.id}",
        )
        self._import_tasks[run.id] = import_task
        import_task.add_done_callback(lambda _t, rid=run.id: self._import_tasks.pop(rid, None))
        return self._design_run_result(run, meta=meta, message="正在整理设计规格")

    async def _run_design_import(
        self,
        run: RunState,
        generation: int,
        text: str,
        title: str,
        source: DesignSource,
        meta: Any,
        timeout_s: float,
    ) -> None:
        watchdog = asyncio.create_task(self._import_watchdog(run, generation, timeout_s))
        try:
            await self._import_intakes(run, generation, text, title, source, meta)
        except asyncio.CancelledError:
            self._fail_import(run, generation, "整理已取消。供应商可能仍会计费。")
            raise
        except Exception as exc:  # noqa: BLE001
            category = classify_llm_error(exc)
            message = user_message_for_error(exc) or UNEXPECTED_IMPORT_FAILURE
            if category is None:
                self._record_import_exception(run, exc)
            self._fail_import(run, generation, message, category=category)
        finally:
            if self._import_writable(run, generation):
                self._fail_import(run, generation, "设计规格整理失败")
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog

    async def _import_watchdog(self, run: RunState, generation: int, timeout_s: float) -> None:
        try:
            await asyncio.sleep(max(0.0, timeout_s))
        except asyncio.CancelledError:
            raise
        # Mark terminal first, then cancel the local import task. Provider may still bill.
        self._fail_import(
            run,
            generation,
            "设计规格整理超时。供应商可能仍会计费。",
            category="timeout",
        )
        self._cancel_import_task(run.id)

    async def _import_intakes(
        self,
        run: RunState,
        generation: int,
        text: str,
        title: str,
        source: DesignSource,
        meta: Any,
    ) -> None:
        if not self._import_writable(run, generation):
            return
        run.artifacts["design_input_step"] = "spec"
        self._persist_snapshot(run)
        try:
            with self._usage_scope(run):
                spec_intake = await design_input_service.intake_spec(
                    text, title, source, meta, gateway=self._gateway_for(run), registry=self.registry
                )
                if not self._import_writable(run, generation):
                    return
                run.artifacts["design_input_step"] = "design"
                self._persist_snapshot(run)
                design_intake = await design_input_service.intake_design(
                    text, title, source, meta, spec_intake, gateway=self._gateway_for(run), registry=self.registry
                )
            if not self._import_writable(run, generation):
                return
            self._commit_design_import(run, generation, spec_intake, design_intake, title, meta)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            category = classify_llm_error(exc)
            message = user_message_for_error(exc) or UNEXPECTED_IMPORT_FAILURE
            if category is None:
                self._record_import_exception(run, exc)
            self._fail_import(run, generation, message, category=category)
            return

    def _commit_design_import(
        self,
        run: RunState,
        generation: int,
        spec_intake: Any,
        design_intake: Any,
        title: str,
        meta: Any,
    ) -> None:
        if not self._import_writable(run, generation):
            return
        run.artifacts["spec"] = spec_intake.spec.model_dump()
        run.artifacts["design"] = design_intake.design.model_dump()
        run.artifacts.setdefault("issues", [])
        missing = design_input_service.merge_missing(spec_intake.missing, design_intake.missing)
        checks = design_input_service.cross_checks(
            spec_intake,
            design_intake,
            max_modules=int((run.limits.get("design") or {}).get("max_modules") or 10),
        )
        run.artifacts["design_input_missing"] = missing
        run.artifacts["design_input_checks"] = checks
        run.artifacts["design_input_notes"] = {
            "spec": spec_intake.notes,
            "design": design_intake.notes,
            "section_map": spec_intake.section_map + design_intake.section_map,
        }
        flat_errors = [f"SPEC: {e}" for e in checks["spec"]] + [f"DESIGN: {e}" for e in checks["design"]]
        run.artifacts["design_input_errors"] = flat_errors
        run.artifacts["design_input_step"] = ""
        run.artifacts["design_input_generation"] = generation + 1

        if missing or flat_errors:
            run.status = "stopped"
            category = "missing_fields" if missing else "invalid_structure"
            message = user_message_for_category(category) or (
                "设计规格缺少必要内容，未进入任务分解" if missing else "设计规格未通过结构检查，未进入任务分解"
            )
            run.artifacts["design_input_status"] = "needs_input"
            run.artifacts["design_input_message"] = message
            run.artifacts["design_input_error_category"] = category
            self.emit(
                run,
                "design_input.needs_input",
                "",
                {"missing": missing, "errors": flat_errors, "error_category": category},
                "system",
            )
            self._persist_snapshot(run)
            return

        # 外部文档整理成功后直接进入设计阶段，不走讨论/评审。
        run.engine.history.append({"from": "4", "event": "spec_confirmed", "to": "5"})
        run.artifacts["design_input_status"] = "awaiting_confirmation"
        run.artifacts["design_input_message"] = "设计规格已整理，等待确认"
        run.artifacts.pop("design_input_error_category", None)
        self._gate(
            run,
            "DESIGN基线确认",
            {
                "design": run.artifacts["design"],
                "spec": run.artifacts["spec"],
                "reviews": [],
                "imported": True,
                "source": run.artifacts["design_input"].get("source"),
                "title": title,
                "missing": [],
                "provenance": run.artifacts["provenance"],
            },
        )
        self.emit(run, "design_input.accepted", "", {"sha256": getattr(meta, "sha256", "")}, "system")
        self._persist_snapshot(run)

    def patch_limits(self, run: RunState, body: dict[str, Any], actor: str = "owner") -> dict[str, Any]:
        before = copy.deepcopy(run.limits)
        _deep_merge_limits(run.limits, body)
        self.emit(run, "system.limit_changed", "", {"before": before, "after": copy.deepcopy(run.limits)}, actor)
        return run.limits

    def _prepare_scripted(self) -> None:
        from app.llm.providers import ScriptedProvider
        from app.settings import get_settings

        provider = self.gateway.provider
        if not isinstance(provider, ScriptedProvider):
            return
        if get_settings().test3_scripted_fixture != "study-room":
            return
        if provider.queue:
            return
        from app.fixtures.study_room import scripted_full_queue

        provider.queue = list(scripted_full_queue())

    def _drain_gateway(self, run: RunState) -> None:
        gateway = self._gateway_for(run)
        while gateway.events:
            ev = gateway.events.pop(0)
            self.emit(run, ev.get("kind") or "llm.fallback", str(ev.get("slot") or ""), ev)

    def _emit_budget(self, run: RunState, task: dict[str, Any] | None = None) -> None:
        orch = run.limits.get("orchestrator") or {}
        info = check_budget(
            run.tokens_used,
            int(orch.get("run_token_budget") or 0),
            warn_ratio=float(orch.get("warn_ratio") or 0.8),
        )
        if info["warn"] and not run.artifacts.get("_budget_warned"):
            run.artifacts["_budget_warned"] = True
            self.emit(run, "budget.warn", "", info)
        if info["exceeded"]:
            run.paused = True
            self.emit(run, "budget.exceeded", "", info)
        if task is None:
            return
        card = TaskCard.model_validate(task["card"])
        limit = tokens_budget(int(card.points), int(orch.get("tokens_per_point") or 1_500_000))
        tinfo = check_budget(int(task.get("tokens_used") or 0), limit, warn_ratio=float(orch.get("warn_ratio") or 0.8))
        if tinfo["exceeded"]:
            task["last_error"] = "token_budget"
            if can_transition(task["state"], "budget_or_stuck"):
                self._set_state(run, task, "budget_or_stuck", extra=tinfo)
            self.emit(run, "budget.exceeded", task["code"], tinfo)

    def _judge_patterns(self) -> dict[str, list[str]]:
        return {
            "empty": list(self.profile.get("empty_test_patterns") or []),
            "skip": list(self.profile.get("skip_all_patterns") or []),
        }

    def _whitelist(self) -> list[str]:
        return list(self.profile.get("whitelist_prefixes") or ["pytest", "python -m pytest", "python -m ruff", "ruff check"])

    def _forbidden(self) -> list[str]:
        return list(self.profile.get("forbidden_prefixes") or [])

    def _require_model(self, value: Any, expected: type, role: str) -> Any:
        if not isinstance(value, expected):
            raise AgentOutputError(f"{role} output type {type(value).__name__}, expected {expected.__name__}")
        return value

    async def _write_checked(
        self,
        run: RunState,
        role: str,
        inputs: dict[str, Any],
        check: Callable[[Any], list[str]],
        expected: type,
        *,
        max_rewrites: int = 2,
    ) -> tuple[Any, list[str]]:
        payload = dict(inputs)
        last_doc: Any = None
        errors: list[str] = []
        for attempt in range(max_rewrites + 1):
            doc = await call_agent(role, payload, registry=self.registry, gateway=self._gateway_for(run))
            self._require_model(doc, expected, role)
            last_doc = doc
            errors = check(doc)
            if not errors:
                return doc, []
            payload = {**inputs, "rewrite": {"errors": errors, "attempt": attempt + 1}}
        return last_doc, errors

    def _max_rewrites(self, run: RunState, section: str) -> int:
        return int((run.limits.get(section) or {}).get("max_rewrites") or 2)

    async def start_idea(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            card = IdeaCard(raw=run.idea)
            check = await call_agent("idea_checker", {"idea_card": card.model_dump()}, registry=self.registry, gateway=self._gateway_for(run))
            self._require_model(check, IdeaCheck, "idea_checker")
            card.user, card.problem, card.needs_payer, card.payer = check.user, check.problem, check.needs_payer, check.payer
            if check.missing and not check.ok:
                return self._gate(run, "想法补充", {"missing": check.missing, "card": card.model_dump()})
            draft = await call_agent("pm_draft", {"idea_card": card.model_dump()}, registry=self.registry, gateway=self._gateway_for(run))
            self._require_model(draft, IdeaDraft, "pm_draft")
            card.approach = draft.approach
            card.features = draft.features
            run.artifacts["idea_card"] = card.model_dump()
            return self._gate(run, "初步做法确认", {"card": card.model_dump()})

    async def resolve_gate(
        self,
        run: RunState,
        gate_id: str,
        decision: str,
        payload: dict[str, Any],
        actor: str = "owner",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        # A human decision can advance into PLAN / rewrite docs / spawn defects.
        # Reject retired DeepSeek-only runs before mutating any gate state.
        self._reject_retired(run)
        # 同一运行的关卡裁决串行化：并发重复点击只会有一条进入分支，
        # 后到者看到 gate 已裁决而返回 400，不会重复生成计划/任务。
        async with self._gate_lock_for(run):
            return await self._resolve_gate_locked(run, gate_id, decision, payload, actor, expected_revision)

    async def _resolve_gate_locked(
        self,
        run: RunState,
        gate_id: str,
        decision: str,
        payload: dict[str, Any],
        actor: str = "owner",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        gate = next(g for g in run.gates if g["id"] == gate_id)
        if gate["status"] != "pending":
            raise ValidationFailed("关卡已裁决，不能重复推进")
        if expected_revision is not None and expected_revision != run.revision:
            raise RevisionConflict("revision mismatch")
        gate["status"] = "approved" if decision == "approve" else "rejected"
        gate["decision"] = payload
        gate["resolved_by"] = actor
        gate["resolved_at"] = datetime.now(timezone.utc).isoformat()
        run.pending_human = False
        run.revision += 1
        self.emit(run, "gate.resolved", gate_id, {"decision": decision, **payload}, actor)
        kind = gate["kind"]
        if kind == "想法补充":
            run.engine.supplements += 1
            extra = payload.get("text") or ""
            run.idea = run.idea + " " + extra
            return await self.start_idea(run)
        if kind == "初步做法确认":
            if decision != "approve":
                return await self.start_idea(run)
            self._record_approved_baseline(
                run, "REQUIREMENT", {"idea": run.idea, "idea_card": run.artifacts.get("idea_card") or {}}
            )
            await self._refresh_grant_statuses(run)
            run.engine.apply("idea_confirmed")
            return await self.run_discussion_step(run)
        if kind == "争议清单查看与裁决":
            if decision != "approve":
                return self._gate(
                    run,
                    "争议清单查看与裁决",
                    {
                        "issues": run.artifacts.get("issues") or [],
                        "reopen": True,
                        "reason": payload.get("reason") or "驳回",
                    },
                )
            self._apply_verdicts(run, payload.get("verdicts") or [])
            run.engine.apply("discussion_viewed")
            return await self.run_proposal(run)
        if kind == "评审确认":
            return await self.after_review_gate(run, decision, payload)
        if kind == "SPEC基线确认":
            if decision != "approve":
                run.artifacts["spec_rewrite"] = {"reason": payload.get("reason") or "驳回", "errors": ["人工驳回"]}
                return await self.run_spec(run)
            self._record_approved_baseline(run, "SPEC", run.artifacts.get("spec") or {})
            await self._refresh_grant_statuses(run)
            self._freeze(run, "SPEC")
            self._record_gate_approval(run, gate, actor)
            run.engine.apply("spec_confirmed")
            return await self.run_design(run)
        if kind == "DESIGN基线确认":
            if decision != "approve":
                if run.artifacts.get("design_input"):
                    run.status = "stopped"
                    run.pending_human = False
                    self.emit(run, "design_input.rejected", gate_id, {"reason": payload.get("reason") or "人工驳回"})
                    return {
                        "status": "rejected",
                        "stage": run.engine.current,
                        "hint": "请修改设计规格原文后重新创建运行；导入运行不做原地改写。",
                    }
                run.artifacts["design_rewrite"] = {"reason": payload.get("reason") or "驳回", "errors": ["人工驳回"]}
                return await self.run_design(run)
            self._record_approved_baseline(run, "DESIGN", run.artifacts.get("design") or {})
            await self._refresh_grant_statuses(run)
            self._freeze(run, "DESIGN")
            self._record_gate_approval(run, gate, actor)
            if run.artifacts.get("design_input"):
                run.artifacts["design_input_status"] = "design_confirmed"
            run.engine.apply("design_confirmed")
            return await self.run_plan(run)
        if kind == "PLAN基线确认":
            if decision != "approve":
                run.artifacts["plan_rewrite"] = {"reason": payload.get("reason") or "驳回", "errors": ["人工驳回"]}
                return await self.run_plan(run)
            if run.artifacts.get("discussion_session_id"):
                self._record_approved_baseline(run, "DESIGN", run.artifacts["design"])
                self._freeze(run, "DESIGN")
            self._record_approved_baseline(run, "PLAN", run.artifacts.get("plan") or {})
            await self._refresh_grant_statuses(run)
            self._freeze(run, "PLAN")
            self._record_gate_approval(run, gate, actor)
            if run.artifacts.get("design_input"):
                run.artifacts["design_input_status"] = "plan_confirmed"
            run.engine.apply("plan_confirmed")
            self._materialize_tasks(run)
            return {"status": "executing", "stage": run.engine.current}
        if kind == "验收确认":
            return self._resolve_acceptance(run, decision, payload, gate)
        if kind == "文档检查失败":
            if decision != "approve":
                return {"status": "rejected", "kind": kind}
            retry = str((gate.get("payload") or {}).get("retry") or "")
            errors = list((gate.get("payload") or {}).get("errors") or [])
            if retry == "proposal":
                return await self.run_proposal(run)
            if retry == "spec":
                run.artifacts["spec_rewrite"] = {"reason": payload.get("reason") or "文档检查失败", "errors": errors}
                return await self.run_spec(run)
            if retry == "design":
                run.artifacts["design_rewrite"] = {"reason": payload.get("reason") or "文档检查失败", "errors": errors}
                return await self.run_design(run)
            if retry == "plan":
                run.artifacts["plan_rewrite"] = {"reason": payload.get("reason") or "文档检查失败", "errors": errors}
                return await self.run_plan(run)
            return {"status": "rejected", "kind": kind}
        if kind == "重排提案":
            if decision != "approve":
                return {"status": "rejected", "kind": kind}
            return await self._apply_replan(run, payload)
        if kind == "反馈分流确认":
            return {"status": "routed"}
        if kind == "变更决定":
            body = dict(payload)
            cr_payload = (gate.get("payload") or {}).get("cr") or {}
            if not body.get("code"):
                body["code"] = cr_payload.get("code")
            if decision != "approve":
                body["decision"] = "驳回"
            elif not body.get("decision"):
                body["decision"] = "批准"
            return await self.decide_cr(run, body)
        return {"status": gate["status"]}

    def _resolve_acceptance(self, run: RunState, decision: str, payload: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        passed = bool((gate.get("payload") or {}).get("pass"))
        reason = str(payload.get("reason") or "").strip()
        if decision != "approve":
            return {"status": "rejected", "pass": passed}
        if not passed and not reason:
            gate["status"] = "pending"
            run.pending_human = True
            raise ValidationFailed("验收未通过，人工确认必须写理由")
        run.engine.apply("acceptance_confirmed")
        self._freeze(run, "BUILD")
        self._export_release(run)
        run.status = "done"
        self._persist_snapshot(run)
        return {
            "status": "done",
            "pass": passed,
            "manual": (not passed),
            "reason": reason,
            "release": run.artifacts.get("release_dir"),
            "tag": run.artifacts.get("build_tag"),
        }

    def _export_release(self, run: RunState) -> Path:
        repo = self.data_dir / "runs" / run.id / "repo"
        dest = self.data_dir / "runs" / run.id / "release"
        dest.mkdir(parents=True, exist_ok=True)
        version = str(run.artifacts.get("baseline_BUILD") or "1.0")
        if (repo / ".git").exists():
            try:
                run.artifacts["build_tag"] = tag_build(repo, version)
            except RuntimeError:
                run.artifacts["build_tag"] = f"build-{version}"
            code_dir = dest / "code"
            if code_dir.exists():
                shutil.rmtree(code_dir)
            shutil.copytree(repo, code_dir, ignore=shutil.ignore_patterns(".git"))
        for name, key in (("SPEC.json", "spec"), ("DESIGN.json", "design"), ("PLAN.json", "plan"), ("acceptance.json", "acceptance")):
            (dest / name).write_text(json.dumps(run.artifacts.get(key) or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        (dest / "trace.json").write_text(json.dumps(run.trace.matrix(), ensure_ascii=False, indent=2), encoding="utf-8")
        (dest / "RUN_SOURCE.json").write_text(
            json.dumps(run.artifacts.get("provenance") or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        run.artifacts["release_dir"] = str(dest)
        return dest

    async def run_discussion_step(
        self,
        run: RunState,
        *,
        reopen: bool = False,
        review_opinions: list[Any] | None = None,
        prev_issues: list[Issue] | None = None,
    ) -> dict[str, Any]:
        card = IdeaCard.model_validate(run.artifacts["idea_card"])
        with self._usage_scope(run):
            result = await run_discussion(
                card,
                registry=self.registry,
                gateway=self._gateway_for(run),
                ids=run.ids,
                reopen=reopen,
                review_opinions=review_opinions,
                prev_issues=prev_issues,
                max_utterances=int((run.limits.get("discussion") or self.limits["discussion"])["max_utterances"]),
            )
        run.artifacts["questions"] = [q.model_dump() for q in result["questions"]]
        run.artifacts["merge_rows"] = [r.model_dump() for r in result["merge_rows"]]
        run.artifacts["utterances"] = [u.model_dump() for u in result["utterances"]]
        run.artifacts["issues"] = [i.model_dump() for i in result["issues"]]
        for u in result["utterances"]:
            self.emit(run, "discussion.message", str(u.seq), {"role": u.role, "rule": u.rule})
        if result["status_overrides"]:
            self.emit(run, "discussion.status_overridden", "", {"items": result["status_overrides"]})
        return self._gate(run, "争议清单查看与裁决", {"issues": run.artifacts["issues"], "reopen": reopen})

    async def run_proposal(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
            idea = run.artifacts["idea_card"]
            doc, errors = await self._write_checked(
                run,
                "proposal_writer",
                {"idea_card": idea, "issue_list": [i.model_dump() for i in issues]},
                lambda item: check_proposal(item, issues, capacity=int((run.limits.get("plan") or {})["capacity_points"])),
                ProposalDoc,
                max_rewrites=self._max_rewrites(run, "spec"),
            )
            run.artifacts["proposal"] = doc.model_dump()
            run.artifacts["proposal_errors"] = errors
            if errors:
                return self._doc_check_failed(run, retry="proposal", errors=errors)
            run.engine.apply("proposal_checked")
            return await self.run_review(run)

    async def run_review(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            sheets: list[ReviewSheet] = []
            for role in ("review_user", "review_dev", "review_qa", "review_expert"):
                sheet = await call_agent(
                    role,
                    {"idea_card": run.artifacts["idea_card"], "proposal": run.artifacts["proposal"]},
                    registry=self.registry,
                    gateway=self._gateway_for(run),
                )
                self._require_model(sheet, ReviewSheet, role)
                for op in sheet.opinions:
                    if not op.code:
                        op.code = run.ids.next("R")
                sheets.append(sheet)
            run.artifacts["reviews"] = [s.model_dump() for s in sheets]
            run.artifacts["review_pass"] = review_pass(sheets)
            return self._gate(run, "评审确认", {"pass": run.artifacts["review_pass"], "reviews": run.artifacts["reviews"]})

    async def after_review_gate(self, run: RunState, decision: str, payload: dict[str, Any]) -> dict[str, Any]:
        sheets = [ReviewSheet.model_validate(s) for s in run.artifacts["reviews"]]
        opinions = [op for s in sheets for op in s.opinions]
        passed = bool(run.artifacts["review_pass"])
        if decision == "override":
            passed = payload.get("pass", passed)
            self.emit(run, "review.overridden", "", {"reason": payload.get("reason", "")}, "owner")
        if passed and decision in {"approve", "override"}:
            run.engine.apply("review_confirmed")
            return await self.run_spec(run)
        route = payload.get("route") or route_review(opinions, returns=run.engine.returns, max_returns=int((run.limits.get("rework") or {})["max_returns"]))
        if route == "步骤1":
            run.engine.apply("review_to_discussion")
            if run.engine.current == "stopped":
                return {"status": "stopped", "reason": "退回超过 2 次"}
            prev = [Issue.model_validate(i) for i in run.artifacts["issues"]]
            disputed = [op for op in opinions if op.kind == "争议类"] or opinions
            return await self.run_discussion_step(run, reopen=True, review_opinions=disputed, prev_issues=prev)
        if route == "步骤2":
            run.engine.apply("review_to_proposal")
            if run.engine.current == "stopped":
                return {"status": "stopped", "reason": "退回超过 2 次"}
            return await self.run_proposal(run)
        if route == "我决定" and payload.get("accept_risk"):
            run.engine.apply("review_accept_risk")
            return await self.run_spec(run)
        run.engine.apply("review_stop")
        return {"status": "stopped", "reason": "只有验证类意见，先做真人验证"}

    async def run_spec(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
            inputs: dict[str, Any] = {
                "idea_card": run.artifacts["idea_card"],
                "proposal": run.artifacts["proposal"],
                "issue_list": [i.model_dump() for i in issues],
                "review_sheet": run.artifacts["reviews"],
            }
            if run.artifacts.get("spec_rewrite"):
                inputs["rewrite"] = run.artifacts.pop("spec_rewrite")
            spec, errors = await self._write_checked(
                run,
                "spec_writer",
                inputs,
                lambda item: check_spec(item, issues, [ReviewSheet.model_validate(s) for s in run.artifacts["reviews"]]),
                SpecDoc,
                max_rewrites=self._max_rewrites(run, "spec"),
            )
            run.artifacts["spec"] = spec.model_dump()
            run.artifacts["spec_errors"] = errors
            if errors:
                return self._doc_check_failed(run, retry="spec", errors=errors)
            for item in spec.features + spec.nonfunc:
                for src in item.sources:
                    run.trace.link(src, item.code, "issue → spec_item")
            return self._gate(run, "SPEC基线确认", {"spec": spec.model_dump()})

    async def run_design(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            spec = SpecDoc.model_validate(run.artifacts["spec"])
            issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
            inputs: dict[str, Any] = {"spec": spec.model_dump()}
            if run.artifacts.get("design_rewrite"):
                inputs["rewrite"] = run.artifacts.pop("design_rewrite")
            design, errors = await self._write_checked(
                run,
                "architect",
                inputs,
                lambda item: check_design(item, spec, issues, max_modules=int((run.limits.get("design") or {})["max_modules"])),
                DesignDoc,
                max_rewrites=self._max_rewrites(run, "design"),
            )
            run.artifacts["design"] = design.model_dump()
            run.artifacts["design_errors"] = errors
            if errors:
                return self._doc_check_failed(run, retry="design", errors=errors)
            max_rewrites = self._max_rewrites(run, "design")
            sheets, design, review_status = await self._design_reviews(run, spec, design, max_rewrites)
            if review_status:
                return review_status
            run.artifacts["design"] = design.model_dump()
            run.artifacts["design_reviews"] = [sheet.model_dump() for sheet in sheets]
            run.artifacts["design_review_pass"] = review_pass(sheets)
            for module in design.modules:
                for src in module.sources:
                    run.trace.link(src, module.code, "spec_item → module")
            return self._gate(run, "DESIGN基线确认", {"design": design.model_dump(), "reviews": run.artifacts["design_reviews"]})

    async def _design_reviews(
        self,
        run: RunState,
        spec: SpecDoc,
        design: DesignDoc,
        max_rewrites: int,
    ) -> tuple[list[ReviewSheet], DesignDoc, dict[str, Any] | None]:
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        rewrites = 0
        sheets = await self._call_design_reviewers(run, spec, design)
        while not review_pass(sheets):
            opinions = [op for sheet in sheets for op in sheet.opinions]
            route = route_design_review(opinions, rewrites=rewrites, max_rewrites=max_rewrites)
            if route == "重写" and rewrites < max_rewrites:
                rewrites += 1
                design, errors = await self._write_checked(
                    run,
                    "architect",
                    {"spec": spec.model_dump(), "rewrite": {"errors": [op.text for op in opinions], "attempt": rewrites}},
                    lambda item: check_design(item, spec, issues, max_modules=int((run.limits.get("design") or {})["max_modules"])),
                    DesignDoc,
                    max_rewrites=0,
                )
                if errors:
                    return sheets, design, self._doc_check_failed(run, retry="design", errors=errors, extra={"route": route})
                sheets = await self._call_design_reviewers(run, spec, design)
                continue
            if route == "停止":
                return sheets, design, self._doc_check_failed(
                    run,
                    retry="design",
                    errors=["设计评审未通过"],
                    extra={"route": route, "reason": "设计评审未通过"},
                )
            if route == "变更单":
                return sheets, design, await self.submit_cr(run, "设计评审：需求类意见", [item.code for item in spec.features[:1]], kind="小变更")
            if route == "探索任务":
                return sheets, design, self._doc_check_failed(
                    run,
                    retry="design",
                    errors=["设计评审要求探索任务"],
                    extra={"route": route, "reason": "设计评审要求探索任务"},
                )
            break
        return sheets, design, None

    async def _call_design_reviewers(self, run: RunState, spec: SpecDoc, design: DesignDoc) -> list[ReviewSheet]:
        sheets: list[ReviewSheet] = []
        for role in ("review_arch", "review_quality"):
            sheet = await call_agent(
                role,
                {"spec": spec.model_dump(), "design": design.model_dump()},
                registry=self.registry,
                gateway=self._gateway_for(run),
            )
            self._require_model(sheet, ReviewSheet, role)
            for op in sheet.opinions:
                if not op.code:
                    op.code = run.ids.next("R")
            sheets.append(sheet)
        return sheets

    async def run_plan(self, run: RunState) -> dict[str, Any]:
        # Retired DeepSeek-only runs must not regenerate PLAN (the former model_stage
        # path). Reject before any gateway, timeout task, or event is created.
        self._reject_retired(run)
        return await self._generate_plan(run)

    async def _generate_plan(self, run: RunState) -> dict[str, Any]:
        with self._usage_scope(run):
            spec = SpecDoc.model_validate(run.artifacts["spec"])
            design = DesignDoc.model_validate(run.artifacts["design"])
            discussion_id = run.artifacts.get("discussion_session_id")
            if discussion_id:
                rewrite = run.artifacts.pop("plan_rewrite", None)
                async with self.db_session() as session:
                    record = await DiscussionSessionStore(session).get(discussion_id)
                existing_packages = (run.artifacts.get("plan") or {}).get("work_packages") or []
                try:
                    graph = await discussion_planning.generate(
                        self, record, spec=spec, design=design, rewrite=rewrite,
                        work_packages=existing_packages,
                    )
                except (BotFailed, ValidationFailed) as exc:
                    message = user_message_for_category(exc.category) if isinstance(exc, BotFailed) else str(exc)
                    return self._doc_check_failed(run, retry="plan", errors=[message])
                run.artifacts["plan"] = graph.model_dump()
                run.artifacts["plan_errors"] = []
                return self._gate(
                    run, "PLAN基线确认", {"plan": graph.model_dump(), "design": run.artifacts["design"]},
                )
            inputs: dict[str, Any] = {"spec": spec.model_dump(), "design": design.model_dump()}
            if run.artifacts.get("plan_rewrite"):
                inputs["rewrite"] = run.artifacts.pop("plan_rewrite")
            graph, errors = await self._write_checked(
                run,
                "decomposer",
                inputs,
                lambda item: check_task_graph(item, spec, design, int((run.limits.get("plan") or {})["capacity_points"])),
                TaskGraph,
                max_rewrites=self._max_rewrites(run, "spec"),
            )
            run.artifacts["plan"] = graph.model_dump()
            run.artifacts["plan_errors"] = errors
            if errors:
                return self._doc_check_failed(run, retry="plan", errors=errors)
            return self._gate(run, "PLAN基线确认", {"plan": graph.model_dump()})

    def _materialize_tasks(self, run: RunState) -> None:
        graph = TaskGraph.model_validate(run.artifacts["plan"])
        fingerprint = hash_artifact(graph.model_dump())
        if run.artifacts.get("plan_materialized") == fingerprint and run.tasks:
            # 同一版本计划重复确认时只刷新就绪状态，不重建任务、不重置进度。
            self._attach_granted_specs(run)
            self._refresh_ready(run)
            return
        run.artifacts["plan_materialized"] = fingerprint
        for task in graph.tasks:
            existing = run.tasks.get(task.code)
            if existing and existing["state"] == "done":
                continue
            run.tasks[task.code] = {
                "id": f"{run.id}:{task.code}",
                "code": task.code,
                "state": "pending",
                "revision": int((existing or {}).get("revision") or 1),
                "card": task.model_dump(),
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
                "tokens_used": 0,
                "prev_output": "",
                "review_issues": [],
            }
            for src in task.sources:
                run.trace.link(src, task.code, "spec_item → task")
        self._sync_task_ids(run)
        self._attach_granted_specs(run)
        self._refresh_ready(run)

    def _refresh_ready(self, run: RunState) -> None:
        states = {code: t["state"] for code, t in run.tasks.items()}
        failed_deps = {"failed", "cancelled", "needs_human"}
        for code, task in run.tasks.items():
            was_dependency_blocked = bool(task.get("blocked_by"))
            if task["state"] != "pending" and not (task["state"] == "blocked" and was_dependency_blocked):
                continue
            deps = list(task["card"]["depends_on"])
            blocked_by = [d for d in deps if states.get(d) in failed_deps]
            waiting_on = [
                d
                for d in deps
                if d not in blocked_by
                and not (states.get(d) == "done" or (states.get(d) == "skipped" and d in run.skip_continue))
            ]
            task["blocked_by"] = blocked_by
            task["waiting_on"] = waiting_on
            if blocked_by:
                if task["state"] == "pending":
                    self._set_state(run, task, "upstream_bad")
                continue
            if task["state"] == "blocked":
                self._set_state(run, task, "upstream_ok")
            if not waiting_on:
                self._set_state(run, task, "deps_met")

    def _task_over_budget(self, run: RunState, task: dict[str, Any]) -> bool:
        card = TaskCard.model_validate(task["card"])
        limit = tokens_budget(int(card.points), int((run.limits.get("orchestrator") or {}).get("tokens_per_point") or 1_500_000))
        return int(task.get("tokens_used") or 0) >= limit

    async def _granted_scope(self, run: RunState, task_codes: set[str] | None) -> set[str] | None:
        """Validate the active grant before a granted_v1 run may execute.

        ``legacy`` returns ``None`` immediately: legacy schedule behavior must
        stay byte-for-byte compatible and must never ask for a grant.
        """
        profile = run_execution_profile(run)
        if profile == PROFILE_LEGACY:
            return None
        if profile != PROFILE_GRANTED:
            category = "profile_conflict" if profile == PROFILE_CONFLICT else "profile_unspecified"
            raise GrantRejected(category, "run execution profile is not usable", status_code=409)
        grants = await self.grants_for_run(run.id)
        if not grants:
            raise GrantRejected("grant_required", "granted_v1 run has no execution grant", status_code=403)
        active = [
            grant for grant in grants if grant.status == "active" and grant.run_id == run.id
        ]
        if not active:
            relevant = [grant for grant in grants if grant.run_id == run.id] or grants
            latest = relevant[-1]
            if latest.status == "stale":
                raise GrantRejected("baseline_stale", "execution grant is stale", status_code=409)
            if latest.status in {"revoked", "consumed"}:
                raise GrantRejected(
                    f"grant_{latest.status}",
                    f"execution grant is {latest.status}",
                    status_code=409,
                )
            raise GrantRejected(
                "grant_not_active",
                f"execution grant is not active (status={latest.status})",
                status_code=409,
            )
        if task_codes is None:
            grant = active[-1]
            requested = {
                code
                for code in grant.task_codes
                if (run.tasks.get(code) or {}).get("state") not in _GRANT_COMPLETED_STATES
            }
        else:
            requested = set(task_codes)
            covering = [grant for grant in active if requested.issubset(set(grant.task_codes))]
            if not covering:
                raise GrantRejected(
                    "scope_mismatch",
                    "requested tasks are outside the approved grant scope",
                    status_code=409,
                )
            grant = covering[-1]
        reason = grant_stale_reason(
            grant,
            approved_baseline_hashes=run_approved_baseline_hashes(run),
            requested_task_codes=requested,
        )
        if reason is None:
            return requested
        if reason.startswith("baseline_changed:"):
            raise GrantRejected("baseline_stale", reason, status_code=409)
        status_code = 403 if reason == "grant_required" else 409
        raise GrantRejected(reason, reason, status_code=status_code)

    async def schedule_once(self, run: RunState, *, task_codes: set[str] | None = None) -> list[str]:
        # Direct API callers get the same controlled rejection as the auto loop.
        self._reject_retired(run)
        self._require_execution_authorization(run, "schedule")
        allowed = await self._granted_scope(run, task_codes)
        if task_codes is not None and run_execution_profile(run) == PROFILE_GRANTED:
            # P5: a successor may not start before its predecessors succeeded.
            # Only explicit requests are rejected; the auto loop keeps selecting
            # ready tasks by dependency and legacy behaviour is untouched.
            blocked = dag_blocked_tasks(
                edges_from_tasks(run.tasks),
                {code: task["state"] for code, task in run.tasks.items()},
                task_codes,
            )
            if blocked:
                raise GrantRejected(
                    "dag_blocked",
                    f"predecessors are not done: {', '.join(blocked)}",
                    status_code=409,
                )
        # 同一运行的调度串行化，避免并发请求把同一任务派发两次。
        # P5: 调度与任务写路径共用同一把 per-run 锁。
        async with self._run_locks.write_scope(run.id):
            return await self._schedule_once_locked(run, allowed=allowed)

    async def _schedule_once_locked(self, run: RunState, *, allowed: set[str] | None = None) -> list[str]:
        if run.paused:
            return []
        if run.status in {"done", "terminated"}:
            return []
        for task in run.tasks.values():
            if task["state"] == "stale" and not task.get("paused"):
                self._set_state(run, task, "change_approved")
        started: list[str] = []
        while not run.paused:
            conflict_ready = [
                TaskCard.model_validate(t["card"])
                for t in run.tasks.values()
                if t.get("conflict_resolve")
                and t["state"] == "ready"
                and not t["paused"]
                and not t["locked_by"]
                and t["code"] not in started
                and (allowed is None or t["code"] in allowed)
            ]
            if conflict_ready:
                await asyncio.gather(*(self.execute_task(run, card.code) for card in conflict_ready))
                started.extend(card.code for card in conflict_ready)
                self._refresh_ready(run)
                continue
            graph = TaskGraph.model_validate(run.artifacts["plan"])
            states = {c: t["state"] for c, t in run.tasks.items()}
            running = [TaskCard.model_validate(t["card"]) for t in run.tasks.values() if t["state"] == "running"]
            picked = [
                card
                for card in select_tasks(
                    graph,
                    states,
                    run_paused=run.paused,
                    paused={c for c, t in run.tasks.items() if t["paused"]},
                    locked={c for c, t in run.tasks.items() if t["locked_by"]},
                    running=running,
                    concurrency=int((run.limits.get("orchestrator") or {})["concurrency"]),
                    budget_exhausted={c for c, t in run.tasks.items() if self._task_over_budget(run, t)},
                    skip_continue=run.skip_continue,
                )
                if card.code not in started and (allowed is None or card.code in allowed)
            ]
            if not picked:
                break
            await asyncio.gather(*(self.execute_task(run, card.code) for card in picked))
            started.extend(card.code for card in picked)
            self._refresh_ready(run)
        self._maybe_tasks_complete(run)
        return started

    async def execute_task(self, run: RunState, code: str) -> dict[str, Any]:
        # P5: all real task writes for a run go through one lock.  Nested calls
        # from the schedule loop re-enter instead of deadlocking.
        async with self._run_locks.write_scope(run.id):
            return await self._execute_task_locked(run, code)

    async def _execute_task_locked(self, run: RunState, code: str) -> dict[str, Any]:
        self._require_execution_authorization(run, "execute")
        self._require_execution_safety(run, code)
        task = run.tasks[code]
        card = TaskCard.model_validate(task["card"])
        if run.status == "terminated":
            self.emit(run, "task.late_result_ignored", code, {"reason": "run terminated"}, "system")
            return {"state": task["state"], "kind": "已终止"}
        if task.get("locked_by") and not task.get("takeover_submit"):
            return {"state": task["state"], "kind": "locked"}
        # Real execution boundary: granted_v1 is validated before any revision
        # bump, state transition, worktree or command.  No Grant / missing spec
        # can never fall through to the legacy agent/commit/merge chain.
        grant: ExecutionGrant | None = None
        granted_spec: dict[str, Any] | None = None
        if run_execution_profile(run) == PROFILE_GRANTED:
            grant, granted_spec = await self._authorize_granted_execution(run, code)
            # F-08: platform policy ∩ Grant.allowed_tool_refs ∩ materialized
            # command/tool_refs.  Runs before preflight, worktree, writes and
            # any process, so a denial has no side effects.
            authorize_granted_command(
                granted_spec.get("command") or [],
                grant_tool_refs=grant.allowed_tool_refs,
                spec_tool_refs=granted_spec.get("tool_refs") or [],
                platform_whitelist=self._whitelist(),
                platform_forbidden=self._forbidden(),
            )
            # F-06: no isolation backend means no execution side effects at all.
            blocked = self._block_unless_isolated(run, task, code)
            if blocked is not None:
                return blocked
        task["revision"] = int(task.get("revision") or 1) + 1
        if task["state"] == "ready":
            self._set_state(run, task, "scheduled")
        if self._task_over_budget(run, task):
            task["last_error"] = "token_budget"
            if can_transition(task["state"], "budget_or_stuck"):
                self._set_state(run, task, "budget_or_stuck")
            self.emit(run, "budget.exceeded", code, {"used": task.get("tokens_used")})
            return {"state": task["state"], "kind": "预算耗尽"}
        if granted_spec is not None and grant is not None:
            return await self._execute_granted_task(run, code, task, card, granted_spec, grant)
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        wt = self.data_dir / "runs" / run.id / "wt" / code
        try:
            if not wt.exists():
                create_worktree(repo, wt, f"task/{code}")
        except Exception as exc:  # noqa: BLE001
            return await self._finish_failure(run, task, card, "环境故障", str(exc), _exc_fields(exc))
        visible: dict[str, Any] = {
            "task_card": card.model_dump(),
            "interfaces": task.get("interfaces") or [],
            "dependency_outputs": self._dep_outputs(run, card),
        }
        if task.get("prev_output") or task.get("review_issues") or int(task.get("repair_rounds") or 0) > 0:
            visible["prev_output"] = task.get("prev_output") or ""
            visible["review_issues"] = task.get("review_issues") or []
        tools = TaskToolset(
            wt,
            list(card.write_set),
            whitelist=self._whitelist(),
            timeout=int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600),
            env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
            truncate=int(self.profile.get("output_truncate") or 8000),
            on_denied=lambda _kind, rel: self.emit(run, "task.write_denied", code, {"path": rel}),
            forbidden=self._forbidden(),
        )
        env_retries = 0
        max_env = int((run.limits.get("orchestrator") or {}).get("max_env_retries") or 3)
        result: Any = None
        with self._usage_scope(run, task):
            while True:
                try:
                    result = await run_tool_agent(
                        "coder" if card.role == "coder" else "tester",
                        visible,
                        tools,
                        registry=self.registry,
                        gateway=self._gateway_for(run),
                        max_steps=int(card.budget.max_tool_steps or (run.limits.get("orchestrator") or {}).get("max_tool_steps") or 30),
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    fields = _exc_fields(exc)
                    kind = classify(fields)
                    if kind == "环境故障" and env_retries < max_env:
                        env_retries += 1
                        await asyncio.sleep(0.01 * (2**env_retries))
                        continue
                    return await self._finish_failure(run, task, card, kind, str(exc), fields)
            if isinstance(result, dict) and result.get("done") is False:
                return await self._finish_failure(run, task, card, "代码缺陷", result.get("summary") or "max tool steps", {"exit_code": 1})
            if run.status == "terminated":
                self.emit(run, "task.late_result_ignored", code, {"reason": "run terminated"}, "system")
                return {"state": task["state"], "kind": "已终止"}
            return await self._accept_review_merge(run, code, wt, list(tools.written))

    async def _execute_granted_task(
        self,
        run: RunState,
        code: str,
        task: dict[str, Any],
        card: TaskCard,
        spec: dict[str, Any],
        grant: ExecutionGrant,
    ) -> dict[str, Any]:
        """granted_v1 branch: write only inside an isolated per-task worktree."""
        generation_id = self._generations.new_id(run.id)
        command = [str(part) for part in (spec.get("command") or [])]
        # F-08 re-check at the wrapper boundary, before any worktree or write.
        authorize_granted_command(
            command,
            grant_tool_refs=grant.allowed_tool_refs,
            spec_tool_refs=spec.get("tool_refs") or [],
            platform_whitelist=self._whitelist(),
            platform_forbidden=self._forbidden(),
        )
        blocked = self._block_unless_isolated(run, task, code)
        if blocked is not None:
            return blocked
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        wt = self.data_dir / "runs" / run.id / "wt" / f"granted-{code}"
        branch = f"{grant.feature_branch}/{code}"
        try:
            create_worktree(repo, wt, branch)
        except Exception as exc:  # noqa: BLE001
            return await self._finish_failure(run, task, card, "环境故障", str(exc), _exc_fields(exc))
        writes = [
            WriteSpec(path=str(item.get("path") or ""), content=str(item.get("content") or ""))
            for item in (spec.get("writes") or [])
            if isinstance(item, dict)
        ]
        command = [str(part) for part in (spec.get("command") or [])]
        try:
            result = await execute_task_granted(
                run.id,
                code,
                grant,
                isolation_root=wt,
                writes=writes,
                test_command=command,
                write_set=list(card.write_set),
                whitelist=self._whitelist(),
                env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                timeout=int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600),
                tool_refs=list(spec.get("tool_refs") or []),
                spec_command=command,
            )
        except CommandDenied as exc:
            return await self._finish_failure(run, task, card, "任务描述问题", str(exc), {"exit_code": 1})
        except IsolationUnavailable as exc:
            task["last_error"] = "isolation_preflight_failed"
            self.emit(run, "task.isolation_blocked", code, {"reason": exc.reason, "backend": exc.backend})
            return {"state": task["state"], "kind": "BLOCKED", "isolation_backend": exc.backend, "reason": exc.reason}
        if not self._generations.is_current(run.id, generation_id):
            # P5: pause/terminate/replan bumped the generation.  A late tool or
            # LLM reply must not write evidence, state or files.
            self.emit(run, "task.late_result_ignored", code, {"reason": "stale generation"})
            return {"state": task["state"], "kind": "ignored", "reason": "stale_generation"}
        task.setdefault("evidence", []).append(result.evidence)
        self.emit(run, "task.evidence", code, {"path": result.evidence_path, "ok": result.ok})
        if result.ok:
            if can_transition(task["state"], "code_finished"):
                self._set_state(run, task, "code_finished")
            if can_transition(task["state"], "accepted"):
                self._set_state(run, task, "accepted")
            self._refresh_ready(run)
            self._maybe_tasks_complete(run)
            return {"state": task["state"], "kind": "done", "evidence": result.evidence}
        if can_transition(task["state"], "env_fail"):
            self._set_state(run, task, "env_fail", reason="offline test failed")
        return {"state": task["state"], "kind": "代码缺陷", "evidence": result.evidence}

    async def _accept_review_merge(
        self,
        run: RunState,
        code: str,
        wt: Path,
        written: list[str] | None,
    ) -> dict[str, Any]:
        task = run.tasks[code]
        card = TaskCard.model_validate(task["card"])
        self._require_execution_safety(run, code)
        if run_execution_profile(run) == PROFILE_GRANTED:
            raise GrantRejected(
                "granted_manual_merge_disabled",
                "granted_v1 runs never use the legacy review/merge path",
                status_code=409,
            )
        if run.status == "terminated":
            self.emit(run, "task.late_result_ignored", code, {"reason": "run terminated"}, "system")
            return {"state": task["state"], "kind": "已终止"}
        repo = self.data_dir / "runs" / run.id / "repo"
        if not card.acceptance:
            return await self._finish_failure(run, task, card, "任务描述问题", "验收命令为空", {"exit_code": 1})

        cmd_results: list[dict[str, Any]] = []
        denied = False
        timeout = False
        for check in card.acceptance:
            try:
                cmd_out = await run_command(
                    list(check.cmd),
                    cwd=wt,
                    whitelist=self._whitelist(),
                    timeout=int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600),
                    env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                    truncate=int(self.profile.get("output_truncate") or 8000),
                    forbidden=self._forbidden(),
                )
            except CommandDenied as exc:
                denied = True
                cmd_results.append({"cmd": list(check.cmd), "denied": True, "exit_code": 1, "output": str(exc)})
                break
            cmd_results.append(cmd_out)
            if cmd_out.get("timeout"):
                timeout = True
        output = "\n".join(str(item.get("output") or "") for item in cmd_results)
        task["prev_output"] = output
        if denied:
            return await self._finish_failure(run, task, card, "任务描述问题", "验收命令被拒", {"exit_code": 1, "denied": True})
        if timeout:
            return await self._finish_failure(run, task, card, "环境故障", "验收超时", {"timeout": True, "exit_code": -1})

        exit_code = 0
        for item in cmd_results:
            code_i = int(item.get("exit_code") if item.get("exit_code") is not None else 1)
            if code_i != 0:
                exit_code = code_i
        judged = judge_output(exit_code, output, self._judge_patterns())

        pending = [rel for rel in dirty_files(wt) if not _ignore_write_noise(rel)]
        produced = list(written or [])
        if not pending and not produced:
            return await self._finish_failure(run, task, card, "任务描述问题", "没有真实文件产出", {"exit_code": 1, "zero_tests": True})
        sha = commit(wt, f"{code} attempt")
        extras = []
        names = [rel for rel in (changed_files(wt, "HEAD~1") if pending else produced) if not _ignore_write_noise(rel)]
        for rel in names:
            try:
                if not in_write_set((wt / rel).resolve() if (wt / rel).exists() else wt / rel, wt, list(card.write_set)):
                    extras.append(rel)
            except Exception:  # noqa: BLE001
                extras.append(rel)
        if extras:
            self.emit(run, "task.write_denied", code, {"paths": extras})
            return await self._finish_failure(run, task, card, "任务描述问题", f"写集外: {extras}", {"exit_code": 1})

        if task["state"] == "running":
            self._set_state(run, task, "code_finished")
        review = await call_agent(
            "code_reviewer",
            {"task_card": card.model_dump(), "interfaces": [], "diff": "", "command_output": output},
            registry=self.registry,
            gateway=self._gateway_for(run),
        )
        issues = list(getattr(review, "issues", []) or [])
        task["review_issues"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in issues]
        blocking = any(getattr(i, "blocking", False) for i in issues)
        verdict = getattr(review, "verdict", "fail")
        if judged["passed"] and verdict == "pass" and not blocking:
            regression_fail = ""
            async with self._merge_lock_for(run):
                merged = merge(repo, f"task/{code}")
                if merged["ok"]:
                    regression = await self._run_regression(run, repo, code)
                    if not regression["ok"]:
                        rollback_merge(repo, str(merged["before"]))
                        regression_fail = str(regression["reason"] or "regression failed")
                    else:
                        task["last_error"] = ""
                        self._set_state(run, task, "accepted")
                        task["locked_by"] = ""
                        task["takeover_submit"] = False
                        task["evidence"].append({"kind": "command", "summary": output, "path": str(wt)})
                        task["evidence"].append({"kind": "review", "summary": "pass", "path": ""})
                        task["evidence"].append({"kind": "merge", "summary": sha, "path": ""})
                        self._unlock_origin_after_conflict(run, task)
                        self._refresh_ready(run)
                        self._maybe_tasks_complete(run)
                        return {"state": "done"}
            if regression_fail:
                return await self._finish_failure(run, task, card, "代码缺陷", regression_fail, {"exit_code": 1})
            return self._spawn_conflict_task(run, code, merged)
        fields = {
            "exit_code": judged["exit_code"],
            "review_blocking": blocking,
            "zero_tests": judged["zero_tests"],
            "all_skipped": judged["all_skipped"],
            "same_signature": bool(task["signatures"] and task["signatures"][-1] == failure_signature(output)),
        }
        kind = classify(fields)
        return await self._finish_failure(run, task, card, kind, output, fields)

    def _sync_task_ids(self, run: RunState) -> None:
        for code in run.tasks:
            try:
                kind, n = IdAllocator.parse(code)
            except ValueError:
                continue
            if kind == "T":
                run.ids.set_at_least("T", n)

    def _spawn_conflict_task(self, run: RunState, origin_code: str, merged: dict[str, Any]) -> dict[str, Any]:
        origin = run.tasks[origin_code]
        origin["last_error"] = "合并冲突"
        if can_transition(origin["state"], "merge_conflict"):
            self._set_state(run, origin, "merge_conflict", extra={"kind": "合并冲突"})
        conflicts = [str(item) for item in (merged.get("conflicts") or [])]
        write_set = [path for path in conflicts if path not in {"conflict", ""}]
        if not write_set:
            write_set = list(origin["card"].get("write_set") or [])
        self._sync_task_ids(run)
        code = run.ids.next("T")
        card = TaskCard(
            code=code,
            title=f"冲突解决 {origin_code}",
            kind="impl",
            module=str(origin["card"].get("module") or "M1"),
            sources=list(origin["card"].get("sources") or []),
            description=f"冲突解决\n冲突文件: {conflicts}\n{merged.get('output') or ''}",
            write_set=write_set,
            outputs=write_set,
            acceptance=list(origin["card"].get("acceptance") or []),
            depends_on=[],
            points=int(origin["card"].get("points") or 1),
            priority="P0",
            role=origin["card"].get("role") or "coder",
        )
        run.tasks[code] = {
            "id": f"{run.id}:{code}",
            "code": code,
            "state": "pending",
            "revision": 1,
            "card": card.model_dump(),
            "repair_rounds": 0,
            "signatures": [],
            "evidence": [],
            "paused": False,
            "locked_by": "",
            "tokens_used": 0,
            "prev_output": str(merged.get("output") or ""),
            "review_issues": [],
            "conflict_resolve": True,
            "conflict_of": origin_code,
        }
        spawned = run.tasks[code]
        if spawned["state"] == "pending":
            self._set_state(run, spawned, "deps_met", extra={"kind": "冲突解决"})
        self.emit(run, "task.spawned", code, {"kind": "冲突解决", "of": origin_code, "write_set": write_set})
        return {"state": "blocked", "kind": "合并冲突", "conflict_task": code}

    def _unlock_origin_after_conflict(self, run: RunState, task: dict[str, Any]) -> None:
        if not task.get("conflict_resolve"):
            return
        origin = run.tasks.get(str(task.get("conflict_of") or ""))
        if not origin:
            return
        repo = self.data_dir / "runs" / run.id / "repo"
        wt = self.data_dir / "runs" / run.id / "wt" / origin["code"]
        try:
            remove_worktree(repo, wt)
        except Exception:  # noqa: BLE001
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
        origin["last_error"] = ""
        if can_transition(origin["state"], "conflict_resolved"):
            self._set_state(run, origin, "conflict_resolved")

    async def _finish_failure(
        self,
        run: RunState,
        task: dict[str, Any],
        card: TaskCard,
        kind: str,
        output: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if run.status == "terminated":
            self.emit(run, "task.late_result_ignored", str(task.get("code") or ""), {"reason": "run terminated"}, "system")
            return {"state": task["state"], "kind": "已终止"}
        if run_execution_profile(run) == PROFILE_GRANTED:
            # Defect recursion re-enters execute_task(); validate the bound grant
            # before this failure handler mutates signatures/repair rounds/state.
            await self._authorize_granted_execution(run, str(task.get("code") or ""))
        sig = failure_signature(output or kind)
        if task["signatures"] and task["signatures"][-1] == sig:
            kind = "任务描述问题"
        task["signatures"].append(sig)
        task["prev_output"] = output
        extra = {"kind": kind}
        task["last_error"] = output or kind
        extra["error"] = task["last_error"]
        if kind == "代码缺陷":
            task["repair_rounds"] = int(task.get("repair_rounds") or 0) + 1
            limit = int((run.limits.get("orchestrator") or {}).get("max_repair_rounds") or 6)
            if task["repair_rounds"] >= limit:
                event = "repair_exceeded" if can_transition(task["state"], "repair_exceeded") else "budget_or_stuck"
                self._set_state(run, task, event, extra=extra)
            else:
                if task["state"] == "verifying":
                    self._set_state(run, task, "defect_repair", extra=extra)
                return await self.execute_task(run, card.code)
        elif kind == "任务描述问题":
            event = "task_issue" if can_transition(task["state"], "task_issue") else "budget_or_stuck"
            self._set_state(run, task, event, extra=extra)
            result = self._gate(run, "重排提案", {"task": card.code, "kind": kind})
            result["kind"] = kind
            return result
        elif kind == "环境故障":
            event = "env_fail" if can_transition(task["state"], "env_fail") else "env_or_conflict"
            self._set_state(run, task, event, extra=extra)
        else:
            event = "task_issue" if can_transition(task["state"], "task_issue") else "budget_or_stuck"
            self._set_state(run, task, event, extra=extra)
        if task.get("conflict_resolve"):
            origin = run.tasks.get(str(task.get("conflict_of") or ""))
            if origin:
                origin["last_error"] = "冲突解决失败"
                if can_transition(origin["state"], "conflict_failed"):
                    self._set_state(run, origin, "conflict_failed", extra={"kind": "合并冲突"})
        return {"state": task["state"], "kind": kind}

    def _dep_outputs(self, run: RunState, card: TaskCard) -> list[dict[str, Any]]:
        outs = []
        for dep in card.depends_on:
            other = run.tasks.get(dep)
            if other:
                outs.append({"code": dep, "state": other["state"], "evidence": other.get("evidence") or []})
        return outs

    async def _run_regression(self, run: RunState, repo: Path, code: str = "") -> dict[str, Any]:
        self._require_execution_safety(run, code)
        if run_execution_profile(run) == PROFILE_GRANTED:
            raise GrantRejected(
                "granted_force_pass_disabled",
                "granted_v1 runs never use the legacy regression/force-pass path",
                status_code=409,
            )
        _ = code
        patterns = self._judge_patterns()
        timeout = int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600)
        env_allow = list(self.profile.get("env_allowlist") or ["PATH"])
        whitelist = self._whitelist()
        commands: list[list[str]] = []
        for task in run.tasks.values():
            if task["state"] != "done":
                continue
            card = TaskCard.model_validate(task["card"])
            for check in card.acceptance:
                commands.append(list(check.cmd))
        test_cmd = self.profile.get("test_command")
        if test_cmd:
            commands.append(list(test_cmd))
        if not commands:
            return {"ok": True, "reason": ""}
        for cmd in commands:
            try:
                out = await run_command(
                    cmd,
                    cwd=repo,
                    whitelist=whitelist,
                    timeout=timeout,
                    env_allow=env_allow,
                    forbidden=self._forbidden(),
                )
            except CommandDenied as exc:
                return {"ok": False, "reason": str(exc)}
            code_i = 1 if out.get("exit_code") is None else int(out.get("exit_code"))
            judged = judge_output(code_i, str(out.get("output") or ""), patterns)
            if not judged["passed"]:
                return {"ok": False, "reason": out.get("output") or "regression failed"}
        return {"ok": True, "reason": ""}

    async def _apply_replan(self, run: RunState, payload: dict[str, Any]) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        design = DesignDoc.model_validate(run.artifacts["design"])
        with self._usage_scope(run):
            graph = await call_agent(
                "decomposer",
                {"spec": spec.model_dump(), "design": design.model_dump(), "rewrite": payload},
                registry=self.registry,
                gateway=self._gateway_for(run),
            )
        self._require_model(graph, TaskGraph, "decomposer")
        result = propose_replan(graph, spec, design, int((run.limits.get("plan") or {})["capacity_points"]))
        if not result["ok"]:
            return {"status": "replan_failed", "errors": result["errors"]}
        for task in run.tasks.values():
            if task["state"] not in {"done", "skipped", "cancelled"} and can_transition(task["state"], "cancel"):
                self._set_state(run, task, "cancel")
        run.artifacts["plan"] = graph.model_dump()
        self._materialize_tasks(run)
        return {"status": "replanned", "tasks": list(run.tasks)}

    async def control_task(
        self,
        run: RunState,
        code: str,
        action: str,
        expected_revision: int,
        reason: str,
        actor: str = "owner",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Retry/resume/takeover can re-enter the model or scheduler. On a retired
        # DeepSeek-only run they must fail clearly instead of silently using 百炼.
        if action in {"retry", "resume", "skip", "force-pass", "takeover", "submit-takeover"}:
            self._reject_retired(run)
        task = run.tasks[code]
        if action in {"retry", "submit-takeover", "force-pass", "takeover"}:
            # Reject before changing state/revisions or creating a worktree: a
            # granted run must not be half-way through a control action while
            # the safety gate is closed.
            self._require_execution_authorization(run, "execute")
            self._require_execution_safety(run, code)
        if run_execution_profile(run) == PROFILE_GRANTED:
            # Same boundary as execute_task: retry is authorized before state
            # changes, and the legacy takeover/force-pass paths stay unreachable.
            if action == "retry":
                await self._authorize_granted_execution(run, code)
            elif action in {"submit-takeover", "takeover"}:
                raise GrantRejected(
                    "granted_manual_merge_disabled",
                    "granted_v1 runs cannot use the legacy takeover workspace or merge",
                    status_code=409,
                )
            elif action == "force-pass":
                raise GrantRejected(
                    "granted_force_pass_disabled",
                    "granted_v1 runs cannot bypass verification with a legacy force-pass",
                    status_code=409,
                )
        if task["revision"] != expected_revision:
            raise RevisionConflict("revision mismatch")
        require_control(action, task["state"], reason=reason)
        prev = task["state"]
        extra = payload or {}
        if action == "pause":
            task["paused"] = True
        elif action == "resume":
            task["paused"] = False
        elif action == "retry":
            event = "retry" if task["state"] == "failed" else "human_retry"
            self._set_state(run, task, event, reason=reason, actor=actor)
            run.revision += 1
            self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
            return await self.execute_task(run, code)
        elif action == "skip":
            self._set_state(run, task, "human_skip", reason=reason, actor=actor)
            if extra.get("downstream", "continue") == "continue":
                run.skip_continue.add(code)
        elif action == "takeover":
            task["locked_by"] = actor
            repo = self.data_dir / "runs" / run.id / "repo"
            if not (repo / ".git").exists():
                init_repo_sync(repo, self.profile.get("initial_files"))
            wt = self.data_dir / "runs" / run.id / "wt" / code
            if not wt.exists():
                create_worktree(repo, wt, f"task/{code}")
            task["takeover_workspace"] = str(wt)
        elif action == "submit-takeover":
            task["takeover_submit"] = True
            task["revision"] += 1
            run.revision += 1
            self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
            return await self._submit_takeover(run, code)
        elif action == "force-pass":
            repo = self.data_dir / "runs" / run.id / "repo"
            if repo.exists():
                regression = await self._run_regression(run, repo)
                if not regression["ok"]:
                    raise ValidationFailed("集成回归失败，不能强制通过")
            self._set_state(run, task, "force_pass", reason=reason, actor=actor)
            task["evidence"].append({"kind": "manual", "summary": reason, "path": ""})
        elif action == "patch":
            raise ValidationFailed("patch 本轮未实现，见 Handoff")
        task["revision"] += 1
        run.revision += 1
        self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
        self._refresh_ready(run)
        return task

    def set_run_control(self, run: RunState, action: str, actor: str = "owner", *, confirm: bool = False) -> RunState:
        if action == "terminate" and not confirm:
            raise ValidationFailed("终止运行需二次确认")
        if action == "pause":
            run.paused = True
            # P5: invalidate in-flight generations so late replies are dropped.
            self._generations.bump(run.id)
        elif action == "resume":
            # Resuming a retired DeepSeek-only run would let the loop call the retired
            # provider; keep it read-only. Pause/terminate stay available.
            self._reject_retired(run)
            run.paused = False
        elif action == "terminate":
            run.status = "terminated"
            run.paused = True
            self._generations.bump(run.id)
            if run.artifacts.get("design_input_status") == "importing":
                generation = int(run.artifacts.get("design_input_generation") or 0)
                self._fail_import(run, generation, "整理已取消。供应商可能仍会计费。")
            self._cancel_import_task(run.id)
            for task in run.tasks.values():
                if task["state"] not in {"done", "skipped", "cancelled"} and can_transition(task["state"], "cancel"):
                    self._set_state(run, task, "cancel", actor=actor)
        run.revision += 1
        self.emit(run, f"control.{action}", "", {"status": run.status, "paused": run.paused}, actor)
        return run

    async def _submit_takeover(self, run: RunState, code: str) -> dict[str, Any]:
        self._require_execution_safety(run, code)
        if run_execution_profile(run) == PROFILE_GRANTED:
            raise GrantRejected(
                "granted_manual_merge_disabled",
                "granted_v1 runs cannot submit a legacy takeover merge",
                status_code=409,
            )
        task = run.tasks[code]
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        wt = Path(task.get("takeover_workspace") or (self.data_dir / "runs" / run.id / "wt" / code))
        if not wt.exists():
            create_worktree(repo, wt, f"task/{code}")
            task["takeover_workspace"] = str(wt)
        if task["state"] == "ready":
            self._set_state(run, task, "scheduled")
        with self._usage_scope(run, task):
            return await self._accept_review_merge(run, code, wt, None)

    def todos(self, run: RunState) -> list[dict[str, Any]]:
        items = [g for g in run.gates if g["status"] == "pending"]
        for task in run.tasks.values():
            if task["state"] == "needs_human":
                items.append({"kind": "needs_human", "task": task["code"]})
        if run.pending_human:
            items.append({"kind": "pending_human", "revision": run.revision})
        return items

    def monitor_snapshot(self, run: RunState) -> dict[str, Any]:
        snapshot = build_monitor_snapshot(run, self.models, self.registry)
        snapshot["workflow"] = self.workflow_projection(run)
        return snapshot

    def workflow_projection(self, run: RunState | None, discussion: Any | None = None) -> dict[str, Any]:
        """Read-only workflow view (stage/blocked/baseline) for API responses."""
        from app.workflow.evidence import evidence_for_run
        from app.workflow.projection import project_workflow_projection

        evidence = evidence_for_run(self, run) if run is not None else {}
        return project_workflow_projection(
            discussion=discussion,
            run=run,
            model_mode=evidence.get("model_mode", "not_run"),
            execution_mode=evidence.get("execution_mode", "not_run"),
            evidence=evidence,
        ).to_dict()

    def budget(self, run: RunState) -> dict[str, Any]:
        orch = run.limits.get("orchestrator") or {}
        limit = int(orch.get("run_token_budget") or 0)
        info = check_budget(run.tokens_used, limit, warn_ratio=float(orch.get("warn_ratio") or 0.8))
        info["used"] = run.tokens_used
        info["limit"] = limit
        info["per_point"] = int(orch.get("tokens_per_point") or 1_500_000)
        return info

    async def accept(self, run: RunState) -> dict[str, Any]:
        self._reject_retired(run)
        self._require_execution_authorization(run, "accept")
        self._require_execution_safety(run)
        if run_execution_profile(run) == PROFILE_GRANTED:
            raise GrantRejected(
                "granted_acceptance_disabled",
                "granted_v1 runs cannot use the legacy acceptance path",
                status_code=409,
            )
        self._maybe_tasks_complete(run)
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        items: list[AcceptanceItem] = []
        for feat in list(spec.features) + list(spec.nonfunc):
            related = [t for t in run.tasks.values() if feat.code in t["card"]["sources"]]
            result = "未验证"
            evidence = ""
            reason = ""
            if related:
                ok, evidence, reason = await self._verify_spec_item(repo, related)
                result = "通过" if ok else "未通过"
            if any(feat.manual) and feat.priority == "P0" and result != "通过":
                reason = reason or "P0 人工项未填写理由"
            items.append(
                AcceptanceItem(
                    code=feat.code,
                    kind=feat.kind,
                    priority=feat.priority,
                    result=result,
                    evidence_path=evidence,
                    manual=any(feat.manual) if feat.manual else False,
                    tasks=[t["code"] for t in related],
                    reason=reason,
                )
            )
        report = AcceptanceReport(
            features=[i for i in items if i.kind == "功能"],
            nonfunc=[i for i in items if i.kind == "非功能"],
            matrix=run.trace.matrix(),
        )
        run.artifacts["acceptance"] = report.model_dump()
        passed = acceptance_pass(report, {"p1_pass_ratio": float((run.limits.get("acceptance") or {})["p1_pass_ratio"])})
        gate = self._gate(run, "验收确认", {"pass": passed, "report": report.model_dump()})
        if not passed:
            await self._spawn_acceptance_defects(run, items)
        return gate

    async def _spawn_acceptance_defects(self, run: RunState, items: list[AcceptanceItem]) -> None:
        cycles = int(run.artifacts.get("accept_fix_cycles") or 0)
        max_cycles = int((run.limits.get("acceptance") or {}).get("max_fix_cycles") or 2)
        if cycles >= max_cycles:
            return
        run.artifacts["accept_fix_cycles"] = cycles + 1
        for item in items:
            if item.result != "未通过":
                continue
            try:
                await self.submit_cr(
                    run,
                    f"验收未通过 {item.code}: {item.reason or item.code}",
                    [item.code],
                    kind="小变更",
                    source="acceptance",
                )
            except Exception:  # noqa: BLE001
                continue

    async def _verify_spec_item(self, repo: Path, related: list[dict[str, Any]]) -> tuple[bool, str, str]:
        outputs: list[str] = []
        ok = True
        reason = ""
        evidence = str(repo)
        for task in related:
            card = TaskCard.model_validate(task["card"])
            if not card.acceptance:
                ok = False
                reason = "无验收命令"
                continue
            for check in card.acceptance:
                try:
                    out = await run_command(
                        list(check.cmd),
                        cwd=repo,
                        whitelist=self._whitelist(),
                        timeout=int(self.limits["orchestrator"]["attempt_timeout_s"]),
                        env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                        forbidden=self._forbidden(),
                    )
                except CommandDenied as exc:
                    ok = False
                    reason = str(exc)
                    outputs.append(str(exc))
                    continue
                code_i = 1 if out.get("exit_code") is None else int(out.get("exit_code"))
                judged = judge_output(code_i, str(out.get("output") or ""), self._judge_patterns())
                outputs.append(str(out.get("output") or ""))
                evidence = str(repo / f"accept-{task['code']}.log")
                (repo / f"accept-{task['code']}.log").write_text(str(out.get("output") or ""), encoding="utf-8")
                if not judged["passed"]:
                    ok = False
                    reason = reason or (out.get("output") or "未通过")
        return ok, evidence, reason or ("\n".join(outputs)[:200] if not ok else "")

    async def submit_cr(self, run: RunState, description: str, impact_codes: list[str], **flags: Any) -> dict[str, Any]:
        self._reject_retired(run)
        open_crs = [c for c in run.crs if c.get("status") not in {"closed", "rejected", "applied"}]
        if len(open_crs) >= int((run.limits.get("change") or {}).get("max_open") or 3):
            run.artifacts.setdefault("cr_queue", []).append({"description": description, "codes": impact_codes, **flags})
            return {"queued": True, "queue_size": len(run.artifacts["cr_queue"])}
        impact = run.trace.impact(impact_codes)
        impact.update(flags)
        kind = str(flags.get("kind") or "")
        level = classify_cr(impact, kind)
        scores: list[int] = []
        any_red = bool(flags.get("red_line"))
        any_block = bool(flags.get("blocking"))
        with self._usage_scope(run):
            for role in ("eval_value", "eval_impact", "eval_risk"):
                try:
                    score = await call_agent(
                        role,
                        {"change_request": {"description": description, "kind": kind}, "impact": impact, "baseline": run.artifacts.get("spec")},
                        registry=self.registry,
                        gateway=self._gateway_for(run),
                    )
                    scores.append(int(getattr(score, "score", 0)))
                    any_red = any_red or bool(getattr(score, "red_line", False))
                    any_block = any_block or bool(getattr(score, "blocking", False))
                except Exception:  # noqa: BLE001
                    break
        ok, ev_flags = evaluation_pass(scores, any_red_line=any_red, any_blocking=any_block)
        code = run.ids.next("CR")
        cr = {
            "code": code,
            "description": description,
            "impact": impact,
            "level": level,
            "kind": kind,
            "source": str(flags.get("source") or ""),
            "status": "analyzed",
            "eval_ok": ok,
            "eval_flags": ev_flags,
            "scores": scores,
        }
        run.crs.append(cr)
        return self._gate(run, "变更决定", {"cr": cr})

    async def decide_cr(self, run: RunState, payload: dict[str, Any]) -> dict[str, Any]:
        self._reject_retired(run)
        code = payload.get("code")
        if not code:
            for gate in reversed(run.gates):
                if gate.get("kind") != "变更决定":
                    continue
                candidate = ((gate.get("payload") or {}).get("cr") or {}).get("code")
                match = next((item for item in run.crs if item["code"] == candidate), None)
                if match and match.get("status") not in {"rejected", "applied", "closed"}:
                    code = candidate
                    break
        cr = next((item for item in run.crs if item["code"] == code), None)
        if cr is None:
            raise ValidationFailed("变更单不存在")
        cr["decision"] = payload.get("decision")
        cr["status"] = "decided"
        flags = cr.get("eval_flags") or {}
        if flags.get("red_line") or flags.get("blocking"):
            cr["eval_ok"] = False
        if cr["decision"] != "批准":
            cr["status"] = "rejected"
            return cr
        for code in cr["impact"].get("downstream", []):
            if code not in run.tasks:
                continue
            task = run.tasks[code]
            if task["state"] == "done":
                self._set_state(run, task, "change_impact")
            elif task["state"] == "running":
                task["paused"] = True
                self.emit(run, "task.state_changed", code, {"code": code, "to": task["state"], "event": "change_pause"})
        await self._apply_incremental_docs(run, cr)
        if cr.get("status") != "rewrite_failed":
            cr["status"] = "applied"
        return cr

    def _affected_codes(self, cr: dict[str, Any]) -> set[str]:
        impact = cr.get("impact") or {}
        codes: set[str] = set()
        for key in ("codes", "downstream", "upstream", "features", "modules", "tasks"):
            for item in impact.get(key) or []:
                codes.add(str(item))
        return codes

    def _next_doc_version(self, run: RunState) -> str:
        best = (1, 0)
        for kind in ("SPEC", "DESIGN", "PLAN"):
            raw = str(run.artifacts.get(f"baseline_{kind}") or "1.0")
            parts = raw.split(".")
            try:
                major = int(parts[0])
                minor = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                major, minor = 1, 0
            if (major, minor) > best:
                best = (major, minor)
        return f"{best[0]}.{best[1] + 1}"

    def _splice_affected(self, old: dict[str, Any], new: dict[str, Any], affected: set[str], fields: tuple[str, ...]) -> dict[str, Any]:
        result = copy.deepcopy(old)
        for section in fields:
            old_items = [item for item in (result.get(section) or []) if isinstance(item, dict)]
            new_items = [item for item in (new.get(section) or []) if isinstance(item, dict)]
            new_by_code = {str(item.get("code") or ""): item for item in new_items if item.get("code")}
            spliced: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in old_items:
                code = str(item.get("code") or "")
                if code in affected:
                    if code in new_by_code:
                        spliced.append(new_by_code[code])
                        seen.add(code)
                    continue
                spliced.append(item)
                if code:
                    seen.add(code)
            for item in new_items:
                code = str(item.get("code") or "")
                if code and code not in seen:
                    spliced.append(item)
                    seen.add(code)
            result[section] = spliced
        return result

    async def _apply_incremental_docs(self, run: RunState, cr: dict[str, Any]) -> None:
        version = self._next_doc_version(run)
        affected = self._affected_codes(cr)
        note = {"code": cr["code"], "description": cr.get("description"), "version": version}
        rewrite_payload = {"change_request": cr, "affected": sorted(affected)}
        writers = (
            ("SPEC", "spec", ("features", "nonfunc"), "spec_writer", SpecDoc),
            ("DESIGN", "design", ("modules", "interfaces"), "architect", DesignDoc),
            ("PLAN", "plan", ("tasks",), "decomposer", TaskGraph),
        )
        with self._usage_scope(run):
            for kind, key, fields, role, expected in writers:
                doc = run.artifacts.get(key)
                if not isinstance(doc, dict):
                    continue
                if key == "design" and not isinstance(run.artifacts.get("spec"), dict):
                    continue
                if key == "plan" and not isinstance(run.artifacts.get("design"), dict):
                    continue
                prev = str(run.artifacts.get(f"baseline_{kind}") or "1.0")
                if f"{key}_{prev}" not in run.artifacts:
                    run.artifacts[f"{key}_{prev}"] = copy.deepcopy(doc)
                before = copy.deepcopy(doc)
                rewritten, errors = await self._write_checked(
                    run,
                    role,
                    self._incremental_inputs(run, cr, rewrite_payload, role),
                    lambda item, _old=before, _kind=kind: self._incremental_check(
                        {
                            "SPEC": lambda doc: self._check_spec_doc(run, doc),
                            "DESIGN": lambda doc: self._check_design_doc(run, doc),
                            "PLAN": lambda doc: self._check_plan_doc(run, doc),
                        }[_kind],
                        _old,
                        item,
                    ),
                    expected,
                    max_rewrites=self._max_rewrites(run, "spec"),
                )
                if errors or rewritten is None:
                    cr["status"] = "rewrite_failed"
                    cr["errors"] = errors
                    return
                checker = {
                    "SPEC": lambda doc: self._check_spec_doc(run, doc),
                    "DESIGN": lambda doc: self._check_design_doc(run, doc),
                    "PLAN": lambda doc: self._check_plan_doc(run, doc),
                }[kind]
                merged = self._splice_affected(before, rewritten.model_dump(), affected, fields)
                self._assert_unaffected(before, merged, affected, fields)
                try:
                    model = expected.model_validate(merged)
                    merge_errors = self._incremental_check(checker, before, model)
                except Exception as exc:  # noqa: BLE001
                    merge_errors = [str(exc)]
                if merge_errors:
                    cr["status"] = "rewrite_failed"
                    cr["errors"] = merge_errors
                    return
                for section in fields:
                    for item in merged.get(section) or []:
                        if isinstance(item, dict) and item.get("code") in affected:
                            item.setdefault("change_notes", []).append(note)
                run.artifacts[key] = merged
                run.artifacts[f"{key}_{version}"] = copy.deepcopy(merged)
                run.artifacts[f"baseline_{kind}"] = version
                self.emit(run, "baseline.frozen", kind, {"version": version, "cr": cr["code"]})
        cr["applied_version"] = version
        self._sync_affected_task_cards(run, affected)

    def _incremental_inputs(self, run: RunState, cr: dict[str, Any], rewrite_payload: dict[str, Any], role: str) -> dict[str, Any]:
        payload = {**rewrite_payload, "change_request": cr}
        if role == "spec_writer":
            return {
                "idea_card": run.artifacts.get("idea_card") or {},
                "proposal": run.artifacts.get("proposal") or {},
                "issue_list": run.artifacts.get("issues") or [],
                "review_sheet": run.artifacts.get("reviews") or [],
                "rewrite": {**payload, "old": run.artifacts.get("spec")},
                "change_request": cr,
                "baseline": run.artifacts.get("spec"),
            }
        if role == "architect":
            return {"spec": run.artifacts.get("spec"), "rewrite": {**payload, "old": run.artifacts.get("design")}, "change_request": cr, "baseline": run.artifacts.get("design")}
        return {"spec": run.artifacts.get("spec"), "design": run.artifacts.get("design"), "rewrite": {**payload, "old": run.artifacts.get("plan")}, "change_request": cr, "baseline": run.artifacts.get("plan")}

    def _check_spec_doc(self, run: RunState, doc: SpecDoc) -> list[str]:
        issues = [Issue.model_validate(i) for i in (run.artifacts.get("issues") or [])]
        sheets = [ReviewSheet.model_validate(s) for s in (run.artifacts.get("reviews") or [])]
        return check_spec(doc, issues, sheets or None)

    def _check_design_doc(self, run: RunState, doc: DesignDoc) -> list[str]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        issues = [Issue.model_validate(i) for i in (run.artifacts.get("issues") or [])]
        return check_design(doc, spec, issues, max_modules=int((run.limits.get("design") or {})["max_modules"]))

    def _check_plan_doc(self, run: RunState, doc: TaskGraph) -> list[str]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        design = DesignDoc.model_validate(run.artifacts["design"])
        return check_task_graph(doc, spec, design, int((run.limits.get("plan") or {})["capacity_points"]))

    def _incremental_check(self, checker: Callable[[Any], list[str]], old_dump: dict[str, Any], new_doc: Any) -> list[str]:
        try:
            old_model = type(new_doc).model_validate(old_dump)
            old_errors = set(checker(old_model))
        except Exception:  # noqa: BLE001
            return []
        return [err for err in checker(new_doc) if err not in old_errors]

    def _assert_unaffected(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        affected: set[str],
        fields: tuple[str, ...],
    ) -> None:
        for section in fields:
            old_items = {item.get("code"): item for item in (before.get(section) or []) if isinstance(item, dict)}
            new_items = {item.get("code"): item for item in (after.get(section) or []) if isinstance(item, dict)}
            for code, old in old_items.items():
                if code in affected:
                    continue
                new = new_items.get(code)
                if json.dumps(old, sort_keys=True, ensure_ascii=False) != json.dumps(new, sort_keys=True, ensure_ascii=False):
                    raise ValidationFailed(f"未受影响条目被改写: {code}")

    async def import_feedback(self, run: RunState, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        self._reject_retired(run)
        with self._usage_scope(run):
            return await self._import_feedback_body(run, rows, key)

    async def _import_feedback_body(self, run: RunState, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        imported = []
        for row in rows:
            masked = mask_text(row.get("text") or "")
            item = {
                "id": len(run.raw_feedback) + 1,
                "text": masked,
                "text_masked": masked,
                "author_hash": hash_author(row.get("author") or "anon", key),
                "source": row.get("source") or "manual",
            }
            run.raw_feedback.append(item)
            imported.append(item)
        texts = [r["text_masked"] for r in imported]
        try:
            vectors = await self._gateway_for(run).embed(texts)
            if not vectors or len(vectors) != len(texts) or any(not vec for vec in vectors):
                raise RuntimeError("embedding unavailable")
            groups = cluster(vectors, threshold=float((run.limits.get("listening") or {}).get("cluster_threshold") or 0.78))
        except Exception:  # noqa: BLE001
            groups = await self._cluster_fast(run, texts)
        if not groups:
            groups = [[idx] for idx in range(len(imported))]
        known_texts = []
        for issue in run.artifacts.get("issues") or []:
            if issue.get("destination") == "本版不做" or issue.get("status") in {"待定", "未讨论"}:
                known_texts.append(issue.get("text") or "")
                known_texts.append(issue.get("code") or "")
        keywords = list((run.limits.get("listening") or {}).get("known_keywords") or [])
        group_payload = []
        for members in groups:
            group_payload.append(
                {
                    "quotes": [imported[i]["id"] for i in members],
                    "texts": [imported[i]["text_masked"] for i in members],
                    "authors": list({imported[i]["author_hash"] for i in members}),
                }
            )
        distilled: list[dict[str, Any]] = []
        try:
            batch = await call_agent("distiller", {"feedback_group": group_payload}, registry=self.registry, gateway=self._gateway_for(run))
            distilled = list(getattr(batch, "items", None) or [])
        except Exception:  # noqa: BLE001
            distilled = []
        scores: dict[str, Any] = {}
        any_red = False
        if distilled:
            for role in ("fb_eval_value", "fb_eval_cost", "fb_eval_risk"):
                try:
                    score = await call_agent(
                        role,
                        {"feedback_group": distilled, "baseline": run.artifacts.get("spec")},
                        registry=self.registry,
                        gateway=self._gateway_for(run),
                    )
                    scores[getattr(score, "dimension", role)] = int(getattr(score, "score", 0))
                    any_red = any_red or bool(getattr(score, "red_line", False))
                except Exception:  # noqa: BLE001
                    break
        raw_by_id = {row["id"]: row["text_masked"] for row in imported}
        for idx, members in enumerate(groups):
            texts = [imported[i]["text_masked"] for i in members]
            authors = {imported[i]["author_hash"] for i in members}
            agent_item = distilled[idx] if idx < len(distilled) else {}
            item = {
                "code": run.ids.next("FB"),
                "category": agent_item.get("category") or "",
                "summary": agent_item.get("summary") or "",
                "quotes": agent_item.get("quotes") or [imported[i]["id"] for i in members],
                "count": agent_item.get("count") if agent_item.get("count") is not None else len(members),
                "basis": agent_item.get("basis") or "归纳",
                "unique_authors": len(authors),
                "red_line": bool(agent_item.get("red_line") or any_red),
                "known": False,
                "new_direction": bool(agent_item.get("new_direction")),
                "linked_issue": agent_item.get("linked_issue") or "",
            }
            known = match_known(item["summary"] or " ".join(texts), known_texts, keywords=keywords)
            item["known"] = bool(known)
            if known and not item["linked_issue"] and known in {i.get("code") for i in (run.artifacts.get("issues") or [])}:
                item["linked_issue"] = known
            item["distill_errors"] = validate_distill(item, raw_by_id)
            item["route"] = route_feedback(item, scores)
            run.feedback.append(item)
        return imported

    async def _cluster_fast(self, run: RunState, texts: list[str]) -> list[list[int]]:
        try:
            batch = await call_agent(
                "cluster_fast",
                {"feedback_group": [{"index": idx, "text": text} for idx, text in enumerate(texts)]},
                registry=self.registry,
                gateway=self._gateway_for(run),
            )
            groups: list[list[int]] = []
            seen: set[int] = set()
            for raw in getattr(batch, "groups", None) or []:
                cleaned = [int(idx) for idx in raw if 0 <= int(idx) < len(texts) and int(idx) not in seen]
                seen.update(cleaned)
                if cleaned:
                    groups.append(cleaned)
            for idx in range(len(texts)):
                if idx not in seen:
                    groups.append([idx])
            return groups
        except Exception:  # noqa: BLE001
            return [[idx] for idx in range(len(texts))]

    def _doc_check_failed(self, run: RunState, *, retry: str, errors: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"retry": retry, "errors": errors, **(extra or {})}
        return self._gate(run, "文档检查失败", payload)

    def _maybe_tasks_complete(self, run: RunState) -> None:
        if run.status == "terminated":
            return
        if run.engine.current != "7" or not run.tasks:
            return
        if all(task["state"] in {"done", "skipped", "cancelled"} for task in run.tasks.values()):
            run.engine.apply("tasks_complete")
            self.emit(run, "stage.changed", "8", {"event": "tasks_complete"})

    def _sync_affected_task_cards(self, run: RunState, affected: set[str]) -> None:
        plan = run.artifacts.get("plan")
        if not isinstance(plan, dict):
            return
        cards = {str(item.get("code") or ""): item for item in (plan.get("tasks") or []) if isinstance(item, dict) and item.get("code")}
        for code, task in list(run.tasks.items()):
            if task["state"] not in {"stale", "done"}:
                continue
            if code not in affected and task["state"] != "stale":
                continue
            new_card = cards.get(code)
            if new_card:
                task["card"] = copy.deepcopy(new_card)
        for code, card in cards.items():
            if code in run.tasks:
                continue
            run.tasks[code] = {
                "id": f"{run.id}:{code}",
                "code": code,
                "state": "pending",
                "revision": 1,
                "card": copy.deepcopy(card),
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
                "tokens_used": 0,
                "prev_output": "",
                "review_issues": [],
            }
        self._sync_task_ids(run)

    def _gate(self, run: RunState, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        gate = {"id": str(uuid.uuid4()), "kind": kind, "status": "pending", "payload": payload}
        run.gates.append(gate)
        run.status = "waiting"
        run.pending_human = True
        self.emit(run, "gate.created", gate["id"], {"kind": kind})
        return {"status": "need_human", "gate": gate, "stage": run.engine.current, "state": "needs_human"}

    def _apply_verdicts(self, run: RunState, verdicts: list[dict[str, Any]]) -> None:
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        by_code = {i.code: i for i in issues}
        for item in verdicts:
            issue = by_code.get(item["code"])
            if not issue:
                continue
            issue.status = item["status"]
            issue.basis = "人工裁决"
            issue.conclusion = item.get("reason") or issue.conclusion
            if item.get("assumption_unverified"):
                issue.basis = "待真人验证"
        run.artifacts["issues"] = [i.model_dump() for i in issues]

    def _freeze(self, run: RunState, kind: str) -> None:
        if f"baseline_{kind}" not in run.artifacts:
            run.artifacts[f"baseline_{kind}"] = "1.0"
        self.emit(run, "baseline.frozen", kind, {"version": run.artifacts[f"baseline_{kind}"]})


def _deep_merge_limits(dst: dict[str, Any], src: dict[str, Any]) -> None:
    if not isinstance(src, dict):
        raise ValidationFailed("limits patch 必须是对象")
    for key, value in src.items():
        if key not in dst:
            raise ValidationFailed(f"未知限制项: {key}")
        if isinstance(dst[key], dict):
            if not isinstance(value, dict):
                raise ValidationFailed(f"{key} 必须是对象")
            _deep_merge_limits(dst[key], value)
        else:
            dst[key] = value


def _ignore_write_noise(rel: str) -> bool:
    parts = Path(rel).parts
    return any(part in {"__pycache__", ".pytest_cache", ".git"} or part.endswith(".pyc") for part in parts)


def _exc_fields(exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    name = exc.__class__.__name__.lower()
    return {
        "http_status": status,
        "timeout": "timeout" in name or "timeout" in str(exc).lower(),
        "parse_error": isinstance(exc, AgentOutputError) or "parse" in name,
        "env_error": True,
    }
