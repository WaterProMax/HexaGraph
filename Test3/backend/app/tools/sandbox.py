from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Any

from app.errors import CommandDenied, WriteDenied


def normalize_under(root: Path, raw: str) -> Path:
    if raw.startswith("~"):
        raise WriteDenied("拒绝 home 路径")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise WriteDenied("拒绝绝对路径")
    root = root.resolve()
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WriteDenied(f"路径越界: {raw}") from exc
    if target.is_symlink():
        real = target.resolve()
        try:
            real.relative_to(root)
        except ValueError as exc:
            raise WriteDenied(f"符号链接逃逸: {raw}") from exc
    return target


def in_write_set(path: Path, root: Path, write_set: list[str]) -> bool:
    rel = path.relative_to(root.resolve()).as_posix()
    for item in write_set:
        prefix = item.strip().lstrip("./")
        if rel == prefix or rel.startswith(prefix.rstrip("/") + "/") or prefix == ".":
            return True
    return False


_SHELL_META = set(";&|`$<>")


def command_allowed(cmd: list[str], whitelist: list[str], forbidden: list[str] | None = None) -> bool:
    if not cmd:
        return False
    if any(any(ch in arg for ch in _SHELL_META) for arg in cmd):
        return False
    for prefix in forbidden or []:
        parts = prefix.split()
        if not parts:
            continue
        if cmd[: len(parts)] == parts:
            return False
        if len(cmd) >= 3 and cmd[0] in {"python", "python3"} and cmd[1] == "-m" and cmd[2] == parts[0]:
            return False
    for prefix in whitelist:
        parts = prefix.split()
        if cmd[: len(parts)] == parts:
            return True
    return False


async def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    whitelist: list[str],
    timeout: int,
    env_allow: list[str],
    truncate: int = 8000,
    forbidden: list[str] | None = None,
) -> dict[str, Any]:
    if not command_allowed(cmd, whitelist, forbidden):
        raise CommandDenied(f"命令不在白名单: {cmd}")
    env = {k: os.environ[k] for k in env_allow if k in os.environ}
    # 不把 __pycache__ 写进工作树：并发 merge 时 dirty 工作区会被误判成合并冲突。
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        if proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
        await proc.wait()
        return {"exit_code": -1, "output": "timeout", "timeout": True, "truncated": False}
    text = raw.decode("utf-8", errors="replace")
    truncated = len(text) > truncate
    if truncated:
        text = text[:truncate] + "\n...[truncated]"
    return {"exit_code": proc.returncode, "output": text, "timeout": False, "truncated": truncated}
