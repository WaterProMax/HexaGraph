"""P1-REV-03: a whitelisted test process and the evidence writer must stay inside.

Every escape target lives under ``tmp_path``; nothing here touches user data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.isolated import execute_task_granted
from app.schemas.execution_grant import ExecutionGrant


def _grant() -> ExecutionGrant:
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
        allowed_tool_refs=[],
        created_at="2026-11-19T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_evidence_symlink_cannot_redirect_writes(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside-evidence"
    outside.mkdir()
    evidence = tmp_path / "wt-evidence"
    evidence.symlink_to(outside, target_is_directory=True)

    try:
        await execute_task_granted(
            "run-1",
            "T-01",
            _grant(),
            isolation_root=root,
            writes=[],
            test_command=["python", "-m", "pytest", "-q"],
        )
    except Exception:
        pass
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_whitelisted_pytest_cannot_write_absolute_outside_path(tmp_path: Path) -> None:
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
    await execute_task_granted(
        "run-1",
        "T-02",
        _grant(),
        isolation_root=root,
        writes=[],
        test_command=["python", "-m", "pytest", "tests/test_escape.py", "-q"],
        whitelist=["python -m pytest"],
    )
    assert not outside.exists()