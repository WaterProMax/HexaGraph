"""P1-REV-01 / F-05: Grant must guard the real execution boundary.

Every production entry that can execute a granted task (scheduler, retry,
defect recursion, takeover submit) must pass the same fail-closed validation
before any side effect:

* a granted run without a grant never reaches the legacy model/tool agent;
* a grant only covers the tasks it names (no latest-status fallback);
* missing/corrupt ``granted_execution`` and run/task binding mismatches reject;
* the PLAN artifact, approved PLAN digest and materialized spec must agree;
* ordinary revisions/progress do not invalidate an active grant.

Tests exercise production methods with a scripted provider and temporary
directories. ``execution_safety_ready`` is flipped in-process only to reach the
boundary logic; production keeps the gate closed (see F-04 tests).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import GrantRejected
from app.execution.isolation import IsolationPreflight
from app.execution.run_state_store import RunExecutionStateRepo
from app.schemas.docs import TaskCard
from tests.p1_support import install_plan, make_bench, make_grant, persist_granted_profile


def _sentinel(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake(*_args, **_kwargs):
        calls.append("legacy-model-tool-agent")
        raise RuntimeError("sentinel must not be reached")

    monkeypatch.setattr("app.services.runtime.run_tool_agent", fake)
    return calls


async def _prepared(tmp_path: Path, codes: list[str]):
    """Production enable path: materialize, approve PLAN, enable, no grant yet."""
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev01")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, codes)
    plan_hash = bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    await bench.enable_granted_execution(run.id, {"PLAN": plan_hash})
    bench.execution_safety_ready = True
    return bench, run, plan_hash


def _granted_spec(run, code: str) -> dict:
    spec = run.tasks[code].get("granted_execution")
    assert isinstance(spec, dict) and spec
    return spec


async def _add_grant(bench, run, codes: list[str], plan_hash: str, *, status: str = "active"):
    grant = make_grant(run.id, codes, status=status, hashes={"PLAN": plan_hash})
    await bench.add_grant(grant)
    return grant


@pytest.mark.asyncio
async def test_granted_without_grant_or_spec_never_reaches_legacy_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev01")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    await persist_granted_profile(bench, run)
    bench.execution_safety_ready = True
    # Reproduce the review case: granted_v1, no Grant and no produced spec.
    run.tasks["T-01"].pop("granted_execution", None)
    calls = _sentinel(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "grant_required"
        assert excinfo.value.status_code == 403
        assert calls == []
        assert not (tmp_path / "runs" / run.id / "wt" / "T-01").exists()
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_retry_outside_grant_scope_is_rejected_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01", "T-02"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    run.tasks["T-02"]["state"] = "failed"
    run.tasks["T-02"]["revision"] = 1
    calls = _sentinel(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.control_task(run, "T-02", "retry", 1, "review repro")
        assert excinfo.value.category == "scope_mismatch"
        assert calls == []
        assert run.tasks["T-02"]["state"] == "failed"
        assert run.tasks["T-02"]["revision"] == 1
        assert run.tasks["T-02"]["evidence"] == []
        assert not (tmp_path / "runs" / run.id / "wt" / f"granted-{'T-02'}").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "category"),
    [("revoked", "grant_revoked"), ("consumed", "grant_consumed"), ("stale", "baseline_stale")],
)
async def test_inactive_grant_is_rejected(
    tmp_path: Path, status: str, category: str
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash, status=status)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == category
        assert run.tasks["T-01"]["state"] != "done"
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_grant_without_active_status_does_not_fall_back(tmp_path: Path) -> None:
    """An out-of-scope task is rejected instead of using the latest grant."""
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01", "T-02"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    try:
        spec = _granted_spec(run, "T-01")
        assert spec["grant_id"]
        with pytest.raises(GrantRejected) as excinfo:
            await bench._authorize_granted_execution(run, "T-02")
        assert excinfo.value.category == "scope_mismatch"
    finally:
        await bench.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    ["remove", "not_a_dict", "wrong_task", "wrong_grant"],
)
async def test_missing_or_corrupt_granted_spec_is_rejected_without_legacy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    spec = run.tasks["T-01"]["granted_execution"]
    assert isinstance(spec, dict)
    if corruption == "remove":
        run.tasks["T-01"].pop("granted_execution")
    elif corruption == "not_a_dict":
        run.tasks["T-01"]["granted_execution"] = "corrupt"
    elif corruption == "wrong_task":
        spec["task_code"] = "T-02"
    else:
        spec["grant_id"] = "G-some-other-grant"
    calls = _sentinel(monkeypatch)
    expected = "granted_spec_missing" if corruption == "remove" else (
        "granted_spec_invalid" if corruption == "not_a_dict" else "grant_binding_mismatch"
    )
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == expected
        assert calls == []
        assert not (tmp_path / "runs" / run.id / "wt" / "granted-T-01").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_wrong_run_binding_is_rejected(tmp_path: Path) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    foreign = make_grant("some-other-run", ["T-01"], hashes={"PLAN": plan_hash})
    await bench.add_grant(foreign)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "grant_required"
        assert run.tasks["T-01"]["state"] != "done"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_plan_change_after_approval_is_rejected(tmp_path: Path) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    run.artifacts["plan"]["tasks"][0]["title"] = "changed after approval"
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "baseline_stale"
        assert run.tasks["T-01"]["state"] != "done"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_materialized_spec_plan_hash_must_match_current_plan(tmp_path: Path) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    _granted_spec(run, "T-01")["approved_plan_hash"] = "0" * 64
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "baseline_stale"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_authoritative_state_plan_hash_is_checked(tmp_path: Path) -> None:
    """The in-memory/spec copies alone are not enough: SQLite must agree."""
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    try:
        async with bench.db_session() as session:
            repo = RunExecutionStateRepo(session)
            state = await repo.get(run.id)
            assert state is not None
            await repo.upsert(replace(state, approved_plan_hash="0" * 64))
            await session.commit()
        with pytest.raises(GrantRejected) as excinfo:
            await bench.execute_task(run, "T-01")
        assert excinfo.value.category == "baseline_stale"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_authorized_subset_runs_continuously_across_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01", "T-02"])
    await _add_grant(bench, run, ["T-01", "T-02"], plan_hash)
    calls: list[str] = []

    async def fake_worker(run_id, task_code, grant, **_kwargs):
        calls.append(task_code)
        return SimpleNamespace(ok=True, evidence={"ok": True}, evidence_path="")

    monkeypatch.setattr("app.services.runtime.execute_task_granted", fake_worker)
    # F-06 isolation is stubbed here: this test is about grant continuity, not
    # the container backend (which has its own tests and fail-closed coverage).
    monkeypatch.setattr(
        "app.services.runtime.preflight_isolation",
        lambda: IsolationPreflight(available=True, backend="test-double", reason="", details={}),
    )
    try:
        run.revision += 7
        run.tasks["T-01"]["revision"] += 3
        first = await bench.execute_task(run, "T-01")
        assert first["kind"] == "done"
        run.revision += 1
        run.tasks["T-02"]["revision"] += 5
        second = await bench.execute_task(run, "T-02")
        assert second["kind"] == "done"
        assert calls == ["T-01", "T-02"]
        assert run.tasks["T-01"]["state"] == "done"
        assert run.tasks["T-02"]["state"] == "done"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_defect_recursion_revalidates_before_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01", "T-02"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    task = run.tasks["T-02"]
    task["state"] = "failed"
    task["repair_rounds"] = 0
    card = TaskCard.model_validate(task["card"])
    calls = _sentinel(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench._finish_failure(run, task, card, "代码缺陷", "boom", {"exit_code": 1})
        assert excinfo.value.category == "scope_mismatch"
        assert calls == []
        assert task["repair_rounds"] == 0
        assert task["signatures"] == []
        assert task["state"] == "failed"
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_takeover_submit_never_enters_legacy_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    task = run.tasks["T-01"]
    task["state"] = "running"
    task["revision"] = 1
    calls = _sentinel(monkeypatch)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.control_task(run, "T-01", "submit-takeover", 1, "manual merge")
        assert excinfo.value.category == "granted_manual_merge_disabled"
        assert calls == []
        assert task["state"] == "running"
        assert task["revision"] == 1
        assert not task.get("takeover_submit")
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_granted_takeover_creates_no_legacy_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-05 residual entry: ``takeover`` must not build a workspace or lock."""
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    task = run.tasks["T-01"]
    task["state"] = "running"
    task["revision"] = 1
    create_calls: list[str] = []

    def fake_worktree(*_args, **_kwargs):
        create_calls.append("worktree")
        raise AssertionError("granted takeover must not create a worktree")

    monkeypatch.setattr("app.services.runtime.create_worktree", fake_worktree)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.control_task(run, "T-01", "takeover", 1, "manual takeover")
        assert excinfo.value.category == "granted_manual_merge_disabled"
        assert excinfo.value.status_code == 409
        assert create_calls == []
        assert task["state"] == "running"
        assert task["revision"] == 1
        assert not task.get("locked_by")
        assert not (tmp_path / "runs" / run.id / "wt" / "T-01").exists()
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_granted_force_pass_never_runs_legacy_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-05 residual entry: ``force-pass`` must reject before regression/state."""
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    task = run.tasks["T-01"]
    task["state"] = "failed"
    task["revision"] = 1
    evidence_before = list(task["evidence"])
    command_calls: list[list[str]] = []

    async def fake_command(cmd, **_kwargs):
        command_calls.append(list(cmd))
        raise AssertionError("granted force-pass must not run a legacy command")

    monkeypatch.setattr("app.services.runtime.run_command", fake_command)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.control_task(run, "T-01", "force-pass", 1, "bypass")
        assert excinfo.value.category == "granted_force_pass_disabled"
        assert excinfo.value.status_code == 409
        assert command_calls == []
        assert task["state"] == "failed"
        assert task["revision"] == 1
        assert task["evidence"] == evidence_before
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_granted_run_regression_helper_rejects_direct_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    command_calls: list[list[str]] = []

    async def fake_command(cmd, **_kwargs):
        command_calls.append(list(cmd))
        raise AssertionError("granted regression must not run a legacy command")

    monkeypatch.setattr("app.services.runtime.run_command", fake_command)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench._run_regression(run, tmp_path / "repo", "T-01")
        assert excinfo.value.category == "granted_force_pass_disabled"
        assert command_calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_granted_accept_is_rejected_before_acceptance_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-05 residual entry: run-level ``accept`` must not enter the legacy flow."""
    bench, run, plan_hash = await _prepared(tmp_path, ["T-01"])
    await _add_grant(bench, run, ["T-01"], plan_hash)
    task = run.tasks["T-01"]
    task["state"] = "verifying"
    task["revision"] = 1
    gates_before = list(run.gates)
    command_calls: list[list[str]] = []

    async def fake_command(cmd, **_kwargs):
        command_calls.append(list(cmd))
        raise AssertionError("granted accept must not run legacy acceptance commands")

    monkeypatch.setattr("app.services.runtime.run_command", fake_command)
    try:
        with pytest.raises(GrantRejected) as excinfo:
            await bench.accept(run)
        assert excinfo.value.category == "granted_acceptance_disabled"
        assert excinfo.value.status_code == 409
        assert command_calls == []
        assert task["state"] == "verifying"
        assert task["revision"] == 1
        assert run.gates == gates_before
        assert "acceptance" not in run.artifacts
    finally:
        await bench.close()