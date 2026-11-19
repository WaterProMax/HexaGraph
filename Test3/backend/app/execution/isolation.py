"""Real isolation backends for granted execution (F-06).

``app/tools/sandbox.py`` only enforces a command whitelist, a cwd and an
in-process write set.  That is policy, not a security boundary: a whitelisted
``python -m pytest`` can still write absolute paths, read the user's home or
open a socket.  Granted execution therefore runs commands only inside a
container whose preflight actually proves the required guarantees.

Selection is explicit and fail-closed:

* ``docker`` is the only backend.  It is reused only when the daemon is already
  reachable, the image is already present locally (no pull) and a probe
  container proves no network, no host home, no docker socket, no write
  outside the mounted worktree, and a working ``python -m pytest``.
  An image without pytest (and the project toolchain) is a failed preflight,
  never an "available but empty" backend.
* Nothing here installs or starts Docker, and nothing falls back to running the
  test command directly on the host.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.errors import IsolationUnavailable

DEFAULT_IMAGE = "python:3.11-slim"
BACKEND_ENV = "TEST3_ISOLATION_BACKEND"
IMAGE_ENV = "TEST3_ISOLATION_IMAGE"
PROBE_TIMEOUT_S = 30
DOCKER_CLI_TIMEOUT_S = 10
OUTPUT_LIMIT_BYTES = 256_000
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1"
PIDS_LIMIT = "128"
TMPFS_SIZE = "64m"
CONTAINER_PATH = "/usr/local/bin:/usr/bin:/bin"
_RESERVED_ENV = frozenset(
    {"PATH", "HOME", "TMPDIR", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "VIRTUAL_ENV"}
)

_PROBE_MARKER = "TEST3_ISOLATION_PROBE="

_PROBE_SCRIPT = r"""
import json, os, pathlib, socket, subprocess

result = {}
try:
    pathlib.Path("/work/probe.txt").write_text("probe", encoding="utf-8")
    result["work_write"] = True
except Exception:
    result["work_write"] = False
try:
    pathlib.Path("/probe-outside.txt").write_text("nope", encoding="utf-8")
    result["outside_write"] = True
except Exception:
    result["outside_write"] = False
sock = socket.socket()
sock.settimeout(1.0)
try:
    sock.connect(("1.1.1.1", 443))
    result["network"] = True
except Exception:
    result["network"] = False
finally:
    sock.close()
