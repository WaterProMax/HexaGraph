"""P1-REV-04: restart / corrupt snapshot / events-only restore must not downgrade.

The pre-fix tree keeps profile and hashes only in the JSON snapshot, so a normal
restart (setter does not persist) and a corrupt snapshot both resolve to legacy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.run_profile import run_execution_profile
from tests.p1_support import install_plan, make_bench, make_grant, persist_granted_profile


async def _prepared(tmp_path: Path):
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev04")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    await persist_granted_profile(bench, run, {"PLAN": "aaa"})
    await bench.add_grant(make_grant(run.id, ["T-01"]))
    return bench, run


@pytest.mark.asyncio
async def test_normal_restart_keeps_granted_profile(tmp_path: Path) -> None:
    bench, run = await _prepared(tmp_path)
    run_id = run.id
    await bench.close()

    restored_bench = make_bench(tmp_path)
    try:
        restored = restored_bench.runs[run_id]
        assert run_execution_profile(restored) == "granted_v1"
    finally:
        await restored_bench.close()


@pytest.mark.asyncio
async def test_corrupt_snapshot_events_only_keeps_granted(tmp_path: Path) -> None:
    bench, run = await _prepared(tmp_path)
    run_id = run.id
    bench._persist_snapshot(run)
    snapshot = tmp_path / "runs" / run_id / "snapshot.json"
    snapshot.write_text("{not valid json", encoding="utf-8")
    await bench.close()

    restored_bench = make_bench(tmp_path)
    try:
        restored = restored_bench.runs[run_id]
        assert run_execution_profile(restored) == "granted_v1"
        assert restored.approved_baseline_hashes == {"PLAN": "aaa"}
    finally:
        await restored_bench.close()


@pytest.mark.asyncio
async def test_missing_profile_is_unspecified_not_legacy(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev04")
    run = bench.create_run(project["id"], "idea")
    run.artifacts.pop("execution_profile", None)
    run.execution_profile = ""
    bench._persist_snapshot(run)
    await bench.close()

    restored_bench = make_bench(tmp_path)
    try:
        assert run_execution_profile(restored_bench.runs[run.id]) == "unspecified"
    finally:
        await restored_bench.close()


@pytest.mark.asyncio
async def test_legacy_run_stays_legacy_and_events_are_not_rewritten(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev04")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    await bench.close()
    events_path = tmp_path / "runs" / run.id / "events.jsonl"
    before = events_path.read_text(encoding="utf-8")

    restored_bench = make_bench(tmp_path)
    try:
        restored = restored_bench.runs[run.id]
        assert run_execution_profile(restored) == "legacy"
        assert events_path.read_text(encoding="utf-8") == before
    finally:
        await restored_bench.close()

@pytest.mark.asyncio
async def test_unspecified_profile_fails_closed_on_schedule(tmp_path: Path) -> None:
    from app.errors import GrantRejected

    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev04")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, ["T-01"])
    run.artifacts.pop("execution_profile", None)
    run.execution_profile = ""
    bench._persist_snapshot(run)
    await bench.close()

    restored_bench = make_bench(tmp_path)
    try:
        restored = restored_bench.runs[run.id]
        with pytest.raises(GrantRejected) as excinfo:
            await restored_bench.schedule_once(restored, task_codes={"T-01"})
        assert excinfo.value.category == "profile_unspecified"
    finally:
        await restored_bench.close()


@pytest.mark.asyncio
async def test_sqlite_and_snapshot_conflict_fails_closed(tmp_path: Path) -> None:
    import json

    from app.errors import GrantRejected

    bench, run = await _prepared(tmp_path)
    run_id = run.id
    await bench.close()

    snapshot = tmp_path / "runs" / run_id / "snapshot.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["execution_profile"] = "legacy"
    data.setdefault("artifacts", {})["execution_profile"] = "legacy"
    snapshot.write_text(json.dumps(data), encoding="utf-8")

    restored_bench = make_bench(tmp_path)
    try:
        restored = restored_bench.runs[run_id]
        assert run_execution_profile(restored) == "conflict"
        with pytest.raises(GrantRejected) as excinfo:
            await restored_bench.schedule_once(restored, task_codes={"T-01"})
        assert excinfo.value.category == "profile_conflict"
    finally:
        await restored_bench.close()


@pytest.mark.asyncio
async def test_conflict_survives_a_second_restart(tmp_path: Path) -> None:
    import json

    bench, run = await _prepared(tmp_path)
    run_id = run.id
    await bench.close()
    snapshot = tmp_path / "runs" / run_id / "snapshot.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["execution_profile"] = "legacy"
    data.setdefault("artifacts", {})["execution_profile"] = "legacy"
    snapshot.write_text(json.dumps(data), encoding="utf-8")

    first = make_bench(tmp_path)
    try:
        assert run_execution_profile(first.runs[run_id]) == "conflict"
    finally:
        await first.close()
    second = make_bench(tmp_path)
    try:
        assert run_execution_profile(second.runs[run_id]) == "conflict"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_approved_hash_update_is_persisted_without_false_conflict(tmp_path: Path) -> None:
    from app.execution.run_profile import run_approved_baseline_hashes

    bench, run = await _prepared(tmp_path)
    run_id = run.id
    bench._record_approved_baseline(run, "PLAN", {"plan": "v2"})
    await bench._refresh_grant_statuses(run)
    expected = run_approved_baseline_hashes(run)
    await bench.close()

    restored = make_bench(tmp_path)
    try:
        recovered = restored.runs[run_id]
        assert run_execution_profile(recovered) == "granted_v1"
        assert run_approved_baseline_hashes(recovered) == expected
    finally:
        await restored.close()
