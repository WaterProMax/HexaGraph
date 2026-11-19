"""P1-F08: granted execution needs platform ∩ grant ∩ materialized spec.

Every test uses the real authorization and filesystem layers.  Only the
container boundary (preflight/run) is replaced, because Docker is unavailable on
this host.  Rejection tests prove zero side effects: no worktree, no staged
write, no command, no evidence directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import GrantRejected
from app.execution import evidence as evidence_store
from app.execution.isolated import execute_task_granted
from app.execution.isolation import IsolationPreflight
from app.schemas.execution_grant import ExecutionGrant
from tests.p1_support import install_plan, make_bench, make_grant

PLATFORM_ALLOWED = ["python -m pytest"]


def _grant(
    *,
    run_id: str = "run-1",
    task_codes: list[str] | None = None,
    tool_refs: list[str] | None = None,
) -> ExecutionGrant:
    return ExecutionGrant(
        grant_id="G-1",
        run_id=run_id,
        execution_profile="granted_v1",
        task_codes=list(task_codes or ["T-01"]),
        approved_baseline_hashes={"PLAN": "aaa"},
        repo_remote="origin",
        repo_owner="WaterProMax",
        repo_name="HexaGraph",
        base_branch="teamwork-001",
        feature_branch="feat/p1-demo",
        allowed_tool_refs=list(tool_refs or []),
        created_at="2026-11-19T00:00:00+00:00",
    )


async def _prepared(
    tmp_path: Path,
    *,
    grant_refs: list[str],
    spec_tool_refs: list[str] | None = None,
    spec_command: list[str] | None = None,
    card_command: list[str] | None = None,
):
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-f08")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    if card_command is not None:
        run.tasks["T-01"]["card"]["acceptance"][0]["cmd"] = list(card_command)
    plan_hash = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    await bench.enable_granted_execution(run.id, {"PLAN": plan_hash})
    await bench.add_grant(
        make_grant(run.id, ["T-01"], hashes={"PLAN": plan_hash}, allowed_tool_refs=grant_refs)
    )
    spec = run.tasks["T-01"]["granted_execution"]
    if spec_tool_refs is not None:
        spec["tool_refs"] = list(spec_tool_refs)
    if spec_command is not None:
        spec["command"] = list(spec_command)
    bench.execution_safety_ready = True
    return bench, run


def _forbid_side_effects(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def sentinel(name: str):
        def record(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"{name} must not be reached")

        return record

    monkeypatch.setattr("app.services.runtime.create_worktree", sentinel("create_worktree"))
    monkeypatch.setattr("app.services.runtime.execute_task_granted", sentinel("execute_task_granted"))
    monkeypatch.setattr("app.services.runtime.preflight_isolation", sentinel("preflight_isolation"))
    monkeypatch.setattr("app.execution.isolated.preflight_isolation", sentinel("worker_preflight"))
    monkeypatch.setattr("app.execution.isolated.run_isolated", sentinel("run_isolated"))
    monkeypatch.setattr("app.execution.evidence.create_evidence_dir", sentinel("create_evidence_dir"))
    return calls


@pytest.mark.asyncio
async def test_wrapper_rejects_when_platform_allows_but_grant_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(tmp_path, grant_refs=["python -m ruff"])
    task = run.tasks["T-01"]
    revision_before = task["revision"]
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "grant_tool_denied"
        assert excinfo.value.status_code == 403
        assert calls == []
        assert task["revision"] == revision_before
        assert sentinel.read_text(encoding="utf-8") == "keep"
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrapper_rejects_when_grant_allows_but_platform_forbids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(
        tmp_path,
        grant_refs=["python -c"],
        card_command=["python", "-c", "print('ok')"],
    )
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "platform_tool_denied"
        assert excinfo.value.status_code == 403
        assert calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrapper_rejects_spec_tool_refs_outside_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(
        tmp_path,
        grant_refs=["python -m pytest"],
        spec_tool_refs=["python -m pytest", "python -m ruff"],
    )
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "spec_tool_refs_conflict"
        assert excinfo.value.status_code == 409
        assert calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrapper_rejects_when_spec_does_not_cover_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(
        tmp_path,
        grant_refs=["python -m pytest", "python -m ruff"],
        spec_tool_refs=["python -m ruff"],
    )
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "spec_tool_denied"
        assert excinfo.value.status_code == 409
        assert calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrapper_rejects_empty_grant_tool_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(tmp_path, grant_refs=[])
    task = run.tasks["T-01"]
    revision_before = task["revision"]
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "grant_tool_refs_empty"
        assert excinfo.value.status_code == 403
        assert calls == []
        assert task["revision"] == revision_before
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrapper_rejects_empty_materialized_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(tmp_path, grant_refs=PLATFORM_ALLOWED, spec_command=[])
    calls = _forbid_side_effects(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "spec_command_missing"
        assert excinfo.value.status_code == 409
        assert calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_three_layers_agree_reaches_isolated_boundary_with_exact_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run = await _prepared(tmp_path, grant_refs=PLATFORM_ALLOWED)
    captured: list[list[str]] = []
    created_dirs: list[Path] = []
    real_create = evidence_store.create_evidence_dir

    def tracking_create() -> Path:
        directory = real_create()
        created_dirs.append(directory)
        return directory

    monkeypatch.setattr("app.services.runtime.preflight_isolation", _available)
    monkeypatch.setattr("app.execution.isolated.preflight_isolation", _available)
    monkeypatch.setattr("app.execution.evidence.create_evidence_dir", tracking_create)

    async def fake_run(argv, *, cwd, timeout, env_allow=None, output_limit=None):
        captured.append(list(argv))
        return {
            "exit_code": 0,
            "output": "ok\n",
            "timeout": False,
            "truncated": False,
            "backend": "docker",
            "image": "test-image",
        }

    monkeypatch.setattr("app.execution.isolated.run_isolated", fake_run)
    try:
        result = await bench.execute_task(run, "T-01")
        assert result["kind"] == "done"
        assert captured == [["python", "-m", "pytest", "-q"]]
        assert created_dirs
        assert all(directory.exists() for directory in created_dirs)
    finally:
        for directory in created_dirs:
            evidence_store.cleanup_evidence_dir(directory)
        await bench.close()


def _available() -> IsolationPreflight:
    return IsolationPreflight(available=True, backend="docker", reason="", details={"image": "test-image"})


@pytest.mark.asyncio
async def test_worker_rejects_wrong_run_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    guard: list[str] = []

    def guard_preflight():
        guard.append("preflight")
        raise AssertionError("binding rejection must happen before preflight")

    monkeypatch.setattr("app.execution.isolated.preflight_isolation", guard_preflight)
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(run_id="other-run", tool_refs=["python -c"]),
            isolation_root=root,
            test_command=["python", "-c", "print('ok')"],
            tool_refs=["python -c"],
            whitelist=["python -c"],
        )
    assert excinfo.value.category == "grant_binding_mismatch"
    assert excinfo.value.status_code == 409
    assert guard == []
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_worker_rejects_task_outside_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    guard: list[str] = []

    def guard_preflight():
        guard.append("preflight")
        raise AssertionError("scope rejection must happen before preflight")

    monkeypatch.setattr("app.execution.isolated.preflight_isolation", guard_preflight)
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-02",
            _grant(task_codes=["T-01"], tool_refs=["python -c"]),
            isolation_root=root,
            test_command=["python", "-c", "print('ok')"],
            tool_refs=["python -c"],
            whitelist=["python -c"],
        )
    assert excinfo.value.category == "scope_mismatch"
    assert excinfo.value.status_code == 409
    assert guard == []
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_worker_rejects_platform_denied_even_when_granted(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=["python -c"]),
            isolation_root=tmp_path,
            test_command=["python", "-c", "print('ok')"],
            tool_refs=["python -c"],
            whitelist=["python -m ruff"],
        )
    assert excinfo.value.category == "platform_tool_denied"
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_rejects_grant_denied_even_when_platform_allows(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=["python -m ruff"]),
            isolation_root=tmp_path,
            test_command=["python", "-m", "pytest", "-q"],
            tool_refs=["python -m ruff"],
            whitelist=PLATFORM_ALLOWED,
        )
    assert excinfo.value.category == "grant_tool_denied"
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_rejects_empty_grant_refs(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=["", "   "]),
            isolation_root=tmp_path,
            test_command=["python", "-m", "pytest", "-q"],
            tool_refs=["python -m pytest"],
            whitelist=PLATFORM_ALLOWED,
        )
    assert excinfo.value.category == "grant_tool_refs_empty"
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_rejects_empty_command_without_defaulting_to_pytest(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=PLATFORM_ALLOWED),
            isolation_root=tmp_path,
            test_command=[],
            tool_refs=PLATFORM_ALLOWED,
            whitelist=PLATFORM_ALLOWED,
        )
    assert excinfo.value.category == "spec_command_missing"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_worker_rejects_missing_spec_tool_refs(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=PLATFORM_ALLOWED),
            isolation_root=tmp_path,
            test_command=["python", "-m", "pytest", "-q"],
            tool_refs=[],
            whitelist=PLATFORM_ALLOWED,
        )
    assert excinfo.value.category == "spec_tool_refs_missing"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_worker_rejects_spec_command_mismatch(tmp_path: Path) -> None:
    with pytest.raises(GrantRejected) as excinfo:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=PLATFORM_ALLOWED),
            isolation_root=tmp_path,
            test_command=["python", "-m", "pytest", "-q"],
            tool_refs=PLATFORM_ALLOWED,
            spec_command=["python", "-m", "pytest", "-x"],
            whitelist=PLATFORM_ALLOWED,
        )
    assert excinfo.value.category == "spec_command_mismatch"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_worker_happy_path_runs_exact_authorized_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []
    created: list[Path] = []
    real_create = evidence_store.create_evidence_dir

    def tracking_create() -> Path:
        directory = real_create()
        created.append(directory)
        return directory

    monkeypatch.setattr("app.execution.isolated.preflight_isolation", _available)
    monkeypatch.setattr("app.execution.evidence.create_evidence_dir", tracking_create)

    async def fake_run(argv, *, cwd, timeout, env_allow=None, output_limit=None):
        captured.append(list(argv))
        return {
            "exit_code": 0,
            "output": "ok\n",
            "timeout": False,
            "truncated": False,
            "backend": "docker",
            "image": "test-image",
        }

    monkeypatch.setattr("app.execution.isolated.run_isolated", fake_run)
    root = tmp_path / "wt"
    root.mkdir()
    try:
        result = await execute_task_granted(
            "run-1",
            "T-01",
            _grant(tool_refs=PLATFORM_ALLOWED),
            isolation_root=root,
            test_command=["python", "-m", "pytest", "-q"],
            tool_refs=PLATFORM_ALLOWED,
            spec_command=["python", "-m", "pytest", "-q"],
            whitelist=PLATFORM_ALLOWED,
        )
        assert result.ok
        assert captured == [["python", "-m", "pytest", "-q"]]
        assert created
    finally:
        for directory in created:
            evidence_store.cleanup_evidence_dir(directory)