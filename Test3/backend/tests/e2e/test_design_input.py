from __future__ import annotations

import copy

import pytest
from httpx import ASGITransport, AsyncClient

from app.errors import ValidationFailed
from app.main import create_app
from app.schemas.design_input import DesignSource, DesignRunCreate
from tests.e2e.test_must_fixes import _bench

SPEC = {
    "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
    "users": [{"name": "学生"}],
    "scenarios": [{"code": "S1", "title": "期末周找空位"}],
    "features": [
        {
            "code": "F1",
            "kind": "功能",
            "title": "查看空闲座位",
            "story": "学生查看座位",
            "scenario": "S1",
            "priority": "P0",
            "impact": "减少找座位时间",
            "acceptance": ["显示剩余座位数与开放时段"],
            "manual": [False],
            "sources": ["§2 座位查询"],
            "out_of_scope": False,
        }
    ],
    "out_of_scope": [],
    "nonfunc": [],
    "open_questions": [],
    "review_followup": [],
}

DESIGN = {
    "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
    "modules": [
        {
            "code": "M1",
            "name": "座位查询",
            "responsibility": "返回空闲座位",
            "sources": ["F1"],
            "provides": ["C1"],
            "depends_on": [],
            "data": [],
        },
        {
            "code": "M2",
            "name": "学生端页面",
            "responsibility": "展示座位",
            "sources": ["F1"],
            "provides": [],
            "depends_on": ["M1"],
            "data": [],
        },
    ],
    "interfaces": [
        {"code": "C1", "provider": "M1", "consumers": ["M2"], "inputs": [], "outputs": [], "errors": []}
    ],
    "data": [],
    "decisions": [],
    "contingencies": [],
    "appendix": "",
}

PLAN = {
    "tasks": [
        {
            "code": "T-01",
            "title": "实现座位查询",
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "实现座位查询",
            "inputs": [],
            "write_set": ["src/seats.py"],
            "outputs": ["src/seats.py"],
            "acceptance": [{"cmd": ["python", "-c", "print(1)"], "pass_criteria": "ok", "from_criterion": "F1"}],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
        },
        {
            "code": "T-02",
            "title": "座位查询测试",
            "kind": "test",
            "module": "M1",
            "sources": ["F1"],
            "description": "写测试",
            "inputs": [],
            "write_set": ["tests/test_seats.py"],
            "outputs": ["tests/test_seats.py"],
            "acceptance": [{"cmd": ["python", "-c", "print(2)"], "pass_criteria": "ok", "from_criterion": "F1"}],
            "depends_on": ["T-01"],
            "points": 1,
            "priority": "P0",
            "role": "coder",
        },
    ],
    "notes": "",
    "capacity": 40,
}


def _intake(missing: list[str] | None = None) -> list[dict]:
    return [
        {"spec": copy.deepcopy(SPEC), "missing": missing or [], "notes": "ok"},
        {"design": copy.deepcopy(DESIGN), "missing": missing or [], "notes": "ok"},
    ]


@pytest.mark.asyncio
async def test_design_input_rejects_empty_and_oversize(tmp_path) -> None:
    bench, _ = _bench(tmp_path)
    project = bench.create_project("p")
    with pytest.raises(ValidationFailed):
        await bench.create_design_run(project["id"], "  \n ", DesignSource(kind="text"))
    with pytest.raises(ValidationFailed):
        await bench.create_design_run(project["id"], "x" * (100 * 1024 + 1), DesignSource(kind="text"))


@pytest.mark.asyncio
async def test_design_input_creates_confirmable_docs_without_tasks(tmp_path) -> None:
    text = "# 自习室预约\n目标：学生查看空闲座位。\n§2 座位查询：显示剩余座位与开放时段。"
    bench, _ = _bench(tmp_path, _intake())
    project = bench.create_project("p")
    result = await bench.create_design_run(
        project["id"], text, DesignSource(kind="file", name="self-study.md"), title="自习室预约"
    )
    assert result["status"] == "awaiting_confirmation"
    assert result["gate"]["kind"] == "DESIGN基线确认"
    run = bench.runs[result["run_id"]]
    assert run.engine.current == "5"
    assert run.artifacts["design_input_status"] == "awaiting_confirmation"
    assert run.engine.history == [{"from": "4", "event": "spec_confirmed", "to": "5"}]
    assert run.artifacts["spec"]["features"][0]["code"] == "F1"
    assert run.artifacts["design"]["modules"][0]["code"] == "M1"
    assert run.tasks == {}
    assert run.artifacts["provenance"]["generation"] == "preset"
    raw = (bench.data_dir / "runs" / run.id / "design-input.txt").read_text(encoding="utf-8")
    assert raw == text
    assert run.artifacts["design_input"]["text"] == text
    assert run.artifacts["design_input"]["sha256"]


