from __future__ import annotations

import asyncio
import threading
from pathlib import Path

_merge_lock = threading.Lock()


async def _git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    raw, _ = await proc.communicate()
    return proc.returncode or 0, raw.decode("utf-8", errors="replace")


def _git_sync(cwd: Path, *args: str) -> tuple[int, str]:
    import subprocess

    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


async def init_repo(path: Path, files: dict[str, str] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    await _git(path, "init")
    await _git(path, "config", "user.email", "test3@local")
    await _git(path, "config", "user.name", "Test3")
    for rel, content in (files or {"README.md": "workspace\n"}).items():
        dest = path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    await _git(path, "add", "-A")
    await _git(path, "commit", "-m", "init")


def init_repo_sync(path: Path, files: dict[str, str] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git_sync(path, "init")
    _git_sync(path, "config", "user.email", "test3@local")
    _git_sync(path, "config", "user.name", "Test3")
    for rel, content in (files or {"README.md": "workspace\n"}).items():
        dest = path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    _git_sync(path, "add", "-A")
    _git_sync(path, "commit", "-m", "init")


def create_worktree(repo: Path, worktree: Path, branch: str, start_point: str = "HEAD") -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    code, out = _git_sync(repo, "worktree", "add", "-B", branch, str(worktree), start_point)
    if code != 0:
        raise RuntimeError(out)


def commit(ws: Path, message: str) -> str:
    _git_sync(ws, "add", "-A")
    code, out = _git_sync(ws, "commit", "-m", message)
    if code != 0 and "nothing to commit" not in out:
        raise RuntimeError(out)
    _, sha = _git_sync(ws, "rev-parse", "HEAD")
    return sha.strip()


def changed_files(ws: Path, base: str = "HEAD~1") -> list[str]:
    _, out = _git_sync(ws, "diff", "--name-only", base)
    return [line for line in out.splitlines() if line.strip()]


def merge(repo: Path, branch: str) -> dict[str, object]:
    with _merge_lock:
        _, before = _git_sync(repo, "rev-parse", "HEAD")
        code, out = _git_sync(repo, "merge", "--no-ff", "-m", f"merge {branch}", branch)
        if code != 0:
            _git_sync(repo, "merge", "--abort")
            conflicts = [line for line in out.splitlines() if line.endswith("FAILED")]
            return {"ok": False, "conflicts": conflicts or ["conflict"], "before": before.strip(), "output": out}
        return {"ok": True, "conflicts": [], "before": before.strip(), "output": out}


def rollback_merge(repo: Path, before_sha: str) -> None:
    _git_sync(repo, "reset", "--hard", before_sha)


def is_merged(repo: Path, branch: str, into: str = "HEAD") -> bool:
    code, out = _git_sync(repo, "merge-base", "--is-ancestor", branch, into)
    return code == 0 and "fatal" not in out
