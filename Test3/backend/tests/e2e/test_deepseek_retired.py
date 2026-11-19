"""Retired DeepSeek-only entry: controlled 410s, no network, read-only history.

The old dedicated entry is gone. These tests pin three guarantees:

* ``provider="deepseek"`` never creates a run and never opens an HTTP client;
* historical ``provenance.mode == "deepseek"`` snapshots stay readable verbatim;
* resume/schedule/gate/task paths reject instead of silently using DashScope.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.errors import ConfigError, DeepSeekRetired
from app.llm.gateway import Gateway, build_provider
from app.llm.providers import DashScopeProvider, ScriptedProvider
from app.main import create_app
from app.schemas.design_input import DesignSource
from app.services import runtime as runtime_module
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.design_spec_http_server import create_offline_app

DESIGN_TEXT = "目标：学生查看空闲自习室座位。\n§2 座位查询与更新时间。"
LEGACY_RUN_ID = "legacy-deepseek-run"


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _bench(tmp_path: Path) -> tuple[Workbench, ScriptedProvider]:
    provider = ScriptedProvider([])
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    return bench, provider


def _no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to build an HTTP client is a hard failure (no live calls)."""

    def _fail(*args, **kwargs):
        raise AssertionError("unexpected HTTP client construction / request")

    monkeypatch.setattr(httpx, "AsyncClient", _fail)


