"""Step-level execution traces for task attempts.

Observability only: recording never changes tool permissions, the model pin,
authorisation verdicts or the task write set, and it is **fail-open** — an
observability failure must never fail the task it observes.

Steps live on ``task["attempt"]["execution_steps"]`` and are frozen into
``attempt_history`` by the existing deep-copy in ``_finish_attempt``.  Each step
is also pushed on the run EventBus as ``task.llm_step`` / ``task.tool_step`` /
``task.granted_command``.  The read API is
``GET /api/runs/{run_id}/tasks/{task_code}/execution-trace``.

Redaction/truncation rules (locked here, asserted by tests):

* file *contents* never enter a summary — only path, character count and the
  first 12 hex chars of the content sha256;
* ``run_command`` keeps argv plus a clipped output;
* ``read_file`` / ``list_dir`` keep a path, a short preview and a capped listing;
* an LLM step records each message's role and length plus one clipped preview of
  the last user message — never the full prompt or context block;
* every field is clipped to :data:`FIELD_LIMIT` Unicode characters and flagged
  with ``truncated``;
* ``***REDACTED***`` replaces environment secret values and ``sk-`` shaped
  values instead of failing the task.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

FIELD_LIMIT = 500
PREVIEW_LIMIT = 200
LISTING_LIMIT = 20
SHA_CHARS = 12

EXECUTION_PATH_LEGACY = "legacy_tool_agent"
EXECUTION_PATH_GRANTED = "granted_v1"
EXECUTION_PATH_SIMULATED = "simulated"
EXECUTION_PATHS = frozenset(
    {EXECUTION_PATH_LEGACY, EXECUTION_PATH_GRANTED, EXECUTION_PATH_SIMULATED}
)

KIND_LLM = "llm"
KIND_TOOL = "tool"
KIND_GRANTED_COMMAND = "granted_command"
STEP_KINDS = (KIND_LLM, KIND_TOOL, KIND_GRANTED_COMMAND)

EVENT_FOR_KIND = {
    KIND_LLM: "task.llm_step",
    KIND_TOOL: "task.tool_step",
    KIND_GRANTED_COMMAND: "task.granted_command",
}

# ``sk-`` shaped values are redacted even when no environment secret matches, so
# a scripted/test provider cannot leak a key into the trace.
_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{3,}")
_REDACTED = "***REDACTED***"

# Tool names whose payloads are summarised field by field instead of dumped.
_WRITE_TOOLS = frozenset({"write_file"})
_COMMAND_TOOLS = frozenset({"run_command"})
_READ_TOOLS = frozenset({"read_file"})
_LIST_TOOLS = frozenset({"list_dir"})

#: Signature of the callback ``run_tool_agent`` invokes for every model reply and
#: every tool execution.  ``data`` carries raw values; this module summarises them.
OnStep = Callable[[str, dict[str, Any]], Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def redact_text(text: Any) -> str:
    """Redact secret values and ``sk-`` shaped strings.

    Never raises: a redaction problem degrades to the pattern-only pass so the
    task keeps running.
    """

    raw = _as_text(text)
    try:
        # Reuse the isolated-execution redactor instead of inventing a second one.
        from app.execution.isolated import redact_secrets

        raw = redact_secrets(raw)
    except Exception:  # noqa: BLE001 - observability must stay fail-open
        pass
    return _SK_PATTERN.sub(_REDACTED, raw)


def clip(text: Any, limit: int = FIELD_LIMIT) -> tuple[str, bool]:
    """Redact then clip to ``limit`` characters; return ``(text, truncated)``."""

    value = redact_text(text)
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def sanitize_summary(text: Any, limit: int = FIELD_LIMIT) -> tuple[str, bool]:
    """Public helper: redacted, clipped summary pair used by every step field."""

    return clip(text, limit)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:SHA_CHARS]


@dataclass
class ExecutionStep:
    """One observed model call, tool execution or granted command."""

    step: int
    kind: str
    name: str
    status: str = "ok"
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    model: str = ""
    slot: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = ""
    input_summary: str = ""
    output_summary: str = ""
    error: str = ""
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # ``null`` reads better than ``""`` for "no error" in the JSON contract.
        payload["error"] = self.error or None
        return payload

    def as_event(self, attempt_id: str) -> dict[str, Any]:
        payload = self.as_dict()
        payload["attempt_id"] = attempt_id
        return payload


@dataclass
class AttemptTrace:
    """One attempt with its frozen hashes and recorded steps."""

    attempt_id: str
    status: str
    started_at: str
    ended_at: str | None
    role: str
    context_hash: str
    memory_context_hash: str
    manual_revision: int
    skill_bundle_hash: str
    commit: str
    context_injected: bool
    execution_path: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_tool_call(name: str, arguments: Any) -> tuple[str, bool]:
    """Summarise tool arguments; file contents are reduced to sha + length."""

    args = arguments if isinstance(arguments, dict) else {}
    if name in _WRITE_TOOLS:
        content = str(args.get("content") or "")
        return clip(f"path={args.get('path')}; chars={len(content)}; sha256={_sha(content)}")
    if name in _COMMAND_TOOLS:
        raw = args.get("cmd") or args.get("command") or []
        argv = " ".join(str(part) for part in raw) if isinstance(raw, list) else str(raw)
        return clip(f"argv={argv}")
    if name in _READ_TOOLS or name in _LIST_TOOLS:
        return clip(f"path={args.get('path') or '.'}")
    return clip(_as_text(args))


def summarize_tool_result(name: str, output: Any) -> tuple[str, bool]:
    """Summarise a tool result without ever exposing written file contents."""

    if name in _WRITE_TOOLS and isinstance(output, dict):
        if output.get("ok"):
            return clip(f"ok=true; path={output.get('path') or ''}")
        return clip(f"ok=false; error={output.get('error') or ''}")
    if name in _COMMAND_TOOLS and isinstance(output, dict):
        text, truncated = clip(output.get("output") or "", FIELD_LIMIT)
        exit_code = output.get("exit_code")
        suffix = "; truncated" if truncated else ""
        return clip(f"exit={exit_code}; output={text}{suffix}")
    if name in _READ_TOOLS:
        text = _as_text(output)
        preview, truncated = clip(text, PREVIEW_LIMIT)
        return clip(f"chars={len(text)}; preview={preview}{'; truncated' if truncated else ''}")
    if name in _LIST_TOOLS:
        if isinstance(output, list):
            names = [str(item) for item in output[:LISTING_LIMIT]]
            return clip(f"count={len(output)}; entries={', '.join(names)}")
        return clip(_as_text(output))
    return clip(_as_text(output))


def summarize_messages(messages: Any) -> tuple[str, bool]:
    """Role + length per message, plus one clipped preview of the last user turn.

    The full prompt and the injected context block are never recorded.
    """

    rows = messages if isinstance(messages, list) else []
    parts: list[str] = []
    preview = ""
    for message in rows:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "?")
        content = message.get("content")
        length = len(_as_text(content))
        parts.append(f"{role}:{length}")
        if role == "user" and content:
            preview = _as_text(content)
    summary = " ".join(parts)
    if preview:
        summary = f"{summary} | last_user={preview}"
    return clip(summary)


def summarize_llm_output(data: dict[str, Any]) -> tuple[str, bool]:
    """Summarise a model reply: tool names or a clipped text preview."""

    tool_names = [str(item) for item in (data.get("tool_names") or []) if item]
    if tool_names:
        return clip("tool_calls: " + ", ".join(tool_names))
    text = data.get("text") or ""
    if text:
        return clip(f"text: {text}", FIELD_LIMIT)
    return clip(data.get("summary") or "")


def last_step_summary(attempt: Any) -> dict[str, Any] | None:
    """Lightweight last-step view for list/monitor payloads (no I/O text)."""

    steps = (attempt or {}).get("execution_steps") or []
    if not isinstance(steps, list) or not steps:
        return None
    step = steps[-1]
    if not isinstance(step, dict):
        return None
    return {
        "kind": str(step.get("kind") or ""),
        "name": str(step.get("name") or ""),
        "status": str(step.get("status") or ""),
        "duration_ms": int(step.get("duration_ms") or 0),
    }


def step_count(attempt: Any) -> int:
    steps = (attempt or {}).get("execution_steps") or []
    return len(steps) if isinstance(steps, list) else 0


def newest_first_attempts(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Finished history plus the live attempt, in start order, without duplicates."""

    history = [item for item in (task.get("attempt_history") or []) if isinstance(item, dict)]
    current = task.get("attempt")
    ordered: list[dict[str, Any]] = list(history)
    if isinstance(current, dict) and current.get("attempt_id"):
        ids = [item.get("attempt_id") for item in ordered]
        if current["attempt_id"] in ids:
            # The live attempt wins: it carries any steps written since the freeze.
            ordered[ids.index(current["attempt_id"])] = current
        else:
            ordered.append(current)
    return ordered


