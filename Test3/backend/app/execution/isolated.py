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

from app.errors import WriteDenied
from app.schemas.execution_grant import ExecutionGrant
from app.tools.sandbox import in_write_set, normalize_under, run_command

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


def _evidence_dir(isolation_root: Path) -> Path:
    return isolation_root.parent / f"{isolation_root.name}-evidence"


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
) -> CommandResult:
    """Write files and run one offline command under ``isolation_root``.

    ``grant`` is used for traceability only (run/task pairing and feature
    branch); this function does not push, commit or call GitHub.
    """
    root = isolation_root.resolve()
    if not root.exists():
        raise WriteDenied(f"isolation root missing: {root}")
    written: list[str] = []
    for spec in writes or []:
        target = normalize_under(root, spec.path)
        if write_set is not None and not in_write_set(target, root, write_set):
            raise WriteDenied(f"写集外: {spec.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.content, encoding="utf-8")
        written.append(spec.path)
    argv = list(test_command or ["python", "-m", "pytest", "-q", "-m", "not live"])
    allowed = list(whitelist or ["python", "python3", "uv", "python -m pytest"])
    result = await run_command(
        argv,
        cwd=root,
        whitelist=allowed,
        timeout=timeout,
        env_allow=list(env_allow or ["PATH"]),
        forbidden=[],
    )
    output = redact_secrets(str(result.get("output") or ""), secret_refs)
    evidence_dir = _evidence_dir(root)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    log_path = evidence_dir / f"{task_code}-{stamp}.log"
    log_path.write_text(output, encoding="utf-8")
    command = CommandResult(
        argv=argv,
        cwd=str(root),
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
    evidence_path = evidence_dir / f"{task_code}-{stamp}.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
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
]