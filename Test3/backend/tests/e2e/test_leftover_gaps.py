from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.errors import ValidationFailed
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.common import AcceptanceCheck
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.workspace.gitops import commit, create_worktree, init_repo_sync
from tests.e2e.test_must_fixes import _bench, _card, _ready_run


@pytest.mark.asyncio
async def test_merge_conflict_spawns_resolve_task(tmp_path: Path) -> None:
    card = _card()
    bench, _ = _bench(
        tmp_path,
        [
            {
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "tests/test_feature.py",
                            "content": "def test_feature():\n    assert True\n",
                        },
                    }
                ]
            },
            {"done": True, "summary": "ok", "files": ["tests/test_feature.py"]},
            {"verdict": "pass", "issues": []},
        ],
    )
    run = _ready_run(bench, card)
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n", "tests/test_feature.py": "base\n"})
    wt = bench.data_dir / "runs" / run.id / "wt" / "T-01"
    create_worktree(repo, wt, "task/T-01")
    (repo / "tests/test_feature.py").write_text("main side\n", encoding="utf-8")
    commit(repo, "main change")
    result = await bench.execute_task(run, "T-01")
    conflict = [task for task in run.tasks.values() if task.get("conflict_resolve")]
    assert conflict, result
    assert run.tasks["T-01"]["state"] == "blocked"
    spawned = conflict[0]
    assert spawned["state"] == "ready"
    assert spawned["card"]["priority"] == "P0"
    assert "tests/test_feature.py" in spawned["card"]["write_set"]
    assert result["kind"] == "合并冲突"


@pytest.mark.asyncio
async def test_accept_pass_exports_release_pack(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    run.tasks["T-01"]["state"] = "done"
    run.artifacts["design"] = {"modules": []}
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"tests/test_feature.py": "def test_feature():\n    assert True\n"})
    result = await bench.accept(run)
    assert result["gate"]["payload"]["pass"] is True
    run.engine.current = "8"
    done = await bench.resolve_gate(run, result["gate"]["id"], "approve", {})
    assert done["status"] == "done"
    assert run.artifacts.get("build_tag") == "build-1.0"
    release = Path(run.artifacts["release_dir"])
    for name in ("SPEC.json", "DESIGN.json", "PLAN.json", "acceptance.json", "trace.json"):
        assert (release / name).exists()
    assert (release / "code" / "tests" / "test_feature.py").exists()
    snapshot = json.loads((bench.data_dir / "runs" / run.id / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "done"
    assert snapshot["artifacts"]["release_dir"] == str(release)
    snapshot["status"] = "waiting"
    snapshot["artifacts"].pop("release_dir")
    (bench.data_dir / "runs" / run.id / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    restored, _ = _bench(tmp_path)
    assert restored.runs[run.id].status == "done"
    assert restored.runs[run.id].artifacts["release_dir"] == str(release)


@pytest.mark.asyncio
async def test_accept_defect_crs_stop_after_two_cycles(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(
        bench,
        _card(acceptance=[AcceptanceCheck(cmd=["python", "-c", "print(1)"], pass_criteria="ok", from_criterion="F1")]),
    )
    run.tasks["T-01"]["state"] = "done"
    first = await bench.accept(run)
    assert first["gate"]["payload"]["pass"] is False
    assert len(run.crs) == 1
    second = await bench.accept(run)
    assert second["gate"]["payload"]["pass"] is False
    assert len(run.crs) == 2
    await bench.accept(run)
    assert len(run.crs) == 2
    assert run.artifacts["accept_fix_cycles"] == 2


@pytest.mark.asyncio
async def test_schedule_loop_ticks_active_runs(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    called: list[str] = []

    async def fake(target) -> list[str]:
        called.append(target.id)
        return []

    bench.schedule_once = fake  # type: ignore[method-assign]
    bench.schedule_interval = 0.05
    bench.start_loop()
    await asyncio.sleep(0.16)
    await bench.stop_loop()
    assert run.id in called


@pytest.mark.asyncio
async def test_takeover_locks_and_submit_merges(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path, [{"verdict": "pass", "issues": []}])
    run = _ready_run(bench, _card())
    locked = await bench.control_task(run, "T-01", "takeover", run.tasks["T-01"]["revision"], "我来改")
    assert locked["locked_by"]
    assert Path(locked["takeover_workspace"]).exists()
    refused = await bench.execute_task(run, "T-01")
    assert refused["kind"] == "locked"
    wt = Path(run.tasks["T-01"]["takeover_workspace"])
    (wt / "tests").mkdir(parents=True, exist_ok=True)
    (wt / "tests/test_feature.py").write_text("def test_feature():\n    assert True\n", encoding="utf-8")
    await bench.control_task(run, "T-01", "submit-takeover", run.tasks["T-01"]["revision"], "提交接管")
    assert run.tasks["T-01"]["state"] == "done"


@pytest.mark.asyncio
async def test_terminate_requires_confirm(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    with pytest.raises(ValidationFailed):
        bench.set_run_control(run, "terminate")
    bench.set_run_control(run, "terminate", confirm=True)
    assert run.status == "terminated"
    assert run.tasks["T-01"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_terminate_http_requires_confirm(tmp_path: Path) -> None:
    app = create_app()
    bench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    app.state.workbench = bench
    project = bench.create_project("term")
    run = bench.create_run(project["id"], "idea")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post(f"/api/runs/{run.id}/terminate", json={})
        assert denied.status_code == 400
        ok = await client.post(f"/api/runs/{run.id}/terminate", json={"confirm": True})
        assert ok.status_code == 200
        assert ok.json()["status"] == "terminated"


@pytest.mark.asyncio
async def test_embed_failure_uses_fast_cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bench, provider = _bench(tmp_path, [{"groups": [[0, 1], [2]]}])
    project = bench.create_project("fb")
    run = bench.create_run(project["id"], "idea")

    async def boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(bench.gateway, "embed", boom)
    rows = [
        {"author": "a", "text": "座位灰了"},
        {"author": "b", "text": "灰色太多"},
        {"author": "c", "text": "希望预测明天"},
    ]
    await bench.import_feedback(run, rows, "test-key")
    assert any(call["slot"] == "fast" for call in provider.calls)
    assert len(run.feedback) == 2
    assert not any("% 17" in str(call) for call in provider.calls)