def attempt_trace(attempt: dict[str, Any]) -> AttemptTrace:
    steps = attempt.get("execution_steps") or []
    return AttemptTrace(
        attempt_id=str(attempt.get("attempt_id") or ""),
        status=str(attempt.get("status") or ""),
        started_at=str(attempt.get("started_at") or ""),
        ended_at=str(attempt.get("ended_at") or "") or None,
        role=str(attempt.get("role") or ""),
        context_hash=str(attempt.get("context_hash") or ""),
        memory_context_hash=str(attempt.get("memory_context_hash") or ""),
        manual_revision=int(attempt.get("manual_revision") or 0),
        skill_bundle_hash=str(attempt.get("skill_bundle_hash") or ""),
        commit=str(attempt.get("commit") or ""),
        context_injected=bool(attempt.get("context_injected")),
        execution_path=str(attempt.get("execution_path") or ""),
        # Steps are stored as plain dicts so the run snapshot stays JSON-serialisable.
        steps=[dict(step) for step in steps if isinstance(step, dict)],
    )


def build_execution_trace(run_id: str, task_code: str, task: dict[str, Any]) -> dict[str, Any]:
    """Response body for the execution-trace endpoint.

    Empty state is ``attempts: []`` — a task that exists but has not run is not a
    404.
    """

    attempts = [attempt_trace(item) for item in newest_first_attempts(task)]
    current = task.get("attempt") if isinstance(task.get("attempt"), dict) else {}
    latest = attempts[-1] if attempts else None
    return {
        "run_id": run_id,
        "task_code": task_code,
        "role": str((task.get("card") or {}).get("role") or current.get("role") or ""),
        "execution_path": str(current.get("execution_path") or (latest.execution_path if latest else "")),
        "context_injected": bool(current.get("context_injected")),
        "current_attempt_id": str(current.get("attempt_id") or ""),
        "attempts": [item.as_dict() for item in attempts],
    }