def _no_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retired path must reject before loading .env / settings."""

    def _fail(*args, **kwargs):
        raise AssertionError("get_settings() must not be called by the retired path")

    monkeypatch.setattr(runtime_module, "get_settings", _fail)


def _legacy_snapshot(
    tmp_path: Path,
    *,
    run_id: str = LEGACY_RUN_ID,
    include_plan: bool = False,
    gate: bool = False,
    task: bool = False,
) -> Path:
    artifacts: dict = {
        "provenance": {
            "generation": "model",
            "generation_label": "DeepSeek 真实模型生成（deepseek-v4-flash）",
            "execution": "real_tool",
            "execution_label": "真实工具执行（受限写集与命令白名单）",
            "provider": "DeepSeekProvider",
            "mode": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            # Unknown, non-sensitive snapshot fields must survive a restore.
            "legacy_extra": {"kept": True},
        },
        "legacy_artifact": {"keep": "verbatim"},
    }
    tasks: dict = {}
    if include_plan:
        artifacts["plan"] = {"tasks": [{"code": "T-01", "title": "旧计划", "depends_on": [], "sources": []}]}
        tasks["T-01"] = {
            "id": f"{run_id}:T-01",
            "code": "T-01",
            "state": "ready",
            "revision": 1,
            "card": {
                "code": "T-01",
                "title": "旧计划",
                "kind": "impl",
                "module": "M1",
                "sources": [],
                "description": "",
                "inputs": [],
                "write_set": [],
                "outputs": [],
                "acceptance": [],
                "depends_on": [],
                "points": 1,
                "priority": "P1",
                "role": "coder",
            },
            "repair_rounds": 0,
            "signatures": [],
            "evidence": [],
            "paused": False,
            "locked_by": "",
            "tokens_used": 0,
            "prev_output": "",
            "review_issues": [],
        }
    if task:
        tasks.setdefault(
            "T-01",
            {
                "id": f"{run_id}:T-01",
                "code": "T-01",
                "state": "failed",
                "revision": 2,
                "card": {
                    "code": "T-01",
                    "title": "旧任务",
                    "kind": "impl",
                    "module": "M1",
                    "sources": [],
                    "description": "",
                    "inputs": [],
                    "write_set": [],
                    "outputs": [],
                    "acceptance": [],
                    "depends_on": [],
                    "points": 1,
                    "priority": "P1",
                    "role": "coder",
                },
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
                "tokens_used": 0,
                "prev_output": "",
                "review_issues": [],
            },
        )
    snapshot = {
        "id": run_id,
        "project_id": "legacy-project",
        "idea": "历史 DeepSeek 运行",
        "status": "running" if include_plan else "waiting",
        "revision": 3,
        "paused": False,
        "pending_human": gate,
        "tokens_used": 42,
        "engine": {"current": "7" if include_plan else "5"},
        "ids": {},
        "artifacts": artifacts,
        "gates": (
            [{"id": "legacy-gate", "kind": "DESIGN基线确认", "status": "pending", "payload": {}}] if gate else []
        ),
        "tasks": tasks,
        "crs": [],
        "feedback": [],
        "raw_feedback": [],
        "trace": [],
        "limits": {},
        "skip_continue": [],
        # Unknown top-level key written by an older build.
        "legacy_top_level": {"keep": "verbatim"},
    }
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    (folder / "events.jsonl").write_text("", encoding="utf-8")
    return folder


@pytest.mark.asyncio
async def test_create_design_run_with_deepseek_provider_is_410_before_run_or_network(
    tmp_path, monkeypatch
) -> None:
    _no_http(monkeypatch)
    _no_settings(monkeypatch)
    bench, provider = _bench(tmp_path)
    project = bench.create_project("retired")
    app = create_app()
    app.state.workbench = bench

    async with _client(app) as client:
        res = await client.post(
            f"/api/projects/{project['id']}/design-runs",
            json={"text": DESIGN_TEXT, "source": {"kind": "text"}, "provider": "deepseek"},
        )

    assert res.status_code == 410, res.text
    body = res.json()["detail"]
    assert body["category"] == "deepseek_retired"
    assert "已下线" in body["summary"]
    assert "未发起请求" in body["summary"]
    assert not [run for run in bench.runs.values() if run.project_id == project["id"]]
    assert provider.calls == []
    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
async def test_offline_http_server_rejects_deepseek_without_touching_settings(tmp_path, monkeypatch) -> None:
    app = create_offline_app(tmp_path)
    _no_http(monkeypatch)
    _no_settings(monkeypatch)
    async with _client(app) as client:
        project = (await client.post("/api/projects", json={"name": "offline"})).json()
        res = await client.post(
            f"/api/projects/{project['id']}/design-runs",
            json={"text": DESIGN_TEXT, "source": {"kind": "text"}, "provider": "deepseek"},
        )
        assert res.status_code == 410, res.text
        runs = (await client.get("/api/runs")).json()
    assert runs == []


def test_gateway_rejects_unknown_provider_kind_instead_of_falling_back() -> None:
    models = load_models()
    assert isinstance(build_provider("scripted", models), ScriptedProvider)
    assert isinstance(build_provider("dashscope", models), DashScopeProvider)
    with pytest.raises(ConfigError):
        build_provider("deepseek", models)
    with pytest.raises(ConfigError):
        build_provider("", models)


@pytest.mark.asyncio
async def test_legacy_deepseek_snapshot_is_readable_and_provenance_is_not_rewritten(tmp_path, monkeypatch) -> None:
    _no_http(monkeypatch)
    _legacy_snapshot(tmp_path)
    bench, provider = _bench(tmp_path)
    app = create_app()
    app.state.workbench = bench

    async with _client(app) as client:
        listing = (await client.get("/api/runs")).json()
        detail = (await client.get(f"/api/runs/{LEGACY_RUN_ID}")).json()
        arts = (await client.get(f"/api/runs/{LEGACY_RUN_ID}/artifacts")).json()
        events = await client.get(f"/api/runs/{LEGACY_RUN_ID}/events/history")
        tasks = await client.get(f"/api/runs/{LEGACY_RUN_ID}/tasks")

    assert [item["id"] for item in listing] == [LEGACY_RUN_ID]
    assert listing[0]["read_only"] is True
    assert listing[0]["retired_mode"] == "deepseek"
    assert "只读" in listing[0]["retired_message"]
    assert detail["provenance"]["mode"] == "deepseek"
    assert detail["provenance"]["provider"] == "DeepSeekProvider"
    assert detail["provenance"]["model"] == "deepseek-v4-flash"
    assert detail["provenance"]["base_url"] == "https://api.deepseek.com"
    assert arts["provenance"]["mode"] == "deepseek"
    assert arts["provenance"]["legacy_extra"] == {"kept": True}
    assert arts["legacy_artifact"] == {"keep": "verbatim"}
    assert events.status_code == 200
    assert events.json() == []
    assert tasks.status_code == 200
    assert provider.calls == []

    # Restore must preserve unknown fields on disk (including top-level ones).
    snapshot = json.loads((tmp_path / "runs" / LEGACY_RUN_ID / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["legacy_top_level"] == {"keep": "verbatim"}
    assert snapshot["artifacts"]["provenance"]["legacy_extra"] == {"kept": True}
    assert snapshot["artifacts"]["provenance"]["mode"] == "deepseek"


@pytest.mark.asyncio
async def test_legacy_deepseek_run_rejects_resume_schedule_gate_and_retry_without_network(
    tmp_path, monkeypatch
) -> None:
    _no_http(monkeypatch)
    _legacy_snapshot(tmp_path, include_plan=True, gate=True, task=True)
    bench, provider = _bench(tmp_path)
    app = create_app()
    app.state.workbench = bench
    assert bench.runs[LEGACY_RUN_ID].artifacts["provenance"]["mode"] == "deepseek"

    async with _client(app) as client:
        resume = await client.post(f"/api/runs/{LEGACY_RUN_ID}/resume")
        schedule = await client.post(f"/api/runs/{LEGACY_RUN_ID}/schedule")
        gate = await client.post("/api/gates/legacy-gate/resolve", json={"decision": "approve"})
        retry = await client.post(
            "/api/tasks/T-01/retry",
            json={"expected_revision": 2, "reason": "人工重试"},
        )
        pause = await client.post(f"/api/runs/{LEGACY_RUN_ID}/pause")
        terminate = await client.post(f"/api/runs/{LEGACY_RUN_ID}/terminate", json={"confirm": True})

    for res in (resume, schedule, gate, retry):
        assert res.status_code == 410, res.text
        assert res.json()["detail"]["category"] == "deepseek_retired"
        assert "未发起请求" in res.json()["detail"]["summary"]
    assert pause.status_code == 200
    assert terminate.status_code == 200
    assert provider.calls == []
    # The gate is still pending: the rejected call did not advance the run.
    gates = bench.runs[LEGACY_RUN_ID].gates
    assert gates[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_start_loop_skips_retired_run_but_still_schedules_normal_run(tmp_path, monkeypatch) -> None:
    _no_http(monkeypatch)
    _legacy_snapshot(tmp_path, include_plan=True)
    _legacy_snapshot(tmp_path, run_id="normal-run", include_plan=True)
    normal_snapshot = tmp_path / "runs" / "normal-run" / "snapshot.json"
    data = json.loads(normal_snapshot.read_text(encoding="utf-8"))
    data["artifacts"]["provenance"] = {
        "generation": "preset",
        "generation_label": "预置测试输出（scripted）",
        "execution": "simulated",
        "execution_label": "模拟执行（预置工具调用）",
        "provider": "ScriptedProvider",
    }
    normal_snapshot.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bench, provider = _bench(tmp_path)
    scheduled: list[str] = []

    async def _spy(run) -> list[str]:
        scheduled.append(run.id)
        return []

    bench.schedule_once = _spy  # type: ignore[method-assign]
    bench.schedule_interval = 0.01
    bench.start_loop()
    try:
        await asyncio.sleep(0.08)
    finally:
        await bench.stop_loop()

    assert LEGACY_RUN_ID not in scheduled
    assert "normal-run" in scheduled
    assert provider.calls == []


@pytest.mark.asyncio
async def test_legacy_deepseek_services_reject_direct_calls(tmp_path) -> None:
    """Defence in depth: the runtime methods, not only the HTTP layer, reject."""

    _legacy_snapshot(tmp_path, include_plan=True, gate=True, task=True)
    bench, provider = _bench(tmp_path)
    run = bench.runs[LEGACY_RUN_ID]

    with pytest.raises(DeepSeekRetired):
        await bench.create_design_run("p", DESIGN_TEXT, DesignSource(kind="text"), provider="deepseek")
    with pytest.raises(DeepSeekRetired):
        await bench.run_plan(run)
    with pytest.raises(DeepSeekRetired):
        await bench.schedule_once(run)
    with pytest.raises(DeepSeekRetired):
        bench.set_run_control(run, "resume")
    with pytest.raises(DeepSeekRetired):
        bench._gateway_for(run)
    assert provider.calls == []