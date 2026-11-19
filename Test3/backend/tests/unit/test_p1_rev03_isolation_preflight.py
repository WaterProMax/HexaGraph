"""P1-REV-03 / F-06: granted execution needs a real, preflighted isolation backend.

These tests never touch user data or the host configuration.  On a machine
without a usable backend the success-path probe is skipped and the fail-closed
path is still exercised; ``preflight_isolation`` never starts Docker or pulls an
image.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import IsolationUnavailable, WriteDenied
from app.execution.isolated import WriteSpec, execute_task_granted
from app.execution.isolation import (
    IsolationPreflight,
    preflight_isolation,
    reset_preflight_cache,
)
from app.schemas.execution_grant import ExecutionGrant
from tests.p1_support import install_plan, make_bench, make_grant

BACKEND_ENV = "TEST3_ISOLATION_BACKEND"


@pytest.fixture(autouse=True)
def _isolation_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    reset_preflight_cache()
    yield
    reset_preflight_cache()


def _grant(tool_refs: list[str] | None = None) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id="run-1",
        execution_profile="granted_v1",
        task_codes=["T-01"],
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=list(tool_refs or ["python -m pytest"]),
        created_at="2026-11-19T00:00:00+00:00",
    )


async def _granted_run(
    tmp_path: Path,
    *,
    card_command: list[str] | None = None,
    tool_refs: list[str] | None = None,
):
    refs = list(tool_refs or ["python -m pytest"])
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev03")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    if card_command:
        run.tasks["T-01"]["card"]["acceptance"][0]["cmd"] = card_command
        bench.profile["whitelist_prefixes"] = list(bench.profile.get("whitelist_prefixes") or []) + [
            ref for ref in refs if ref not in (bench.profile.get("whitelist_prefixes") or [])
        ]
    plan_hash = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    await bench.enable_granted_execution(run.id, {"PLAN": plan_hash})
    await bench.add_grant(make_grant(run.id, ["T-01"], hashes={"PLAN": plan_hash}, allowed_tool_refs=refs))
    bench.execution_safety_ready = True
    return bench, run


def test_preflight_never_leaves_probe_directories(tmp_path: Path) -> None:
    import tempfile

    before = {path.name for path in Path(tempfile.gettempdir()).glob("test3-isolation-probe-*")}
    result = preflight_isolation(force=True)
    after = {path.name for path in Path(tempfile.gettempdir()).glob("test3-isolation-probe-*")}
    assert after == before
    assert isinstance(result, IsolationPreflight)
    if not result.available:
        assert result.reason
        assert result.backend in {"", "docker"}


@pytest.mark.asyncio
async def test_disabled_backend_blocks_granted_execution_without_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    escape = tmp_path / "escaped-by-command.txt"
    bench, run = await _granted_run(
        tmp_path,
        card_command=["python", "-c", f"open({str(escape)!r}, 'w').write('escaped')"],
        tool_refs=["python -c"],
    )
    monkeypatch.setenv(BACKEND_ENV, "none")
    reset_preflight_cache()

    async def forbidden_worker(*_args, **_kwargs):
        raise AssertionError("granted execution must not reach the worker")

    monkeypatch.setattr("app.services.runtime.execute_task_granted", forbidden_worker)
    task = run.tasks["T-01"]
    state_before = task["state"]
    revision_before = task["revision"]
    try:
        result = await bench.execute_task(run, "T-01")
        assert result["kind"] == "BLOCKED"
        assert "disabled" in result["reason"]
        assert task["state"] == state_before
        assert task["revision"] == revision_before
        assert not (tmp_path / "runs" / run.id / "wt" / "T-01").exists()
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
        assert not escape.exists()
        assert any(event["kind"] == "task.isolation_blocked" for event in run.events)
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_failed_preflight_blocks_before_worktree_and_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    escape = tmp_path / "escaped-by-command.txt"
    bench, run = await _granted_run(
        tmp_path,
        card_command=["python", "-c", f"open({str(escape)!r}, 'w').write('escaped')"],
        tool_refs=["python -c"],
    )
    monkeypatch.setattr(
        "app.services.runtime.preflight_isolation",
        lambda: IsolationPreflight(
            available=False,
            backend="docker",
            reason="docker daemon is not reachable; refusing to start it",
            details={},
        ),
    )

    async def forbidden_worker(*_args, **_kwargs):
        raise AssertionError("granted execution must not reach the worker")

    monkeypatch.setattr("app.services.runtime.execute_task_granted", forbidden_worker)
    task = run.tasks["T-01"]
    state_before = task["state"]
    revision_before = task["revision"]
    try:
        result = await bench.execute_task(run, "T-01")
        assert result["kind"] == "BLOCKED"
        assert result["isolation_backend"] == "docker"
        assert "docker daemon" in result["reason"]
        assert task["state"] == state_before
        assert task["revision"] == revision_before
        assert task["last_error"] == "isolation_preflight_failed"
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
        assert not escape.exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_worker_rejects_bad_write_specs_before_any_probe(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)

    cases = [
        WriteSpec(str(tmp_path / "absolute.txt"), "x"),
        WriteSpec("../escape.txt", "x"),
        WriteSpec("link.txt", "x"),
    ]
    for spec in cases:
        with pytest.raises(WriteDenied):
            await execute_task_granted(
                "run-1",
                "T-01",
                _grant(["python -c"]),
                isolation_root=root,
                writes=[spec],
                test_command=["python", "-c", "print('ok')"],
                tool_refs=["python -c"],
                whitelist=["python -c"],
            )
    assert outside.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "absolute.txt").exists()
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_worker_fails_closed_without_backend(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    preflight = preflight_isolation(force=True)
    if preflight.available:
        pytest.skip("a real isolation backend is available; covered by the escape test")
    with pytest.raises(IsolationUnavailable):
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(["python -c"]),
            isolation_root=root,
            writes=[WriteSpec("planned.txt", "must not be written")],
            test_command=["python", "-c", "print('ok')"],
            tool_refs=["python -c"],
            whitelist=["python -c"],
        )
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_escape_is_contained_when_backend_available(tmp_path: Path) -> None:
    preflight = preflight_isolation(force=True)
    if not preflight.available:
        pytest.skip(f"no isolation backend on this host: {preflight.reason}")

    root = tmp_path / "wt"
    (root / "tests").mkdir(parents=True)
    outside = tmp_path / "escaped.txt"
    (root / "tests" / "test_escape.py").write_text(
        "from pathlib import Path\n\n"
        "def test_escape() -> None:\n"
        f"    Path({str(outside)!r}).write_text('escaped')\n"
        "    assert True\n",
        encoding="utf-8",
    )
    result = await execute_task_granted(
        "run-1",
        "T-01",
        _grant(["python -m pytest"]),
        isolation_root=root,
        writes=[],
        test_command=["python", "-m", "pytest", "tests/test_escape.py", "-q"],
        whitelist=["python -m pytest"],
        tool_refs=["python -m pytest"],
    )
    assert not outside.exists()
    assert result.exit_code != 0
    assert result.evidence["isolation"]["backend"] == preflight.backend


def test_container_argv_has_no_host_mounts_and_has_limits(tmp_path: Path, monkeypatch) -> None:
    from app.execution.isolation import _docker_argv, safe_env

    work = tmp_path / "wt"
    work.mkdir()
    argv = _docker_argv(
        "docker",
        "python:3.11-slim",
        work,
        ["python", "-c", "print('ok')"],
        container_name="test3-x",
        host_home="/Users/someone",
        env={"PATH": "/usr/bin"},
    )
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert any(arg.startswith("--memory=") for arg in argv)
    assert any(arg.startswith("--cpus=") for arg in argv)
    assert any(arg.startswith("--pids-limit=") for arg in argv)
    mounts = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-v"]
    assert mounts == [f"{work}:/work:rw"]
    assert all(not mount.startswith("/Users") and not mount.startswith("/home") for mount in mounts)
    assert "docker.sock" not in " ".join(argv)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = safe_env(["PATH", "OPENAI_API_KEY"])
    assert env == {"PATH": "/usr/bin"}