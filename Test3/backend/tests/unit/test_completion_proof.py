"""Card C: completion proof is the attempt's integrated, in-scope diff."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.execution.run_profile import run_approved_baseline_hashes
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.docs import TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workspace.gitops import _git_sync, commit, create_worktree, init_repo_sync, merge
from tests.p1_support import make_card


def _bench(tmp_path: Path) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider([])),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )


def _prepare(
    tmp_path: Path,
    *,
    write_set: list[str] | None = None,
    initial_files: dict[str, str] | None = None,
):
    bench = _bench(tmp_path)
    project = bench.create_project("proof")
    run = bench.create_run(project["id"], "idea")
    run.engine.current = "6"
    write_set = list(write_set or ["src/T-01.py"])
    card = make_card("T-01", write_set=write_set)
    run.artifacts["plan"] = TaskGraph(tasks=[card]).model_dump()
    bench._materialize_tasks(run)
    bench._record_approved_baseline(run, "PLAN", run.artifacts["plan"])
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, initial_files or {"README.md": "x\n"})
    base = _git_sync(repo, "rev-parse", "HEAD")[1].strip()
    ref = _git_sync(repo, "symbolic-ref", "-q", "HEAD")[1].strip()
    return bench, run, repo, base, ref, write_set


def _task_worktree(bench: Workbench, run, repo: Path) -> Path:
    wt = bench.data_dir / "runs" / run.id / "wt" / "T-01"
    create_worktree(repo, wt, "task/T-01")
    return wt


def _commit_task_work(repo: Path, wt: Path) -> str:
    _git_sync(wt, "add", "-A")
    return commit(wt, "task work")


def _seed_attempt(
    bench: Workbench,
    run,
    repo: Path,
    *,
    base: str,
    ref: str,
    branch: str,
    work_commit: str,
    write_set: list[str],
    merged: bool,
    integration_ref: str | None = None,
):
    if merged:
        merged_result = merge(repo, branch)
        assert merged_result["ok"] is True, merged_result
    task = run.tasks["T-01"]
    attempt = {
        "attempt_id": "A-1",
        "intent": "execute",
        "status": "finished_ok",
        "baseline_hashes": dict(run_approved_baseline_hashes(run)),
        "repo": str(repo),
        "repo_identity": str(repo.resolve()),
        "worktree": str(bench.data_dir / "runs" / run.id / "wt" / "T-01"),
        "branch": branch,
        "base_commit": base,
        "integration_ref": integration_ref or ref,
        "integration_ref_sha": base,
        "target_branch": ref,
        "commit": work_commit,
        "write_set": list(write_set),
        "task_code": "T-01",
        "run_id": run.id,
        "project_id": run.project_id,
    }
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    task["needs_reconciliation"] = True
    task["paused"] = True
    bench._set_state(run, task, "scheduled")
    bench._persist_snapshot(run)
    return task, attempt


async def _accept(bench, run, task):
    return await bench.resolve_reconciliation(
        run, "T-01", "accept_evidence", task["revision"], actor="leader", reason="verified"
    )


@pytest.mark.asyncio
async def test_merged_in_scope_change_can_be_accepted(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )

    report = await _accept(bench, run, task)
    assert task["state"] == "done"
    assert task["needs_reconciliation"] is False
    assert task["completion_proof"]["ok"] is True
    assert task["completion_proof"]["base_commit"] == base
    assert task["completion_proof"]["changed"] == ["src/T-01.py"]
    assert report["needs_reconciliation"] is False


@pytest.mark.asyncio
async def test_existing_unchanged_file_is_not_completion(tmp_path) -> None:
    bench, run, repo, base, ref, _write_set = _prepare(tmp_path, write_set=["README.md"])
    _task_worktree(bench, run, repo)
    task, _attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=base, write_set=["README.md"], merged=True
    )
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "no_relevant_changes" in str(exc.value)
    assert task["needs_reconciliation"] is True


@pytest.mark.asyncio
async def test_unmerged_task_branch_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=False
    )
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "commit_not_integrated" in str(exc.value)


@pytest.mark.asyncio
async def test_change_outside_write_set_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "extra.txt").write_text("unexpected\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "changes_outside_write_set" in str(exc.value)
    assert "extra.txt" in str(exc.value)


@pytest.mark.asyncio
async def test_other_repo_identity_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    other = tmp_path / "other-repo"
    init_repo_sync(other, {"README.md": "other\n"})
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )
    attempt["repo"] = str(other)
    attempt["repo_identity"] = str(other.resolve())
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    bench._persist_snapshot(run)
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "repo_identity_mismatch" in str(exc.value)


@pytest.mark.asyncio
async def test_baseline_drift_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )
    bench._record_approved_baseline(run, "PLAN", {"tasks": [], "work_packages": []})
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "baseline_mismatch" in str(exc.value)


@pytest.mark.asyncio
async def test_frozen_integration_fields_are_required(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )
    attempt.pop("base_commit")
    attempt.pop("integration_ref")
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    bench._persist_snapshot(run)
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "attempt_proof_fields_missing" in str(exc.value)


@pytest.mark.asyncio
async def test_integration_ref_rewritten_to_unrelated_history_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    # The task work is merged into the real integration ref, but the attempt
    # names a different ref that stays on the base commit.
    _git_sync(repo, "branch", "unrelated", base)
    task, _attempt = _seed_attempt(
        bench,
        run,
        repo,
        base=base,
        ref=ref,
        branch="task/T-01",
        work_commit=work,
        write_set=write_set,
        merged=True,
        integration_ref="refs/heads/unrelated",
    )
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "commit_not_integrated" in str(exc.value)


@pytest.mark.asyncio
async def test_merge_commit_can_be_the_proven_product(tmp_path) -> None:
    bench, run, repo, base, ref, write_set = _prepare(tmp_path)
    wt = _task_worktree(bench, run, repo)
    (wt / "src").mkdir()
    (wt / "src" / "T-01.py").write_text("print('ok')\n", encoding="utf-8")
    work = _commit_task_work(repo, wt)
    task, attempt = _seed_attempt(
        bench, run, repo, base=base, ref=ref, branch="task/T-01", work_commit=work, write_set=write_set, merged=True
    )
    merged_head = _git_sync(repo, "rev-parse", "HEAD")[1].strip()
    assert merged_head != work
    attempt["commit"] = merged_head
    task["attempt"] = attempt
    task["attempt_history"] = [dict(attempt)]
    bench._persist_snapshot(run)

    await _accept(bench, run, task)
    assert task["state"] == "done"
    assert task["completion_proof"]["branch_binding"] == "branch_merged_into_commit"


@pytest.mark.asyncio
async def test_authorized_deletion_passes(tmp_path) -> None:
    bench, run, repo, base, ref, _write_set = _prepare(
        tmp_path, write_set=["src/old.py"], initial_files={"README.md": "x\n", "src/old.py": "old\n"}
    )
    wt = _task_worktree(bench, run, repo)
    (wt / "src" / "old.py").unlink()
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench,
        run,
        repo,
        base=base,
        ref=ref,
        branch="task/T-01",
        work_commit=work,
        write_set=["src/old.py"],
        merged=True,
    )
    await _accept(bench, run, task)
    assert task["state"] == "done"
    assert task["completion_proof"]["changed"] == ["src/old.py"]


@pytest.mark.asyncio
async def test_authorized_rename_passes(tmp_path) -> None:
    bench, run, repo, base, ref, _write_set = _prepare(
        tmp_path,
        write_set=["src/old.py", "src/new.py"],
        initial_files={"README.md": "x\n", "src/old.py": "old\n"},
    )
    wt = _task_worktree(bench, run, repo)
    _git_sync(wt, "mv", "src/old.py", "src/new.py")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench,
        run,
        repo,
        base=base,
        ref=ref,
        branch="task/T-01",
        work_commit=work,
        write_set=["src/old.py", "src/new.py"],
        merged=True,
    )
    await _accept(bench, run, task)
    assert task["state"] == "done"
    assert task["completion_proof"]["changed"] == ["src/new.py", "src/old.py"]


@pytest.mark.asyncio
async def test_rename_source_outside_write_set_is_rejected(tmp_path) -> None:
    bench, run, repo, base, ref, _write_set = _prepare(
        tmp_path, write_set=["src/new.py"], initial_files={"README.md": "x\n", "src/old.py": "old\n"}
    )
    wt = _task_worktree(bench, run, repo)
    _git_sync(wt, "mv", "src/old.py", "src/new.py")
    work = _commit_task_work(repo, wt)
    task, _attempt = _seed_attempt(
        bench,
        run,
        repo,
        base=base,
        ref=ref,
        branch="task/T-01",
        work_commit=work,
        write_set=["src/new.py"],
        merged=True,
    )
    with pytest.raises(Exception) as exc:
        await _accept(bench, run, task)
    assert "changes_outside_write_set" in str(exc.value)
    assert "src/old.py" in str(exc.value)


def test_begin_attempt_freezes_integration_ref_and_base(tmp_path) -> None:
    bench, run, repo, base, ref, _write_set = _prepare(tmp_path)
    task = run.tasks["T-01"]
    bench._begin_attempt(run, task, "T-01", repo=repo)
    attempt = task["attempt"]
    assert attempt["base_commit"] == base
    assert attempt["integration_ref"] == ref
    assert attempt["integration_ref_sha"] == base
    assert attempt["target_branch"] == ref
    assert attempt["proof_ready"] is True


def test_detached_head_is_not_auto_provable(tmp_path) -> None:
    bench, run, repo, _base, _ref, _write_set = _prepare(tmp_path)
    _git_sync(repo, "checkout", "--detach")
    task = run.tasks["T-01"]
    bench._begin_attempt(run, task, "T-01", repo=repo)
    attempt = task["attempt"]
    assert attempt["base_commit"] == ""
    assert attempt["integration_ref"] == ""
    assert attempt["proof_ready"] is False
    assert attempt["proof_unknown_reason"] == "detached_or_unresolvable_integration_ref"


def test_missing_grant_integration_hint_fails_closed(tmp_path) -> None:
    bench, run, repo, _base, _ref, _write_set = _prepare(tmp_path)
    task = run.tasks["T-01"]
    bench._begin_attempt(run, task, "T-01", repo=repo, integration_hint="teamwork-001")
    attempt = task["attempt"]
    assert attempt["integration_ref"] == ""
    assert attempt["base_commit"] == ""
    assert attempt["proof_ready"] is False
    assert attempt["proof_unknown_reason"] == "integration_hint_missing"