@pytest.mark.asyncio
async def test_design_input_missing_stops_before_planning(tmp_path) -> None:
    bench, _ = _bench(tmp_path, _intake(["未给出并发上限"]))
    project = bench.create_project("p")
    result = await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    assert result["status"] == "needs_input"
    assert result["missing"] == ["未给出并发上限"]
    run = bench.runs[result["run_id"]]
    assert run.gates == []
    assert run.tasks == {}
    assert run.status == "stopped"
    assert run.artifacts["design_input_status"] == "needs_input"
    assert run.engine.history == []
    restored = bench._deserialize_run(bench._serialize_run(run))
    assert restored.artifacts["design_input_status"] == "needs_input"
    assert restored.engine.history == []
    assert restored.gates == []


@pytest.mark.asyncio
async def test_design_input_needs_split_does_not_confirm_spec_or_design(tmp_path) -> None:
    bench, provider = _bench(tmp_path, _intake())
    project = bench.create_project("p")
    result = await bench.create_design_run(project["id"], "目标：" + "长" * 24_000, DesignSource())
    assert result["status"] == "needs_split"
    run = bench.runs[result["run_id"]]
    assert run.artifacts["design_input_status"] == "needs_split"
    assert run.engine.history == []
    assert run.gates == []
    assert run.tasks == {}
    assert provider.calls == []


@pytest.mark.asyncio
async def test_design_input_invalid_model_output_leaves_no_confirmed_artifacts(tmp_path) -> None:
    bench, _ = _bench(tmp_path, [{"spec": {"chapters": []}}])
    project = bench.create_project("p")
    result = await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    assert result["status"] == "failed"
    run = bench.runs[result["run_id"]]
    assert run.gates == []
    assert run.artifacts["design_input_status"] == "failed"
    assert run.engine.history == []
    assert "spec" not in run.artifacts
    assert "design" not in run.artifacts
    assert "baseline_DESIGN" not in run.artifacts


@pytest.mark.asyncio
async def test_design_input_api_returns_structured_preview(tmp_path) -> None:
    text = "目标：学生查看空闲座位。\n§2 座位查询。"
    bench, _ = _bench(tmp_path, _intake())
    app = create_app()
    app.state.workbench = bench
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "p"})).json()
        res = await client.post(
            f"/api/projects/{project['id']}/design-runs",
            json={"text": text, "source": {"kind": "file", "name": "spec.md"}, "title": "自习室"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "awaiting_confirmation"
        assert body["spec"]["features"][0]["code"] == "F1"
        assert body["gate"]["kind"] == "DESIGN基线确认"

        empty = await client.post(
            f"/api/projects/{project['id']}/design-runs", json={"text": "", "source": {}}
        )
        assert empty.status_code == 400
        too_big = await client.post(
            f"/api/projects/{project['id']}/design-runs", json={"text": "x" * (100 * 1024 + 1), "source": {}}
        )
        assert too_big.status_code == 400


@pytest.mark.asyncio
async def test_design_gate_confirm_is_idempotent_and_reaches_plan(tmp_path) -> None:
    bench, _ = _bench(tmp_path, _intake() + [copy.deepcopy(PLAN)])
    project = bench.create_project("p")
    created = await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    run = bench.runs[created["run_id"]]
    gate_id = created["gate"]["id"]

    planned = await bench.resolve_gate(run, gate_id, "approve", {})
    assert planned["gate"]["kind"] == "PLAN基线确认"
    assert run.artifacts["design_input_status"] == "design_confirmed"
    assert run.tasks == {}
    with pytest.raises(ValidationFailed):
        await bench.resolve_gate(run, gate_id, "approve", {})

    plan_gate = planned["gate"]["id"]
    executing = await bench.resolve_gate(run, plan_gate, "approve", {})
    assert executing["status"] == "executing"
    assert run.artifacts["design_input_status"] == "plan_confirmed"
    assert set(run.tasks) == {"T-01", "T-02"}
    assert run.tasks["T-02"]["state"] == "pending"
    with pytest.raises(ValidationFailed):
        await bench.resolve_gate(run, plan_gate, "approve", {})
    assert set(run.tasks) == {"T-01", "T-02"}


@pytest.mark.asyncio
async def test_design_reject_on_imported_run_does_not_rebuild_design(tmp_path) -> None:
    bench, _ = _bench(tmp_path, _intake())
    project = bench.create_project("p")
    created = await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    run = bench.runs[created["run_id"]]
    result = await bench.resolve_gate(run, created["gate"]["id"], "reject", {"reason": "规则写错"})
    assert result["status"] == "rejected"
    assert run.status == "stopped"
    assert run.gates[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_design_run_request_model_defaults(tmp_path) -> None:
    body = DesignRunCreate(text="x")
    assert body.source.kind == "text"
    assert len(body.text) == 1
