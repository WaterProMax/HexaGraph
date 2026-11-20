"""Scoped copy-and-write-back for granted execution (F-06 closeout).

The container never receives the host worktree.  It runs on a throw-away copy;
afterwards this module compares the copy with a baseline snapshot and applies
only changes whose paths are inside the task's ``write_set``.  Everything else
(including symlinks and type changes) is discarded and recorded.

The host write-back never follows a symlink: every parent component is checked
with ``lstat`` and the final component is opened with ``O_NOFOLLOW``.  An existing target is unlinked and recreated with
``O_EXCL`` so a hard link shared with an out-of-scope name is never truncated.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.errors import WriteDenied
from app.tools.sandbox import in_write_set


@dataclass(frozen=True)
class ScopedChange:
    path: str
    kind: str  # added | modified | deleted


@dataclass(frozen=True)
class WorktreeCopy:
    source: Path
    work: Path
    baseline: Path


@dataclass
class ScopeResult:
    applied: list[str] = field(default_factory=list)
    discarded: list[dict[str, str]] = field(default_factory=list)


def prepare_worktree_copy(root: Path) -> WorktreeCopy:
    """Copy the worktree twice: one for the container, one as baseline."""
    base = Path(tempfile.mkdtemp(prefix="test3-isolation-work-"))
    work = base / "work"
    baseline = base / "baseline"
    try:
        shutil.copytree(root, work, symlinks=True)
        shutil.copytree(root, baseline, symlinks=True)
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise
    return WorktreeCopy(source=root.resolve(), work=work, baseline=baseline)


def cleanup_worktree_copy(copy: WorktreeCopy) -> None:
    shutil.rmtree(copy.work.parent, ignore_errors=True)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(path: Path) -> tuple[str, str]:
    try:
        info = os.lstat(path)
    except OSError:
        return ("missing", "")
    if stat.S_ISLNK(info.st_mode):
        try:
            return ("symlink", os.readlink(path))
        except OSError:
            return ("symlink", "")
    if stat.S_ISREG(info.st_mode):
        try:
            return ("file", _hash_file(path))
        except OSError:
            return ("unreadable", "")
    return ("other", "")


def _snapshot(root: Path) -> dict[str, tuple[str, str]]:
    snapshot: dict[str, tuple[str, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(dirpath)
        for name in list(dirnames):
            candidate = directory / name
            if candidate.is_symlink():
                dirnames.remove(name)
                rel = candidate.relative_to(root).as_posix()
                snapshot[rel] = _entry(candidate)
        for name in filenames:
            candidate = directory / name
            rel = candidate.relative_to(root).as_posix()
            snapshot[rel] = _entry(candidate)
    return snapshot


def collect_changes(copy: WorktreeCopy) -> list[ScopedChange]:
    before = _snapshot(copy.baseline)
    after = _snapshot(copy.work)
    changes: list[ScopedChange] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        if path not in before:
            kind = "added"
        elif path not in after:
            kind = "deleted"
        else:
            kind = "modified"
        changes.append(ScopedChange(path=path, kind=kind))
    return changes


def _safe_relative(raw: str) -> bool:
    if not raw or "\x00" in raw:
        return False
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts:
        return False
    return all(part not in {"", ".", ".."} for part in path.parts)


def _open_parent(root: Path, rel: str) -> tuple[int, str]:
    parts = PurePosixPath(rel).parts
    current = root
    for part in parts[:-1]:
        candidate = current / part
        try:
            info = os.lstat(candidate)
        except FileNotFoundError:
            os.mkdir(candidate, 0o755)
            info = os.lstat(candidate)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise WriteDenied(f"unsafe parent directory for {rel}")
        current = candidate
    dir_fd = os.open(current, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    return dir_fd, parts[-1]


def _write_regular(root: Path, rel: str, data: bytes) -> None:
    dir_fd, name = _open_parent(root, rel)
    try:
        mode = 0o644
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is not None:
            if not stat.S_ISREG(info.st_mode):
                raise WriteDenied(f"refusing to overwrite a non-regular file: {rel}")
            mode = stat.S_IMODE(info.st_mode)
            # Never truncate an existing inode: an out-of-scope name may share it
            # (hard link).  Drop only this directory entry and create a new inode.
            os.unlink(name, dir_fd=dir_fd)
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=dir_fd,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise WriteDenied(f"short write while applying {rel}")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def _delete_regular(root: Path, rel: str) -> None:
    dir_fd, name = _open_parent(root, rel)
    try:
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode):
            raise WriteDenied(f"refusing to delete a non-regular file: {rel}")
        os.unlink(name, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def apply_changes(copy: WorktreeCopy, changes: list[ScopedChange], write_set: list[str] | None) -> ScopeResult:
    """Apply only in-scope, regular-file changes from the copy to the host."""
    result = ScopeResult()
    scope = list(write_set or [])
    for change in changes:
        rel = change.path
        if not _safe_relative(rel):
            raise WriteDenied(f"unsafe change path: {rel!r}")
        if write_set is None or not in_write_set(copy.source / rel, copy.source, scope):
            result.discarded.append({"path": rel, "reason": "outside-write-set"})
            continue
        if change.kind == "deleted":
            _delete_regular(copy.source, rel)
            result.applied.append(rel)
            continue
        source = copy.work / rel
        try:
            info = os.lstat(source)
        except FileNotFoundError:
            result.discarded.append({"path": rel, "reason": "missing-in-copy"})
            continue
        if stat.S_ISLNK(info.st_mode):
            result.discarded.append({"path": rel, "reason": "symlink"})
            continue
        if not stat.S_ISREG(info.st_mode):
            result.discarded.append({"path": rel, "reason": "not-a-regular-file"})
            continue
        _write_regular(copy.source, rel, source.read_bytes())
        result.applied.append(rel)
    return result


__all__ = [
    "ScopeResult",
    "ScopedChange",
    "WorktreeCopy",
    "apply_changes",
    "cleanup_worktree_copy",
    "collect_changes",
    "prepare_worktree_copy",
]