host_home = os.environ.get("TEST3_PROBE_HOST_HOME", "")
result["host_home"] = host_home
result["host_home_visible"] = bool(host_home) and pathlib.Path(host_home).exists()
result["docker_socket"] = pathlib.Path("/var/run/docker.sock").exists()
result["home"] = os.environ.get("HOME", "")
result["work_mounted"] = os.path.ismount("/work")
try:
    pytest_version = subprocess.run(
        ["python", "-m", "pytest", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    result["pytest_available"] = pytest_version.returncode == 0
except Exception:
    result["pytest_available"] = False
print("TEST3_ISOLATION_PROBE=" + json.dumps(result, sort_keys=True))
"""


@dataclass(frozen=True)
class IsolationPreflight:
    available: bool
    backend: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


_CACHE: IsolationPreflight | None = None


def reset_preflight_cache() -> None:
    """Test hook: drop the cached probe so env changes take effect."""
    global _CACHE
    _CACHE = None


def preflight_isolation(*, force: bool = False) -> IsolationPreflight:
    """Probe the local isolation backend without changing any host state.

    The probe runs in a throw-away temp directory and a ``--rm`` container.  A
    failed probe is a definitive "unavailable": callers must fail closed.
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    _CACHE = _probe_docker()
    return _CACHE


def _unavailable(reason: str, **details: Any) -> IsolationPreflight:
    return IsolationPreflight(available=False, backend="docker", reason=reason, details=details)


def _probe_docker() -> IsolationPreflight:
    mode = os.environ.get(BACKEND_ENV, "").strip().lower()
    if mode in {"none", "disabled", "off"}:
        return IsolationPreflight(
            available=False,
            backend="",
            reason=f"isolation disabled by {BACKEND_ENV}={mode}",
            details={"env": mode},
        )
    docker = shutil.which("docker")
    if not docker:
        return _unavailable("docker CLI not found; no isolation backend available")

    version = _run_sync([docker, "version", "--format", "{{.Server.Version}}"], timeout=DOCKER_CLI_TIMEOUT_S)
    if version.returncode != 0:
        detail = (version.stderr or version.stdout or "").strip().splitlines()
        return _unavailable(
            "docker daemon is not reachable; refusing to start it",
            error=detail[-1] if detail else "",
        )

    image = os.environ.get(IMAGE_ENV, DEFAULT_IMAGE)
    inspect = _run_sync([docker, "image", "inspect", image], timeout=DOCKER_CLI_TIMEOUT_S)
    if inspect.returncode != 0:
        return _unavailable(
            f"isolation image is not present locally: {image} (no pull attempted)",
            image=image,
        )

    probe_dir = Path(tempfile.mkdtemp(prefix="test3-isolation-probe-"))
    try:
        work = probe_dir / "work"
        work.mkdir()
        argv = _docker_argv(
            docker,
            image,
            work,
            ["python", "-c", _PROBE_SCRIPT],
            container_name=f"test3-probe-{uuid.uuid4().hex[:8]}",
            host_home=str(Path.home()),
        )
        result = _run_sync(argv, timeout=PROBE_TIMEOUT_S)
        marker = ""
        for line in (result.stdout or "").splitlines():
            if line.startswith(_PROBE_MARKER):
                marker = line[len(_PROBE_MARKER) :]
        if result.returncode != 0 or not marker:
            return _unavailable(
                "isolation probe container failed",
                exit_code=result.returncode,
                image=image,
                output=(result.stderr or result.stdout or "").strip()[-400:],
            )
        checks = json.loads(marker)
        failures = _probe_failures(checks)
        if failures:
            return _unavailable(
                "isolation probe did not prove the required guarantees: " + ", ".join(failures),
                image=image,
                checks=checks,
            )
        return IsolationPreflight(
            available=True,
            backend="docker",
            reason="",
            details={"image": image, "checks": checks, "server_version": (version.stdout or "").strip()},
        )
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


def _probe_failures(checks: dict[str, Any]) -> list[str]:
    failures = []
    if not checks.get("work_write"):
        failures.append("worktree is not writable")
    if checks.get("outside_write"):
        failures.append("outside write succeeded")
    if checks.get("network"):
        failures.append("network is reachable")
    if checks.get("host_home_visible"):
        failures.append("host home is mounted")
    if checks.get("docker_socket"):
        failures.append("docker socket is exposed")
    if checks.get("home") != "/tmp":
        failures.append("HOME is not redirected to /tmp")
    if not checks.get("work_mounted"):
        failures.append("/work is not a mount")
    if not checks.get("pytest_available"):
        failures.append("pytest is not available in the isolation image")
    return failures


def _run_sync(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_docker_cli_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 124, "", f"{type(exc).__name__}: {exc}")


def _docker_cli_env() -> dict[str, str]:
    """Env for the docker CLI only; it is never forwarded into the container."""
    keep = {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "TMPDIR"}
    return {key: value for key, value in os.environ.items() if key in keep}


def _docker_argv(
    docker: str,
    image: str,
    work: Path,
    command: list[str],
    *,
    container_name: str,
    host_home: str,
    env: dict[str, str] | None = None,
) -> list[str]:
    argv = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        container_name,
        "--network=none",
        f"--memory={MEMORY_LIMIT}",
        f"--memory-swap={MEMORY_LIMIT}",
        f"--cpus={CPU_LIMIT}",
        f"--pids-limit={PIDS_LIMIT}",
        "--read-only",
        f"--tmpfs=/tmp:rw,exec,size={TMPFS_SIZE},mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--ulimit=nofile=256:256",
        f"--user={os.getuid()}:{os.getgid()}",
        "-e",
        f"PATH={CONTAINER_PATH}",
        "-e",
        "HOME=/tmp",
        "-e",
        "TMPDIR=/tmp",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        f"TEST3_PROBE_HOST_HOME={host_home}",
        "-v",
        f"{work}:/work:rw",
        "-w",
        "/work",
    ]
    for key, value in (env or {}).items():
        if key in _RESERVED_ENV:
            continue
        argv.extend(["-e", f"{key}={value}"])
    argv.append(image)
    argv.extend(command)
    return argv


def safe_env(env_allow: list[str] | None) -> dict[str, str]:
    """Only explicitly allowed, non-sensitive host values reach the container.

    Host PATH/HOME/PYTHON* are never forwarded: the container gets its own
    fixed PATH and ``HOME=/tmp``.  The docker CLI process keeps its own env via
    ``_docker_cli_env``; that env is not a source for in-container tools.
    """
    sensitive = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
    env: dict[str, str] = {}
    for name in env_allow or []:
        if name in _RESERVED_ENV:
            continue
        if any(token in name.upper() for token in sensitive):
            continue
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


async def run_isolated(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env_allow: list[str] | None = None,
    output_limit: int = OUTPUT_LIMIT_BYTES,
) -> dict[str, Any]:
    """Run ``argv`` inside the preflighted container.

    Raises ``IsolationUnavailable`` when no backend passed preflight; callers
    must surface that as BLOCKED rather than execute on the host.
    """
    preflight = preflight_isolation()
    if not preflight.available:
        raise IsolationUnavailable(
            f"isolation backend unavailable: {preflight.reason}",
            backend=preflight.backend,
            reason=preflight.reason,
            details=preflight.details,
        )
    docker = shutil.which("docker")
    if not docker:
        raise IsolationUnavailable("docker CLI disappeared after preflight", backend="docker", reason="docker CLI missing")
    work = cwd.resolve()
    name = f"test3-task-{uuid.uuid4().hex[:10]}"
    args = _docker_argv(
        docker,
        str(preflight.details.get("image") or DEFAULT_IMAGE),
        work,
        list(argv),
        container_name=name,
        host_home=str(Path.home()),
        env=safe_env(env_allow),
    )
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_docker_cli_env(),
        start_new_session=True,
    )
    timed_out = False
    try:
        raw, truncated = await asyncio.wait_for(_read_capped(proc, output_limit), timeout=timeout)
    except TimeoutError:
        timed_out = True
        raw, truncated = b"", False
        await _kill(proc)
        await _force_remove(name)
    except asyncio.CancelledError:
        await _kill(proc)
        await _force_remove(name)
        raise
    text = raw.decode("utf-8", errors="replace")
    if timed_out:
        text = "timeout"
    elif truncated:
        text += "\n...[truncated]"
    return {
        "exit_code": -1 if timed_out else (1 if proc.returncode is None else int(proc.returncode)),
        "output": text,
        "timeout": timed_out,
        "truncated": truncated or len(raw) >= output_limit,
        "backend": "docker",
        "image": preflight.details.get("image", ""),
    }


async def _read_capped(proc: asyncio.subprocess.Process, limit: int) -> tuple[bytes, bool]:
    assert proc.stdout is not None
    kept: list[bytes] = []
    total = 0
    truncated = False
    while True:
        chunk = await proc.stdout.read(65536)
        if not chunk:
            break
        if total < limit:
            piece = chunk[: limit - total]
            kept.append(piece)
            total += len(piece)
        if total >= limit:
            truncated = True
    await proc.wait()
    return b"".join(kept), truncated


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


async def _force_remove(name: str) -> None:
    docker = shutil.which("docker")
    if not docker:
        return
    proc = await asyncio.create_subprocess_exec(
        docker,
        "rm",
        "-f",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=DOCKER_CLI_TIMEOUT_S)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


__all__ = [
    "IsolationPreflight",
    "preflight_isolation",
    "reset_preflight_cache",
    "run_isolated",
    "safe_env",
]