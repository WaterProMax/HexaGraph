"""Safe evidence file storage (F-07).

The previous writer used a predictable sibling directory with ``mkdir`` and
``write_text``.  A symlink planted at that path redirected stdout/stderr logs and
the evidence JSON outside the run.  This module replaces it with a small,
explicit entry point:

* directories come from the system secure temp interface (unpredictable name,
  0700, private);
* files are created with ``O_CREAT|O_EXCL|O_NOFOLLOW`` relative to a directory
  file descriptor, so the check and the open are the same syscall chain and a
  symlink swapped in at open time is refused instead of followed;
* only regular files are accepted, and modes are forced to 0600/0700;
* cleanup only removes the directory this writer created and never follows a
  link out of it.

Failures raise ``EvidenceWriteFailed``: callers must report the run as failed,
never as successful evidence.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from app.errors import EvidenceWriteFailed

DIRECTORY_PREFIX = "test3-evidence-"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

_SAFE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# Windows 没有 O_NOFOLLOW（Python 未定义）；此时符号链接防护由下方的 lstat/S_ISLNK 检查兜底。
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0)


def create_evidence_dir() -> Path:
    """Create a private, unpredictable evidence directory owned by this task."""
    try:
        raw = tempfile.mkdtemp(prefix=DIRECTORY_PREFIX)
        os.chmod(raw, DIRECTORY_MODE)
    except OSError as exc:
        raise EvidenceWriteFailed(f"cannot create evidence directory: {exc}") from exc
    directory = Path(raw)
    try:
        info = os.lstat(directory)
    except OSError as exc:
        raise EvidenceWriteFailed(f"cannot inspect evidence directory: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise EvidenceWriteFailed(f"evidence directory is not a real directory: {directory}")
    if stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
        raise EvidenceWriteFailed(f"evidence directory mode is not {DIRECTORY_MODE:o}: {directory}")
    return directory


def _open_evidence_dir(directory: Path) -> int:
    try:
        dir_fd = os.open(directory, _DIR_FLAGS)
    except OSError as exc:
        raise EvidenceWriteFailed(f"refusing to use evidence directory {directory}: {exc}") from exc
    info = os.fstat(dir_fd)
    if not stat.S_ISDIR(info.st_mode):
        os.close(dir_fd)
        raise EvidenceWriteFailed(f"not a directory: {directory}")
    return dir_fd


def _open_new_file(dir_fd: int, name: str) -> int:
    """Single atomic open: never follows a link and never reuses a name."""
    return os.open(name, _FILE_FLAGS, FILE_MODE, dir_fd=dir_fd)


def write_evidence_file(directory: Path, name: str, text: str) -> Path:
    """Write one evidence artifact inside ``directory``.

    The name must be a plain basename.  An existing entry (file, symlink, FIFO,
    socket) is refused; the writer never truncates or replaces it.
    """
    if not isinstance(name, str) or not _SAFE_NAME.match(name):
        raise EvidenceWriteFailed(f"unsafe evidence file name: {name!r}")
    dir_fd = _open_evidence_dir(directory)
    try:
        try:
            fd = _open_new_file(dir_fd, name)
        except OSError as exc:
            raise EvidenceWriteFailed(f"cannot create evidence file {name!r} without following links: {exc}") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise EvidenceWriteFailed(f"evidence target is not a regular file: {name!r}")
            os.fchmod(fd, FILE_MODE)
            payload = text.encode("utf-8")
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise EvidenceWriteFailed(f"short write for evidence file {name!r}")
                view = view[written:]
            os.fsync(fd)
            inode = info.st_ino
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)

    target = directory / name
    try:
        final = os.lstat(target)
    except OSError as exc:
        raise EvidenceWriteFailed(f"evidence file disappeared after write: {name!r}") from exc
    if not stat.S_ISREG(final.st_mode) or final.st_ino != inode:
        raise EvidenceWriteFailed(f"evidence file was replaced after write: {name!r}")
    return target


def cleanup_evidence_dir(directory: Path) -> None:
    """Remove only this writer's directory; never follow a symlink out of it."""
    try:
        info = os.lstat(directory)
    except FileNotFoundError:
        return
    except OSError:
        return
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return
    try:
        dir_fd = os.open(directory, _DIR_FLAGS)
    except OSError:
        return
    try:
        for name in os.listdir(dir_fd):
            try:
                os.unlink(name, dir_fd=dir_fd)
            except OSError:
                continue
    finally:
        os.close(dir_fd)
    try:
        os.rmdir(directory)
    except OSError:
        return


__all__ = [
    "DIRECTORY_MODE",
    "DIRECTORY_PREFIX",
    "FILE_MODE",
    "cleanup_evidence_dir",
    "create_evidence_dir",
    "write_evidence_file",
]