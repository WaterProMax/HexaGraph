from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.execution.isolated import (
    WriteSpec,
    build_evidence,
    execute_task_granted,
    redact_secrets,
    stage_writes,
)
from app.execution.isolation import preflight_isolation
from app.schemas.execution_grant import ExecutionGrant


def _grant(feature_branch: str = "feat/p1-demo") -> ExecutionGrant:
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
        feature_branch=feature_branch,
        allowed_tool_refs=["python -m pytest"],
        created_at="2026-11-19T00:00:00+00:00",
    )


@pytest.fixture
async def iso(tmp_path: Path) -> Path:
    root = tmp_path / "iso"
    root.mkdir()
    return root


def test_writes_stay_inside_isolation_root(iso: Path, tmp_path: Path) -> None:
    another_root = tmp_path / "user-project"
    another_root.mkdir()
    written = stage_writes(iso, [WriteSpec("foo.txt", "bar")], ["foo.txt"])
    assert written == ["foo.txt"]
    assert (iso / "foo.txt").read_text(encoding="utf-8") == "bar"
    assert not (another_root / "foo.txt").exists()


@pytest.mark.asyncio
async def test_failing_offline_test_is_not_success(iso: Path) -> None:
    preflight = preflight_isolation()
    if not preflight.available:
        pytest.skip(f"no isolation backend on this host: {preflight.reason}")
    result = await execute_task_granted(
        "run-1",
        "T-01",
        _grant(),
        isolation_root=iso,
        writes=[WriteSpec("tests/test_fail.py", "def test_fail():\n    assert False\n")],
        test_command=["python", "-m", "pytest", "tests/test_fail.py", "-q"],
        tool_refs=["python -m pytest"],
        whitelist=["python -m pytest"],
    )
    assert result.exit_code != 0
    assert result.evidence["ok"] is False
    assert result.evidence["commands"][0]["exit_code"] != 0
    assert result.evidence["isolation"]["backend"] == preflight.backend


def test_evidence_and_log_redact_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    output = redact_secrets("value=sk-test-secret rest", ["OPENAI_API_KEY"])
    assert "sk-test-secret" not in output
    assert "***REDACTED***" in output

    from app.execution.isolated import CommandResult

    command = CommandResult(
        argv=["python", "-c", "print('ok')"],
        cwd="/work",
        exit_code=0,
        log_path="/tmp/probe.log",
        output=output,
    )
    evidence = build_evidence("T-03", [command], isolation_root="/tmp/iso", written=[], secret_refs=["OPENAI_API_KEY"])
    text = json.dumps(evidence, ensure_ascii=False)
    assert "sk-test-secret" not in text
    assert "***REDACTED***" in text
    assert evidence["ok"] is True


@pytest.mark.asyncio
async def test_parallel_tasks_do_not_cross_write(tmp_path: Path) -> None:
    first = tmp_path / "iso-a"
    second = tmp_path / "iso-b"
    first.mkdir()
    second.mkdir()
    await asyncio.gather(
        asyncio.to_thread(stage_writes, first, [WriteSpec("a.txt", "A")], ["a.txt"]),
        asyncio.to_thread(stage_writes, second, [WriteSpec("b.txt", "B")], ["b.txt"]),
    )
    assert (first / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (first / "b.txt").exists()
    assert (second / "b.txt").read_text(encoding="utf-8") == "B"
    assert not (second / "a.txt").exists()