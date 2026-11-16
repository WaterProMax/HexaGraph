"""Design-spec import lifecycle: ASAP return, 409, timeout, cancel, restore."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.design_input import DesignSource
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.test_design_input import _intake
from tests.e2e.test_must_fixes import _bench


class HoldProvider:
    """Scripted provider that blocks until `hold` is set, simulating a slow model call."""

    def __init__(self, hold: asyncio.Event, queue: list | None = None) -> None:
        self.hold = hold
        self.inner = ScriptedProvider(queue or [])
        self.calls = self.inner.calls
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()

    async def complete(self, *args, **kwargs):
        self.entered.set()
        await self.hold.wait()
        result = await self.inner.complete(*args, **kwargs)
        self.finished.set()
        return result

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.embed(texts)


def _hold_bench(tmp_path, queue: list | None = None, *, import_timeout_s: float = 600.0) -> tuple[Workbench, HoldProvider, asyncio.Event]:
    hold = asyncio.Event()
    provider = HoldProvider(hold, queue)
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    bench.import_timeout_s = import_timeout_s
    return bench, provider, hold


async def _wait_not_importing(bench: Workbench, run_id: str, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = bench.runs[run_id]
        status = str(run.artifacts.get("design_input_status") or "")
        if status and status != "importing":
            return status
        task = getattr(bench, "_import_tasks", {}).get(run_id)
        if task and task.done():
            return str(run.artifacts.get("design_input_status") or "")
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still importing")


@pytest.mark.asyncio
async def test_design_import_http_returns_importing_asap_then_completes(tmp_path) -> None:
    bench, provider, hold = _hold_bench(tmp_path, _intake())
    app = create_app()
    app.state.workbench = bench
    text = "目标：学生查看空闲座位。\n§2 座位查询。"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "p"})).json()
        started = time.monotonic()
        res = await asyncio.wait_for(
            client.post(
                f"/api/projects/{project['id']}/design-runs",
                json={"text": text, "source": {"kind": "text"}, "title": "自习室"},
            ),
            timeout=1.0,
        )
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "importing"
        assert body["run_id"]
        run_id = body["run_id"]
        snap = json.loads((tmp_path / "runs" / run_id / "snapshot.json").read_text(encoding="utf-8"))
        assert snap["artifacts"]["design_input_status"] == "importing"
        assert snap["artifacts"].get("design_input_started_at")
        assert snap["artifacts"].get("design_input_deadline_at")

        arts = (await client.get(f"/api/runs/{run_id}/artifacts")).json()
        assert arts["design_input_status"] == "importing"

        hold.set()
        status = await _wait_not_importing(bench, run_id)
        assert status == "awaiting_confirmation"
        arts = (await client.get(f"/api/runs/{run_id}/artifacts")).json()
        assert arts["design_input_status"] == "awaiting_confirmation"
        assert arts["spec"]["features"][0]["code"] == "F1"
        run = (await client.get(f"/api/runs/{run_id}")).json()
        assert any(g["kind"] == "DESIGN基线确认" for g in run["gates"])


@pytest.mark.asyncio
async def test_design_import_duplicate_same_project_returns_409(tmp_path) -> None:
    bench, _provider, hold = _hold_bench(tmp_path, _intake())
    app = create_app()
    app.state.workbench = bench
    text = "目标：学生查看空位。"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "p"})).json()
        first = await asyncio.wait_for(
            client.post(
                f"/api/projects/{project['id']}/design-runs",
                json={"text": text, "source": {}},
            ),
            timeout=1.0,
        )
        assert first.status_code == 200
        first_id = first.json()["run_id"]
        assert first.json()["status"] == "importing"

        second = await client.post(
            f"/api/projects/{project['id']}/design-runs",
            json={"text": text + " 再来一次。", "source": {}},
        )
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["run_id"] == first_id
        assert detail.get("category")
        assert detail.get("summary")
        blob = json.dumps(detail, ensure_ascii=False).lower()
        assert "sk-" not in blob
        assert "authorization" not in blob
        assert "api_key" not in blob
        assert "dashscope" not in blob
        assert len(bench.runs) == 1
        hold.set()
        await _wait_not_importing(bench, first_id)


@pytest.mark.asyncio
async def test_design_import_short_timeout_fails_without_gate_and_ignores_late_result(tmp_path) -> None:
    bench, provider, hold = _hold_bench(tmp_path, _intake(), import_timeout_s=0.08)
    project = bench.create_project("p")
    result = await asyncio.wait_for(
        bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource()),
        timeout=1.0,
    )
    assert result["status"] == "importing"
    run = bench.runs[result["run_id"]]
    status = await _wait_not_importing(bench, run.id, timeout=2.0)
    assert status in {"failed", "timeout"}
    assert run.gates == []
    assert "spec" not in run.artifacts
    assert "design" not in run.artifacts
    errors = " ".join(run.artifacts.get("design_input_errors") or [])
    message = str(run.artifacts.get("design_input_message") or result.get("message") or "")
    assert "超时" in errors or "超时" in message or status == "timeout"

    hold.set()
    try:
        await asyncio.wait_for(provider.finished.wait(), timeout=1.0)
    except TimeoutError:
        pass
    await asyncio.sleep(0.05)
    assert run.artifacts.get("design_input_status") in {"failed", "timeout"}
    assert run.gates == []
    assert "spec" not in run.artifacts
    assert run.artifacts.get("design_input_status") != "awaiting_confirmation"


@pytest.mark.asyncio
async def test_terminate_cancels_import_and_ignores_late_success(tmp_path) -> None:
    bench, provider, hold = _hold_bench(tmp_path, _intake())
    project = bench.create_project("p")
    result = await asyncio.wait_for(
        bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource()),
        timeout=1.0,
    )
    run = bench.runs[result["run_id"]]
    assert result["status"] == "importing"
    await provider.entered.wait()
    bench.set_run_control(run, "terminate", confirm=True)
    assert run.status == "terminated"
    assert run.artifacts.get("design_input_status") != "importing"
    note = " ".join(
        [str(run.artifacts.get("design_input_message") or ""), *(run.artifacts.get("design_input_errors") or [])]
    )
    events = " ".join(json.dumps(e, ensure_ascii=False) for e in run.events)
    assert "计费" in note or "计费" in events

    hold.set()
    try:
        await asyncio.wait_for(provider.finished.wait(), timeout=0.5)
    except TimeoutError:
        pass
    await asyncio.sleep(0.05)
    assert run.status == "terminated"
    assert run.artifacts.get("design_input_status") != "awaiting_confirmation"
    assert run.gates == []
    assert "spec" not in run.artifacts


@pytest.mark.asyncio
async def test_restore_runs_marks_interrupted_importing_terminal(tmp_path) -> None:
    bench, _ = _bench(tmp_path)
    project = bench.create_project("p")
    from app.services.runtime import RunState

    run = RunState(id="run-interrupted", project_id=project["id"], idea="设计规格导入")
    run.artifacts["design_input"] = {"text": "目标：学生查看空位。", "sha256": "abc", "source": {"kind": "text"}}
    run.artifacts["design_input_status"] = "importing"
    run.artifacts["design_input_step"] = "spec"
    bench.runs[run.id] = run
    bench._persist_snapshot(run)

    restored_bench, _ = _bench(tmp_path)
    restored = restored_bench.runs[run.id]
    assert restored.artifacts.get("design_input_status") != "importing"
    assert restored.artifacts.get("design_input_status") in {"failed", "interrupted", "timeout"}
    # resubmit is allowed: no active importing run
    active = [
        r
        for r in restored_bench.runs.values()
        if r.project_id == project["id"] and r.artifacts.get("design_input_status") == "importing"
    ]
    assert active == []


@pytest.mark.asyncio
async def test_commit_exception_marks_failed_not_importing(tmp_path, monkeypatch) -> None:
    bench, _provider, hold = _hold_bench(tmp_path, _intake())

    def boom(self, *args, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("commit exploded sk-secret /etc/passwd")

    monkeypatch.setattr(type(bench), "_commit_design_import", boom)
    project = bench.create_project("p")
    result = await asyncio.wait_for(
        bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource()),
        timeout=1.0,
    )
    assert result["status"] == "importing"
    hold.set()
    status = await _wait_not_importing(bench, result["run_id"], timeout=2.0)
    assert status == "failed"
    run = bench.runs[result["run_id"]]
    blob = " ".join(
        [
            str(run.artifacts.get("design_input_message") or ""),
            *(run.artifacts.get("design_input_errors") or []),
        ]
    )
    assert "设计规格整理失败" in blob
    assert "sk-secret" not in blob
    assert "commit exploded" not in blob
    assert "/etc/passwd" not in blob
    assert run.artifacts.get("design_input_status") != "importing"
    assert run.gates == []
    task = getattr(bench, "_import_tasks", {}).get(result["run_id"])
    assert task is None or task.done()
