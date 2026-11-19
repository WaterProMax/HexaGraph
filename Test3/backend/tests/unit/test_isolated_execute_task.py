from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.execution.isolated import WriteSpec, execute_task_granted
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
        allowed_tool_refs=[],
        created_at="2026-11-19T00:00:00+00:00",
    )


@pytest.fixture
async def iso(tmp_path: Path) -> Path:
    root = tmp_path / "iso"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_writes_stay_inside_isolation_root(iso: Path, tmp_path: Path) -> None:
    another_root = tmp_path / "user-project"
    another_root.mkdir()
    result = await execute_task_granted(
        "run-1",
        "T-01",
        _grant(),
        isolation_root=iso,
        writes=[WriteSpec("foo.txt", "bar")],
        test_command=["python", "-c", "print('ok')"],
    )
    assert (iso / "foo.txt").read_text(encoding="utf-8") == "bar"
    assert not (another_root / "foo.txt").exists()
    assert result.exit_code == 0
    assert result.evidence["commands"][0]["exit_code"] == 0
    assert Path(result.log_path).is_file()
    assert "ok" in Path(result.log_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_failing_offline_test_is_not_success(iso: Path) -> None:
    result = await execute_task_granted(
        "run-1",
        "T-02",
        _grant(),
        isolation_root=iso,
        writes=[WriteSpec("tests/test_fail.py", "def test_fail():\n    assert False\n")],
        test_command=["python", "-m", "pytest", "tests/test_fail.py", "-q"],
    )
    assert result.exit_code != 0
    assert result.evidence["ok"] is False
    assert result.evidence["commands"][0]["exit_code"] != 0


@pytest.mark.asyncio
async def test_evidence_and_log_redact_secret_env(iso: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    result = await execute_task_granted(
        "run-1",
        "T-03",
        _grant(),
        isolation_root=iso,
        writes=[],
        test_command=["python", "-c", "import os\nprint(os.environ.get('OPENAI_API_KEY',''))"],
        env_allow=["PATH", "OPENAI_API_KEY"],
    )
    evidence_text = Path(result.evidence_path).read_text(encoding="utf-8")
    log_text = Path(result.log_path).read_text(encoding="utf-8")
    assert "sk-test-secret" not in evidence_text
    assert "sk-test-secret" not in log_text
    assert "***REDACTED***" in log_text
    json.loads(evidence_text)


@pytest.mark.asyncio
async def test_parallel_tasks_do_not_cross_write(tmp_path: Path) -> None:
    first = tmp_path / "iso-a"
    second = tmp_path / "iso-b"
    first.mkdir()
    second.mkdir()
    await asyncio.gather(
        execute_task_granted(
            "run-1", "A", _grant(), isolation_root=first, writes=[WriteSpec("a.txt", "A")],
            test_command=["python", "-c", "print('a')"],
        ),
        execute_task_granted(
            "run-1", "B", _grant(), isolation_root=second, writes=[WriteSpec("b.txt", "B")],
            test_command=["python", "-c", "print('b')"],
        ),
    )
    assert (first / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (first / "b.txt").exists()
    assert (second / "b.txt").read_text(encoding="utf-8") == "B"
    assert not (second / "a.txt").exists()