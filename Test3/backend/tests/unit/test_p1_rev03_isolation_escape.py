"""P1-REV-03: a whitelisted test process and the evidence writer must stay inside.

Every escape target lives under ``tmp_path``; nothing here touches user data.
The evidence test replaces only the container boundary (preflight + run) and
keeps the real filesystem writer, so the write phase is actually exercised even
when Docker is unavailable.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.execution.evidence import cleanup_evidence_dir
from app.execution.isolated import execute_task_granted
from app.execution.isolation import IsolationPreflight, preflight_isolation
from app.schemas.execution_grant import ExecutionGrant


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


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.mark.asyncio
async def test_evidence_symlink_cannot_redirect_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside-evidence"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("outside", encoding="utf-8")
    os.chmod(sentinel, 0o640)
    before = (sentinel.read_text(encoding="utf-8"), _mode(sentinel))
    # The old predictable location is now a symlink pointing outside.  The
    # worker must neither use it nor follow it.
    (tmp_path / "wt-evidence").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(
        "app.execution.isolated.preflight_isolation",
        lambda: IsolationPreflight(available=True, backend="docker", reason="", details={"image": "test-image"}),
    )

    async def fake_run(argv, *, cwd, timeout, env_allow=None, output_limit=None):
        return {
            "exit_code": 0,
            "output": "evidence-body\n",
            "timeout": False,
            "truncated": False,
            "backend": "docker",
            "image": "test-image",
        }

    monkeypatch.setattr("app.execution.isolated.run_isolated", fake_run)

    result = await execute_task_granted(
        "run-1",
        "T-01",
        _grant(["python -c"]),
        isolation_root=root,
        writes=[],
        test_command=["python", "-c", "print('ok')"],
        tool_refs=["python -c"],
        whitelist=["python -c"],
    )
    log_path = Path(result.log_path)
    evidence_path = Path(result.evidence_path)
    try:
        assert log_path.is_file() and evidence_path.is_file()
        assert log_path.parent == evidence_path.parent
        assert log_path.parent != tmp_path / "wt-evidence"
        assert _mode(log_path.parent) == 0o700
        assert _mode(log_path) == 0o600
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert payload["commands"][0]["output"] == "evidence-body\n"
        assert list(outside.iterdir()) == [sentinel]
        assert (sentinel.read_text(encoding="utf-8"), _mode(sentinel)) == before
    finally:
        cleanup_evidence_dir(log_path.parent)


@pytest.mark.asyncio
async def test_whitelisted_pytest_cannot_write_absolute_outside_path(tmp_path: Path) -> None:
    preflight = preflight_isolation()
    if not preflight.available:
        pytest.skip(f"requires isolation backend: {preflight.reason}")
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
        "T-01",
        _grant(["python -m pytest"]),
        isolation_root=root,
        writes=[],
        test_command=["python", "-m", "pytest", "tests/test_escape.py", "-q"],
        whitelist=["python -m pytest"],
        tool_refs=["python -m pytest"],
    )
    assert not outside.exists()
