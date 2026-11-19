"""P1-REV-01: Grant must guard the real execution boundary.

Reproduces the two report cases without a real model or network:

* granted_v1 run, no Grant, no produced execution spec -> sentinel must not run;
* a Grant for T-01 only, retrying T-02 -> T-02 must not execute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import GrantRejected
from tests.p1_support import install_plan, make_bench, make_grant, persist_granted_profile


async def _granted_bench(tmp_path: Path, codes: list[str]):
    bench = make_bench(tmp_path)
    project = bench.create_project("p1-rev01")
    run = bench.create_run(project["id"], "idea")
    install_plan(bench, run, codes)
    await persist_granted_profile(bench, run)
    return bench, run


@pytest.mark.asyncio
async def test_granted_without_grant_or_spec_never_reaches_legacy_agent(tmp_path: Path, monkeypatch) -> None:
    bench, run = await _granted_bench(tmp_path, ["T-01"])
    sentinel_calls: list[str] = []

    async def sentinel(*_args, **_kwargs):
        sentinel_calls.append("legacy-model-tool-agent")
        raise RuntimeError("sentinel must not be reached")

    monkeypatch.setattr("app.services.runtime.run_tool_agent", sentinel)
    try:
        with pytest.raises(GrantRejected):
            await bench.execute_task(run, "T-01")
        assert sentinel_calls == []
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_retry_outside_grant_scope_is_not_done(tmp_path: Path, monkeypatch) -> None:
    bench, run = await _granted_bench(tmp_path, ["T-01", "T-02"])
    # Grant covers T-01 only; T-02 is retryable but outside the approved scope.
    await bench.add_grant(make_grant(run.id, ["T-01"]))
    run.tasks["T-02"]["state"] = "failed"
    run.tasks["T-02"]["revision"] = 1
    sentinel_calls: list[str] = []

    async def sentinel(*_args, **_kwargs):
        sentinel_calls.append("legacy-model-tool-agent")
        raise RuntimeError("sentinel must not be reached")

    monkeypatch.setattr("app.services.runtime.run_tool_agent", sentinel)
    try:
        with pytest.raises(GrantRejected):
            await bench.control_task(run, "T-02", "retry", 1, "review repro")
        assert sentinel_calls == []
        assert run.tasks["T-02"]["state"] != "done"
    finally:
        await bench.close()