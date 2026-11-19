"""Isolated granted-v1 execution worker.

The worker only writes under an explicit isolation root (the per-task worktree),
runs an offline, whitelisted command, and records replayable evidence. It never
uses the user's dirty workspace and never performs network or model calls.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.errors import EvidenceWriteFailed, GrantRejected, IsolationUnavailable, WriteDenied
from app.execution import evidence as evidence_store
from app.execution.isolation import preflight_isolation, run_isolated
from app.execution.tool_policy import DEFAULT_PLATFORM_WHITELIST, authorize_granted_command
from app.schemas.execution_grant import ExecutionGrant
from app.tools.sandbox import in_write_set, normalize_under

_SENSITIVE_TOKENS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_MIN_SECRET_LENGTH = 8


@dataclass
class WriteSpec:
    path: str
    content: str


@dataclass
class CommandResult:
    argv: list[str]
    cwd: str
    exit_code: int
    log_path: str
    output: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_path: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def secret_values(secret_refs: list[str] | None = None) -> list[str]:
    values: set[str] = set()
    for name in secret_refs or []:
        value = os.environ.get(name)
        if value and len(value) >= _MIN_SECRET_LENGTH:
            values.add(value)
    for name, value in os.environ.items():
        if not value or len(value) < _MIN_SECRET_LENGTH:
            continue
        upper = name.upper()
        if any(token in upper for token in _SENSITIVE_TOKENS):
            values.add(value)
    return sorted(values, key=len, reverse=True)


def redact_secrets(text: str, secret_refs: list[str] | None = None) -> str:
    redacted = text
    for value in secret_values(secret_refs):
        redacted = redacted.replace(value, "***REDACTED***")
    return redacted


def _redact_obj(value: Any, secret_refs: list[str] | None) -> Any:
    if isinstance(value, str):
        return redact_secrets(value, secret_refs)
    if isinstance(value, list):
        return [_redact_obj(item, secret_refs) for item in value]
    if isinstance(value, dict):
        return {key: _redact_obj(item, secret_refs) for key, item in value.items()}
    return value


def build_evidence(
    task_code: str,
    commands: list[CommandResult],
    *,
    isolation_root: str | Path | None = None,
    written: list[str] | None = None,
    secret_refs: list[str] | None = None,
) -> dict[str, Any]:
    evidence = {
        "task_code": task_code,
        "isolation_root": str(isolation_root) if isolation_root is not None else "",
        "written": list(written or []),
        "commands": [
            {
                "argv": list(command.argv),
                "cwd": command.cwd,
                "exit_code": int(command.exit_code),
                "log_path": command.log_path,
                "output": command.output,
            }
            for command in commands
        ],
        "ok": all(command.exit_code == 0 for command in commands),
    }
    return _redact_obj(evidence, secret_refs)


def validate_writes(
    root: Path,
    writes: list[WriteSpec] | None,
    write_set: list[str] | None,
) -> list[tuple[WriteSpec, Path]]:
    """Resolve every WriteSpec without touching the filesystem.

    Absolute paths, ``..`` escapes and symlinks are refused here, before any
    isolation probe or file creation, so a rejected plan leaves no trace.
    """
    root = root.resolve()
    if not root.exists():
        raise WriteDenied(f"isolation root missing: {root}")
    planned: list[tuple[WriteSpec, Path]] = []
    for spec in writes or []:
        target = normalize_under(root, spec.path)
        if write_set is not None and not in_write_set(target, root, write_set):
            raise WriteDenied(f"写集外: {spec.path}")
        planned.append((spec, target))
    return planned


def stage_writes(
    root: Path,
    writes: list[WriteSpec] | None,
    write_set: list[str] | None,
) -> list[str]:
    """Validate and then write inside the isolation root only."""
    written: list[str] = []
    for spec, target in validate_writes(root, writes, write_set):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.content, encoding="utf-8")
        written.append(spec.path)
    return written


async def execute_task_granted(
    run_id: str,
    task_code: str,
    grant: ExecutionGrant,
    *,
    isolation_root: Path,
    writes: list[WriteSpec] | None = None,
    test_command: list[str] | None = None,
    write_set: list[str] | None = None,
    whitelist: list[str] | None = None,
    env_allow: list[str] | None = None,
    timeout: int = 600,
    secret_refs: list[str] | None = None,
    tool_refs: list[str] | None = None,
    spec_command: list[str] | None = None,
) -> CommandResult:
    """Write files and run one offline command inside a preflighted container.

    ``grant`` is used for traceability only (run/task pairing and feature
    branch); this function does not push, commit or call GitHub.  When no
    isolation backend passes preflight the call raises ``IsolationUnavailable``
    before writing files or starting any process.

    The command must be authorized by the platform policy, the Grant's
    ``allowed_tool_refs`` and the materialized spec's ``tool_refs`` before any
    write or process exists (F-08).
    """
    if grant.run_id != run_id:
        raise GrantRejected(
            "grant_binding_mismatch",
            f"execution grant belongs to run {grant.run_id}, not {run_id}",
            status_code=409,
        )
    if task_code not in grant.task_codes:
        raise GrantRejected(
            "scope_mismatch",
            f"task {task_code} is outside the grant scope",
            status_code=409,
        )
    platform_refs = list(whitelist) if whitelist is not None else list(DEFAULT_PLATFORM_WHITELIST)
    argv = authorize_granted_command(
        test_command or [],
        grant_tool_refs=grant.allowed_tool_refs,
        spec_tool_refs=tool_refs or [],
        platform_whitelist=platform_refs,
        expected_command=spec_command,
    )
    root = isolation_root.resolve()
    if not root.exists():
        raise WriteDenied(f"isolation root missing: {root}")
    # Pure validation first: a bad path never reaches the isolation probe.
    validate_writes(root, writes, write_set)
    preflight = preflight_isolation()
    if not preflight.available:
        raise IsolationUnavailable(
            f"isolation backend unavailable: {preflight.reason}",
            backend=preflight.backend,
            reason=preflight.reason,
            details=preflight.details,
        )
    written = stage_writes(root, writes, write_set)
    result = await run_isolated(
        argv,
        cwd=root,
        timeout=timeout,
        env_allow=list(env_allow or ["PATH"]),
    )
    output = redact_secrets(str(result.get("output") or ""), secret_refs)
    stamp = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    evidence_dir = evidence_store.create_evidence_dir()
    try:
        log_path = evidence_store.write_evidence_file(evidence_dir, f"{task_code}-{stamp}.log", output)
        command = CommandResult(
            argv=argv,
            cwd="/work",
            exit_code=1 if result.get("exit_code") is None else int(result["exit_code"]),
            log_path=str(log_path),
            output=output,
        )
        evidence = build_evidence(
            task_code,
            [command],
            isolation_root=root,
            written=written,
            secret_refs=secret_refs,
        )
        evidence["grant_id"] = grant.grant_id
        evidence["run_id"] = run_id
        evidence["feature_branch"] = grant.feature_branch
        evidence["isolation"] = {
            "backend": result.get("backend", ""),
            "image": result.get("image", ""),
            "network": "none",
            "host_home": "not mounted",
            "timeout": bool(result.get("timeout")),
            "truncated": bool(result.get("truncated")),
        }
        evidence_path = evidence_store.write_evidence_file(
            evidence_dir,
            f"{task_code}-{stamp}.json",
            json.dumps(evidence, ensure_ascii=False, indent=2),
        )
    except EvidenceWriteFailed:
        evidence_store.cleanup_evidence_dir(evidence_dir)
        raise
    command.evidence = evidence
    command.evidence_path = str(evidence_path)
    return command


__all__ = [
    "CommandResult",
    "WriteSpec",
    "build_evidence",
    "execute_task_granted",
    "redact_secrets",
    "secret_values",
    "stage_writes",
    "validate_writes",
]