"""Offline design-spec demo server: schedule mode, sample match, queue limits, labels."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.design_spec_http_server import create_offline_app
from tests.e2e.test_design_input import PLAN

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "design-specs"
SELF_STUDY = EXAMPLES / "self-study-room.md"
CLUB_SIGNUP = EXAMPLES / "club-signup.md"


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_status(client: AsyncClient, run_id: str, timeout: float = 4.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    body: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        arts = (await client.get(f"/api/runs/{run_id}/artifacts")).json()
        status = arts.get("design_input_status")
        if status and status != "importing":
            return arts
        body = arts
        await asyncio.sleep(0.02)
    raise AssertionError(f"import still running: {body.get('design_input_status')}")


async def _import(client: AsyncClient, text: str, *, name: str, title: str = "") -> tuple[str, dict]:
    project = (await client.post("/api/projects", json={"name": "offline-demo"})).json()
    res = await client.post(
        f"/api/projects/{project['id']}/design-runs",
        json={"text": text, "source": {"kind": "file", "name": name}, "title": title},
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    arts = await _wait_status(client, run_id)
    return run_id, arts


@pytest.mark.asyncio
async def test_health_exposes_manual_schedule_mode_when_loop_is_off(tmp_path) -> None:
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )
    async with _client(app) as client:
        health = await client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["schedule_mode"] == "manual"


@pytest.mark.asyncio
async def test_health_exposes_auto_schedule_mode_after_start_loop_even_for_preset(tmp_path) -> None:
    bench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    assert type(bench.gateway.provider).__name__ == "ScriptedProvider"
    app = create_app()
    app.state.workbench = bench
    bench.start_loop()
    try:
        async with _client(app) as client:
            health = await client.get("/api/health")
        assert health.json()["schedule_mode"] == "auto"
        assert health.json()["status"] == "ok"
    finally:
        await bench.stop_loop()
    async with _client(app) as client:
        health = await client.get("/api/health")
    assert health.json()["schedule_mode"] == "manual"


@pytest.mark.asyncio
async def test_offline_demo_server_health_is_manual_not_inferred_from_preset(tmp_path) -> None:
    app = create_offline_app(tmp_path)
    async with _client(app) as client:
        health = await client.get("/api/health")
        assert health.json()["schedule_mode"] == "manual"
        run_id, arts = await _import(
            client, SELF_STUDY.read_text(encoding="utf-8"), name="self-study-room.md", title="自习室座位预约"
        )
        run = (await client.get(f"/api/runs/{run_id}")).json()
    assert arts["provenance"]["generation"] == "preset"
    assert run["provenance"]["generation"] == "preset"
    assert health.json()["schedule_mode"] == "manual"
    assert health.json()["schedule_mode"] != arts["provenance"]["generation"]


@pytest.mark.asyncio
async def test_offline_success_plan_matches_self_study_room_seat_query(tmp_path) -> None:
    sample = SELF_STUDY.read_text(encoding="utf-8")
    assert "查询可预约座位" in sample
    app = create_offline_app(tmp_path)
    async with _client(app) as client:
        run_id, arts = await _import(client, sample, name="self-study-room.md", title="自习室座位预约")
        gate_id = (await client.get(f"/api/runs/{run_id}")).json()["gates"][0]["id"]
        planned = await client.post(f"/api/gates/{gate_id}/resolve", json={"decision": "approve"})
        assert planned.status_code == 200, planned.text
        plan_gate = planned.json()["gate"]["id"]
        executing = await client.post(f"/api/gates/{plan_gate}/resolve", json={"decision": "approve"})
        assert executing.status_code == 200, executing.text
        tasks = (await client.get(f"/api/runs/{run_id}/tasks")).json()
        arts = (await client.get(f"/api/runs/{run_id}/artifacts")).json()
        run = (await client.get(f"/api/runs/{run_id}")).json()

    titles = [task["title"] for task in arts["plan"]["tasks"]]
    assert titles == [item["title"] for item in PLAN["tasks"]]
    assert all("座位" in title for title in titles)
    assert [task["code"] for task in tasks] == ["T-01", "T-02"]
    assert tasks[1]["card"]["depends_on"] == ["T-01"]
    assert "预置测试输出" in arts["provenance"]["generation_label"]
    assert "模拟执行" in arts["provenance"]["execution_label"]
    assert run["provenance"]["generation_label"] == arts["provenance"]["generation_label"]
    assert run["provenance"]["execution_label"] == arts["provenance"]["execution_label"]


@pytest.mark.asyncio
async def test_club_signup_upload_persists_text_but_does_not_claim_seat_plan_from_club_doc(tmp_path) -> None:
    club = CLUB_SIGNUP.read_text(encoding="utf-8")
    assert "社团" in club
    assert "报名" in club
    app = create_offline_app(tmp_path)
    async with _client(app) as client:
        run_id, arts = await _import(client, club, name="club-signup.md", title="社团活动报名")
        run = (await client.get(f"/api/runs/{run_id}")).json()
        assert arts["design_input"]["text"] == club
        assert arts["design_input"]["source"]["name"] == "club-signup.md"
        saved = (tmp_path / "runs" / run_id / "design-input.txt").read_text(encoding="utf-8")
        assert saved == club
        assert arts["provenance"]["generation"] == "preset"
        assert "预置测试输出" in arts["provenance"]["generation_label"]
        planned = await client.post(
            f"/api/gates/{run['gates'][0]['id']}/resolve", json={"decision": "approve"}
        )
        assert planned.status_code == 200, planned.text
        plan_arts = (await client.get(f"/api/runs/{run_id}/artifacts")).json()
        run_view = (await client.get(f"/api/runs/{run_id}")).json()

    titles = [task["title"] for task in plan_arts["plan"]["tasks"]]
    assert titles
    assert all("座位" in title for title in titles)
    assert plan_arts["provenance"]["generation"] == "preset"
    assert run_view["provenance"]["generation"] == "preset"
    assert "社团" not in " ".join(titles)


@pytest.mark.asyncio
async def test_offline_queue_is_one_success_one_missing_then_exhausted(tmp_path) -> None:
    sample = SELF_STUDY.read_text(encoding="utf-8")
    app = create_offline_app(tmp_path)
    async with _client(app) as client:
        success_id, success_arts = await _import(client, sample, name="self-study-room.md")
        assert success_arts["design_input_status"] == "awaiting_confirmation"
        run = (await client.get(f"/api/runs/{success_id}")).json()
        design_gate = run["gates"][0]["id"]
        planned = await client.post(f"/api/gates/{design_gate}/resolve", json={"decision": "approve"})
        plan_gate = planned.json()["gate"]["id"]
        await client.post(f"/api/gates/{plan_gate}/resolve", json={"decision": "approve"})
        for _ in range(4):
            await client.post(f"/api/runs/{success_id}/schedule")
            tasks = (await client.get(f"/api/runs/{success_id}/tasks")).json()
            if tasks and all(task["state"] == "done" for task in tasks):
                break
        tasks = (await client.get(f"/api/runs/{success_id}/tasks")).json()
        assert [task["state"] for task in tasks] == ["done", "done"]

        missing_id, missing_arts = await _import(client, "目标：学生查看空位。", name="missing.md")
        assert missing_arts["design_input_status"] == "needs_input"
        assert missing_arts.get("plan") is None
        assert (await client.get(f"/api/runs/{missing_id}/tasks")).json() == []
        assert "缺少并发冲突处理" in " ".join(missing_arts.get("design_input_missing") or missing_arts.get("missing") or [])

        exhausted_id, exhausted_arts = await _import(client, sample, name="self-study-room.md")
        assert exhausted_arts["design_input_status"] == "failed"
        assert exhausted_arts.get("plan") is None


@pytest.mark.asyncio
async def test_two_fresh_offline_resets_yield_identical_first_imports(tmp_path) -> None:
    sample = SELF_STUDY.read_text(encoding="utf-8")
    first_dir = tmp_path / "demo-a"
    second_dir = tmp_path / "demo-b"
    first_dir.mkdir()
    second_dir.mkdir()
    results = []
    for data_dir in (first_dir, second_dir):
        app = create_offline_app(data_dir)
        async with _client(app) as client:
            run_id, arts = await _import(client, sample, name="self-study-room.md", title="自习室座位预约")
            run = (await client.get(f"/api/runs/{run_id}")).json()
            health = (await client.get("/api/health")).json()
        results.append(
            {
                "status": arts["design_input_status"],
                "feature": arts["spec"]["features"][0]["title"],
                "module": arts["design"]["modules"][0]["name"],
                "generation": arts["provenance"]["generation_label"],
                "execution": arts["provenance"]["execution_label"],
                "schedule_mode": health["schedule_mode"],
                "gate": run["gates"][0]["kind"],
            }
        )
    assert results[0] == results[1]
    assert results[0]["schedule_mode"] == "manual"
    assert "预置测试输出" in results[0]["generation"]
    assert "模拟执行" in results[0]["execution"]


@pytest.mark.asyncio
async def test_offline_queue_helper_documents_success_then_missing(tmp_path) -> None:
    from tests.e2e.design_spec_http_server import build_offline_queue

    queue = build_offline_queue()
    plan = copy.deepcopy(PLAN)
    for task in plan["tasks"]:
        task["acceptance"][0]["cmd"] = ["python", "-m", "pytest", "tests/test_smoke.py", "-q"]
    assert queue[2]["tasks"][0]["title"] == plan["tasks"][0]["title"]
    missing_items = [item for item in queue if isinstance(item, dict) and item.get("missing")]
    assert missing_items
    assert missing_items[0]["missing"] == ["缺少并发冲突处理与可检查的验收条件"]
    assert queue[-1]["missing"] == ["缺少并发冲突处理与可检查的验收条件"]