class ExecutionTraceRecorder:
    """Collects steps for one attempt and pushes them on the run event bus.

    ``emit`` is called as ``emit(event_kind, payload)``; the caller closes over the
    run and task code.  Every method is fail-open.
    """

    def __init__(
        self,
        *,
        execution_path: str,
        context_injected: bool,
        attempt: dict[str, Any] | None = None,
        emit: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.execution_path = execution_path if execution_path in EXECUTION_PATHS else ""
        self.context_injected = bool(context_injected)
        self.enabled = True
        self._emit = emit
        self._attempt: dict[str, Any] | None = None
        self._step = 0
        if isinstance(attempt, dict):
            self.bind(attempt)

    # -- binding -----------------------------------------------------------
    def bind(self, attempt: dict[str, Any]) -> None:
        """Attach to the current attempt and freeze path/injection flags."""

        self._attempt = attempt
        try:
            attempt["execution_path"] = self.execution_path
            attempt["context_injected"] = self.context_injected
            if not isinstance(attempt.get("execution_steps"), list):
                attempt["execution_steps"] = []
            self._step = len(attempt["execution_steps"])
        except Exception:  # noqa: BLE001 - fail-open
            self.enabled = False

    @property
    def attempt_id(self) -> str:
        return str((self._attempt or {}).get("attempt_id") or "")

    # -- recording ---------------------------------------------------------
    def observe(self, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Callback signature accepted by ``run_tool_agent``'s ``on_step``."""

        payload = data or {}
        try:
            if kind == KIND_LLM:
                return self.add(
                    KIND_LLM,
                    str(payload.get("name") or ""),
                    status=str(payload.get("status") or "ok"),
                    started_at=str(payload.get("started_at") or ""),
                    ended_at=str(payload.get("ended_at") or ""),
                    duration_ms=int(payload.get("duration_ms") or 0),
                    model=str(payload.get("model") or ""),
                    slot=str(payload.get("slot") or ""),
                    tokens_in=int(payload.get("tokens_in") or 0),
                    tokens_out=int(payload.get("tokens_out") or 0),
                    finish_reason=str(payload.get("finish_reason") or ""),
                    input_summary=summarize_messages(payload.get("messages")),
                    output_summary=summarize_llm_output(payload),
                    error=str(payload.get("error") or ""),
                )
            if kind == KIND_TOOL:
                name = str(payload.get("name") or "")
                return self.add(
                    KIND_TOOL,
                    name,
                    status=str(payload.get("status") or "ok"),
                    started_at=str(payload.get("started_at") or ""),
                    ended_at=str(payload.get("ended_at") or ""),
                    duration_ms=int(payload.get("duration_ms") or 0),
                    input_summary=summarize_tool_call(name, payload.get("arguments")),
                    output_summary=summarize_tool_result(name, payload.get("output")),
                    error=str(payload.get("error") or ""),
                )
            if kind == KIND_GRANTED_COMMAND:
                argv = payload.get("argv") or []
                text = " ".join(str(part) for part in argv) if isinstance(argv, list) else str(argv)
                return self.add(
                    KIND_GRANTED_COMMAND,
                    str(payload.get("name") or (argv[0] if isinstance(argv, list) and argv else "command")),
                    status=str(payload.get("status") or "ok"),
                    started_at=str(payload.get("started_at") or ""),
                    ended_at=str(payload.get("ended_at") or ""),
                    duration_ms=int(payload.get("duration_ms") or 0),
                    input_summary=clip(f"argv={text}"),
                    output_summary=summarize_tool_result("run_command", payload.get("output")),
                    error=str(payload.get("error") or ""),
                )
            return None
        except Exception:  # noqa: BLE001 - observability must not fail the task
            self.enabled = False
            return None

    def add(
        self,
        kind: str,
        name: str,
        *,
        status: str = "ok",
        started_at: str = "",
        ended_at: str = "",
        duration_ms: int = 0,
        model: str = "",
        slot: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        finish_reason: str = "",
        input_summary: tuple[str, bool] | str = ("", False),
        output_summary: tuple[str, bool] | str = ("", False),
        error: str = "",
    ) -> dict[str, Any] | None:
        """Append one step to the bound attempt and emit its event."""

        if not self.enabled or self._attempt is None or kind not in STEP_KINDS:
            return None
        try:
            self._step += 1
            in_text, in_truncated = self._pair(input_summary)
            out_text, out_truncated = self._pair(output_summary)
            step = ExecutionStep(
                step=self._step,
                kind=kind,
                name=clip(name, PREVIEW_LIMIT)[0],
                status=status or "ok",
                started_at=started_at or _now(),
                ended_at=ended_at or _now(),
                duration_ms=max(int(duration_ms or 0), 0),
                model=clip(model, PREVIEW_LIMIT)[0],
                slot=clip(slot, PREVIEW_LIMIT)[0],
                tokens_in=max(int(tokens_in or 0), 0),
                tokens_out=max(int(tokens_out or 0), 0),
                finish_reason=clip(finish_reason, PREVIEW_LIMIT)[0],
                input_summary=in_text,
                output_summary=out_text,
                error=clip(error)[0],
                truncated=bool(in_truncated or out_truncated),
            )
            steps = self._attempt.get("execution_steps")
            if not isinstance(steps, list):
                steps = []
                self._attempt["execution_steps"] = steps
            steps.append(step.as_dict())
            if self._emit is not None:
                try:
                    self._emit(EVENT_FOR_KIND[kind], step.as_event(self.attempt_id))
                except Exception:  # noqa: BLE001 - a broken sink must not fail the task
                    pass
            return step.as_dict()
        except Exception:  # noqa: BLE001 - fail-open
            self.enabled = False
            return None

    def observe_granted_command(
        self,
        argv: list[str],
        output: Any,
        *,
        duration_ms: int,
        exit_code: int | None = None,
        error: str = "",
    ) -> dict[str, Any] | None:
        """Record a single granted-v1 command (never a fake multi-step loop)."""

        status = "ok" if (error == "" and (exit_code in (None, 0))) else "error"
        payload = output if isinstance(output, dict) else {"output": output, "exit_code": exit_code}
        return self.observe(
            KIND_GRANTED_COMMAND,
            {
                "argv": list(argv or []),
                "output": payload,
                "duration_ms": duration_ms,
                "status": status,
                "error": error,
            },
        )

    @staticmethod
    def _pair(value: tuple[str, bool] | str) -> tuple[str, bool]:
        if isinstance(value, tuple):
            return str(value[0]), bool(value[1])
        return str(value), False


__all__ = [
    "EVENT_FOR_KIND",
    "EXECUTION_PATHS",
    "EXECUTION_PATH_GRANTED",
    "EXECUTION_PATH_LEGACY",
    "EXECUTION_PATH_SIMULATED",
    "FIELD_LIMIT",
    "KIND_GRANTED_COMMAND",
    "KIND_LLM",
    "KIND_TOOL",
    "LISTING_LIMIT",
    "PREVIEW_LIMIT",
    "STEP_KINDS",
    "AttemptTrace",
    "ExecutionStep",
    "ExecutionTraceRecorder",
    "OnStep",
    "attempt_trace",
    "build_execution_trace",
    "clip",
    "last_step_summary",
    "newest_first_attempts",
    "redact_text",
    "sanitize_summary",
    "step_count",
    "summarize_llm_output",
    "summarize_messages",
    "summarize_tool_call",
    "summarize_tool_result",
]