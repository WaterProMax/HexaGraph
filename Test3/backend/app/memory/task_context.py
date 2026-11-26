"""Task/role scoped manual memory stored inside the run snapshot (M subsystem).

Memory is keyed by ``run_id + task_code + role`` where ``role`` is the task
card role ("coder" or "tester").  There is no bot assignment and no new table:
the payload lives in ``task["role_memory"][role]`` inside ``RunState.tasks`` so
``Workbench._persist_snapshot`` already persists it and the per-run write lock
``bench._run_locks.write_scope`` serializes writers.  Revision bumps are CAS
guarded by the caller-supplied ``expected_revision``.

Permissions follow the project membership table only:

* read  -- any project member;
* write -- the project Leader (``ProjectMembershipRow.is_leader == 1``).

``X-Bot-Id`` is a local identity declaration, not strong authentication, so the
service never treats it as proof beyond the membership lookup.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, cast

from app.agents.task_context import ContextSection
from app.execution.run_lock import RunLockBusy
from app.memory.access import is_project_member
from app.memory.organizer import contains_secret
from app.schemas.docs import TaskCard
from app.schemas.task_agent_memory import (
    TASK_ROLES,
    TaskRole,
    TaskRoleMemoryView,
    TaskRoleSnapshot,
)
from app.settings import CONFIG_DIR
from app.storage.models import ProjectMembershipRow

ROLE_SOURCE_MATCHER_VERSION = "task-role-v1"

# The scheduler holds the per-run write lock for the whole execution batch
# (including agent/model calls), so a memory write must not queue behind it:
# wait only briefly for a concurrent short memory write, otherwise answer
# ``run_busy`` and let the Leader retry after the batch.  No queueing: the edit
# is not applied later behind the user's back.
MEMORY_WRITE_BUSY_SECONDS = 0.5
MAX_MANUAL_CHARS = 4_000
MAX_ROLE_TEXT_CHARS = 2_000
MEMORY_KEY = "role_memory"
_FROZEN_KEYS = ("role", "role_hash", "manual_revision", "context_hash", "memory_context_hash")


class TaskMemoryNotFound(Exception):
    """The run or the task (or its card) does not exist."""


class TaskMemoryForbidden(Exception):
    """The actor is not allowed to read or write this project memory."""


class TaskMemoryConflict(Exception):
    """A domain conflict; ``code`` is "revision_conflict", "role_mismatch", ...

    Content validation failures (too long, secret-like) use the same type with
    their own code so callers can map the code to HTTP 409 or 422 uniformly.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- deterministic helpers ---------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_task_card(card: dict[str, Any]) -> str:
    """Canonical JSON for the full task card (sorted keys, compact separators)."""

    return json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def task_role(run: Any, task_code: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return ``(task, card, role)`` for ``task_code`` or raise NotFound."""

    task = run.tasks.get(task_code)
    if not isinstance(task, dict):
        raise TaskMemoryNotFound(f"task not found: {task_code}")
    card = task.get("card")
    if not isinstance(card, dict):
        raise TaskMemoryNotFound(f"task card not found: {task_code}")
    role = card.get("role")
    if role not in TASK_ROLES:
        # Tolerate a minimally materialized card: the schema is the fallback
        # authority for the role field, but nothing else is invented here.
        try:
            role = TaskCard.model_validate(card).role
        except Exception as exc:  # noqa: BLE001 - malformed cards are not found
            raise TaskMemoryNotFound(f"task card has no valid role: {task_code}") from exc
    return task, card, str(role)


def _roles_yaml_digest() -> str:
    path = CONFIG_DIR / "roles.yaml"
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return _sha256_bytes(b"")


def _acceptance_lines(card: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in card.get("acceptance") or []:
        if isinstance(item, dict):
            cmd = " ".join(str(part) for part in (item.get("cmd") or []))
            lines.append(
                "- cmd: "
                + cmd
                + "; pass_criteria: "
                + str(item.get("pass_criteria") or "")
                + "; from_criterion: "
                + str(item.get("from_criterion") or "")
            )
        else:
            lines.append(f"- {item}")
    return lines or ["- (none)"]


def _role_text(task_code: str, role: str, card: dict[str, Any]) -> str:
    acceptance = "\n".join(_acceptance_lines(card))
    write_set = "\n".join(f"- {item}" for item in (card.get("write_set") or [])) or "- (none)"
    text = (
        f"任务：{task_code}\n"
        f"角色：{role}\n"
        f"标题：{card.get('title') or ''}\n"
        f"描述：{card.get('description') or ''}\n"
        f"验收标准：\n{acceptance}\n"
        f"写入范围：\n{write_set}"
    )
    if len(text) > MAX_ROLE_TEXT_CHARS:
        marker = "\n[自动角色段已截断]"
        text = text[: MAX_ROLE_TEXT_CHARS - len(marker)] + marker
    return text


def _role_source_for(task_code: str, role: str, card: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": _role_text(task_code, role, card),
        "sources": [
            {
                "kind": "task_card",
                "ref": task_code,
                "sha256": _sha256_text(canonical_task_card(card)),
            },
            {
                "kind": "role_definition",
                "ref": role,
                "sha256": _roles_yaml_digest(),
            },
        ],
        "matcher_version": ROLE_SOURCE_MATCHER_VERSION,
    }


def role_source(run: Any, task_code: str) -> dict[str, Any]:
    """Deterministic automatic role block; reads the task card only.

    Bot duties, project membership and role configuration text are deliberately
    not part of the text: only the card identity plus the roles.yaml bytes
    digest are attested here.
    """

    _task, card, role = task_role(run, task_code)
    return _role_source_for(task_code, role, card)


def _section_dict(section: ContextSection) -> dict[str, Any]:
    return {
        "kind": section.kind,
        "source_id": section.source_id,
        "source_version": section.source_version,
        "text": section.text,
        "sha256": section.sha256,
        "summary": section.summary,
    }


def _sections_payload(sections: list[ContextSection]) -> dict[str, Any]:
    return {
        "sections": [
            {
                "kind": section.kind,
                "source_id": section.source_id,
                "source_version": section.source_version,
                "sha256": section.sha256,
                "text": section.text,
            }
            for section in sections
        ]
    }


def context_hash_for_sections(sections: list[ContextSection]) -> str:
    """Canonical hash over the selected sections' metadata and text."""

    return _sha256_text(
        json.dumps(
            _sections_payload(sections),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _role_section(task_code: str, role: str, card: dict[str, Any]) -> ContextSection:
    source = _role_source_for(task_code, role, card)
    return ContextSection.create(
        kind="task_role",
        source_id=f"{task_code}:{role}",
        source_version=ROLE_SOURCE_MATCHER_VERSION,
        text=source["text"],
    )


def _manual_section(task_code: str, role: str, revision: int, manual_text: str) -> ContextSection:
    return ContextSection.create(
        kind="task_manual",
        source_id=f"{task_code}:{role}",
        source_version=str(revision),
        text=manual_text,
    )


# --- memory payload ----------------------------------------------------------


def _default_memory() -> dict[str, Any]:
    return {
        "revision": 0,
        "manual_text": "",
        "manual_updated_by": None,
        "manual_updated_at": None,
        "frozen_context": {},
    }


def _read_memory(task: dict[str, Any], role: str) -> dict[str, Any]:
    """Read-only normalized view of the stored per-role memory payload."""

    default = _default_memory()
    store = task.get(MEMORY_KEY)
    raw = store.get(role) if isinstance(store, dict) else None
    if not isinstance(raw, dict):
        return default
    frozen = raw.get("frozen_context")
    updated_by = raw.get("manual_updated_by")
    updated_at = raw.get("manual_updated_at")
    return {
        "revision": max(0, int(raw.get("revision") or 0)),
        "manual_text": str(raw.get("manual_text") or ""),
        "manual_updated_by": str(updated_by) if updated_by is not None else None,
        "manual_updated_at": str(updated_at) if updated_at is not None else None,
        "frozen_context": dict(frozen) if isinstance(frozen, dict) else {},
    }


def get_memory(run: Any, task_code: str, role: str) -> dict[str, Any]:
    """Return the stored memory payload, defaulting to an empty revision 0."""

    task, _card, card_role = task_role(run, task_code)
    if role != card_role:
        raise TaskMemoryConflict("role_mismatch")
    return _read_memory(task, role)


def _write_memory(task: dict[str, Any], role: str, memory: dict[str, Any]) -> None:
    store = task.get(MEMORY_KEY)
    if not isinstance(store, dict):
        store = {}
        task[MEMORY_KEY] = store
    store[role] = memory


def _attempt_frozen_context(attempt: Any) -> dict[str, Any]:
    """Extract the frozen role metadata from an attempt (nested or merged)."""

    if not isinstance(attempt, dict):
        return {}
    nested = attempt.get("frozen_context")
    source: dict[str, Any] = nested if isinstance(nested, dict) and nested else attempt
    return {key: source[key] for key in _FROZEN_KEYS if source.get(key) is not None}


def _attempt_context_hash(attempt: Any) -> str:
    if not isinstance(attempt, dict):
        return ""
    value = attempt.get("context_hash")
    if value:
        return str(value)
    nested = attempt.get("frozen_context")
    if isinstance(nested, dict) and nested.get("context_hash"):
        return str(nested["context_hash"])
    return ""


def _attempt_role(attempt: Any) -> str:
    if not isinstance(attempt, dict):
        return ""
    if attempt.get("role"):
        return str(attempt["role"])
    nested = attempt.get("frozen_context")
    if isinstance(nested, dict) and nested.get("role"):
        return str(nested["role"])
    return ""


def _effective(
    memory_revision: int, context_hash: str, attempt: Any, role: str
) -> Literal["current", "next_attempt"]:
    if not isinstance(attempt, dict):
        return "current"
    if str(attempt.get("status") or "") not in {"started", "running"}:
        return "current"
    if _attempt_role(attempt) != role:
        return "current"
    frozen = _attempt_frozen_context(attempt)
    frozen_revision = frozen.get("manual_revision")
    try:
        same_revision = frozen_revision is not None and int(frozen_revision) == memory_revision
    except (TypeError, ValueError):
        same_revision = False
    frozen_memory_hash = frozen.get("memory_context_hash") or frozen.get("context_hash")
    if same_revision and frozen_memory_hash == context_hash:
        return "current"
    return "next_attempt"


def _view(
    run: Any,
    task: dict[str, Any],
    card: dict[str, Any],
    role: str,
    *,
    memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full view without performing permission checks or mutation."""

    task_code = str(task.get("code") or card.get("code") or "")
    payload = memory if memory is not None else _read_memory(task, role)
    role_section = _role_section(task_code, role, card)
    sections = [role_section]
    manual_text = str(payload.get("manual_text") or "")
    manual_section: ContextSection | None = None
    if manual_text:
        manual_section = _manual_section(task_code, role, int(payload["revision"]), manual_text)
        sections.append(manual_section)
    context_hash = context_hash_for_sections(sections)
    role_snapshot = TaskRoleSnapshot.model_validate(_role_source_for(task_code, role, card))
    attempt = task.get("attempt")
    attempt_meta = _attempt_frozen_context(attempt)
    frozen = bool(_attempt_role(attempt) == role and _attempt_context_hash(attempt))
    if frozen:
        frozen_context = attempt_meta
    else:
        stored = payload.get("frozen_context")
        frozen_context = dict(stored) if isinstance(stored, dict) else {}
    return TaskRoleMemoryView(
        run_id=str(run.id),
        project_id=str(run.project_id),
        task_code=task_code,
        role=cast(TaskRole, role),
        revision=int(payload["revision"]),
        manual_text=manual_text,
        manual_updated_by=payload.get("manual_updated_by"),
        manual_updated_at=payload.get("manual_updated_at"),
        role_snapshot=role_snapshot,
        manual_section=_section_dict(manual_section) if manual_section is not None else None,
        role_section=_section_dict(role_section),
        context_hash=context_hash,
        frozen=frozen,
        frozen_context=frozen_context,
        effective=_effective(int(payload["revision"]), context_hash, attempt, role),
    ).model_dump()


# --- permission and lookup helpers ------------------------------------------


def _require_run(bench: Any, run_id: str) -> Any:
    run = bench.runs.get(str(run_id))
    if run is None:
        raise TaskMemoryNotFound(f"run not found: {run_id}")
    return run


async def _require_member(bench: Any, project_id: str, actor: str) -> None:
    async with bench.db_session() as session:
        member = await is_project_member(session, project_id, actor)
    if not member:
        raise TaskMemoryForbidden(f"bot {actor} is not a project member")


async def _require_leader(bench: Any, project_id: str, actor: str) -> None:
    async with bench.db_session() as session:
        row = await session.get(ProjectMembershipRow, (project_id, actor))
    if row is None or int(row.is_leader or 0) != 1:
        raise TaskMemoryForbidden(f"bot {actor} is not the project leader")


def _validate_manual_text(manual_text: str) -> str:
    text = str(manual_text or "").strip()
    if len(text) > MAX_MANUAL_CHARS:
        raise TaskMemoryConflict("manual_text_too_long")
    if contains_secret(text):
        raise TaskMemoryConflict("secret_in_manual")
    return text


def _validate_expected(expected_revision: int) -> int:
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise TaskMemoryConflict("invalid_revision") from exc
    if expected < 0:
        raise TaskMemoryConflict("invalid_revision")
    return expected


# --- commit helper -----------------------------------------------------------


def _commit_task_role_memory(
    bench: Any,
    run_id: str,
    task_code: str,
    role: str,
    expected_revision: int,
    *,
    manual_text: str,
    updated_by: str | None,
    updated_at: str | None,
) -> dict[str, Any]:
    """Copy-on-write commit of one role memory entry.

    The caller must already hold ``bench._run_locks.write_scope(run.id)``: the
    helper never acquires a second lock and never awaits, so the read/stage/
    persist/publish sequence is atomic with respect to other writers.

    The canonical run is not mutated until the snapshot write has succeeded.
    The staged task map is only used at serialization time, and on success only
    this task's ``role_memory`` is published back onto the existing task object
    (identity preserved).  On failure the canonical task, its role memory and
    its revision stay exactly as they were.
    """

    current_run = _require_run(bench, run_id)
    task, card, current_role = task_role(current_run, task_code)
    if current_role != role:
        raise TaskMemoryConflict("role_mismatch")
    memory = _read_memory(task, role)
    current_revision = int(memory["revision"])
    if int(expected_revision) != current_revision:
        raise TaskMemoryConflict("revision_conflict")
    updated = {
        **memory,
        "revision": current_revision + 1,
        "manual_text": manual_text,
        "manual_updated_by": updated_by,
        "manual_updated_at": updated_at,
    }
    # Stage a deep copy so the live task graph is untouched until the commit
    # succeeds; only the target role entry is changed inside the copy.
    staged_tasks = copy.deepcopy(current_run.tasks)
    staged_task = staged_tasks.get(task_code)
    if not isinstance(staged_task, dict):
        raise TaskMemoryNotFound(f"task not found: {task_code}")
    _write_memory(staged_task, role, updated)
    # Build and validate the response view before persisting so a foreseeable
    # view error cannot happen after the snapshot was already committed.  The
    # canonical task is equivalent input here: only ``memory`` differs.
    view = _view(current_run, task, card, role, memory=updated)
    bench._persist_snapshot(current_run, tasks_override=staged_tasks)
    # The write is durable now; publish only this role's staged payload back to
    # the existing task object so callers holding a reference keep seeing it.
    staged_store = staged_task.get(MEMORY_KEY)
    if isinstance(staged_store, dict):
        _write_memory(task, role, staged_store[role])
    return view


# --- public service API ------------------------------------------------------


async def read_task_role_memory(
    bench: Any,
    actor: str,
    run_id: str,
    task_code: str,
    role: str,
) -> dict[str, Any]:
    """Return the role memory view; requires project membership."""

    run = _require_run(bench, run_id)
    task, card, card_role = task_role(run, task_code)
    await _require_member(bench, run.project_id, actor)
    if role != card_role:
        raise TaskMemoryConflict("role_mismatch")
    return _view(run, task, card, role)


async def save_task_role_manual(
    bench: Any,
    actor: str,
    run_id: str,
    task_code: str,
    role: str,
    expected_revision: int,
    manual_text: str,
) -> dict[str, Any]:
    """Leader-only CAS write of the manual text for ``(task_code, role)``."""

    run = _require_run(bench, run_id)
    _task, _card, card_role = task_role(run, task_code)
    await _require_leader(bench, run.project_id, actor)
    if role != card_role:
        raise TaskMemoryConflict("role_mismatch")
    text = _validate_manual_text(manual_text)
    expected = _validate_expected(expected_revision)
    try:
        async with bench._run_locks.write_scope(
            run.id, busy_timeout=MEMORY_WRITE_BUSY_SECONDS
        ):
            return _commit_task_role_memory(
                bench,
                run_id,
                task_code,
                role,
                expected,
                manual_text=text,
                updated_by=actor,
                updated_at=_now_iso(),
            )
    except RunLockBusy as exc:
        raise TaskMemoryConflict("run_busy") from exc


async def delete_task_role_manual(
    bench: Any,
    actor: str,
    run_id: str,
    task_code: str,
    role: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Leader-only CAS clear of the manual text; the revision still advances."""

    run = _require_run(bench, run_id)
    _task, _card, card_role = task_role(run, task_code)
    await _require_leader(bench, run.project_id, actor)
    if role != card_role:
        raise TaskMemoryConflict("role_mismatch")
    expected = _validate_expected(expected_revision)
    try:
        async with bench._run_locks.write_scope(
            run.id, busy_timeout=MEMORY_WRITE_BUSY_SECONDS
        ):
            return _commit_task_role_memory(
                bench,
                run_id,
                task_code,
                role,
                expected,
                manual_text="",
                updated_by=None,
                updated_at=None,
            )
    except RunLockBusy as exc:
        raise TaskMemoryConflict("run_busy") from exc


def build_task_role_sections(
    bench: Any,
    run: Any,
    task_code: str,
) -> tuple[list[ContextSection], dict[str, Any]]:
    """Return ``([role_section, manual_section?], meta)`` for the I1 assembler.

    Read-only: the method never creates ``role_memory`` entries, never touches
    attempts and never persists anything.  ``bench`` is accepted for symmetry
    with the other service entry points; the data is entirely in the run.
    """

    del bench  # no I/O is required to assemble memory sections
    task, card, role = task_role(run, task_code)
    memory = _read_memory(task, role)
    role_section = _role_section(str(task.get("code") or task_code), role, card)
    sections = [role_section]
    manual_text = str(memory["manual_text"] or "")
    if manual_text:
        sections.append(
            _manual_section(str(task.get("code") or task_code), role, int(memory["revision"]), manual_text)
        )
    memory_context_hash = context_hash_for_sections(sections)
    meta = {
        "role": role,
        "role_hash": role_section.sha256,
        "manual_revision": int(memory["revision"]),
        "context_hash": memory_context_hash,
        "memory_context_hash": memory_context_hash,
    }
    return sections, meta


def freeze_role_meta(bench: Any, run: Any, task_code: str) -> dict[str, Any]:
    """Return the metadata root attaches to a task attempt; ``{}`` if absent."""

    try:
        _sections, meta = build_task_role_sections(bench, run, task_code)
    except (TaskMemoryNotFound, TaskMemoryConflict):
        return {}
    return meta


__all__ = [
    "MAX_MANUAL_CHARS",
    "MEMORY_KEY",
    "ROLE_SOURCE_MATCHER_VERSION",
    "TaskMemoryConflict",
    "TaskMemoryForbidden",
    "TaskMemoryNotFound",
    "build_task_role_sections",
    "canonical_task_card",
    "context_hash_for_sections",
    "delete_task_role_manual",
    "freeze_role_meta",
    "get_memory",
    "read_task_role_memory",
    "role_source",
    "save_task_role_manual",
    "task_role",
]