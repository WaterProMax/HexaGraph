from __future__ import annotations

import asyncio
import copy

import pytest

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.schemas.docs import ProposalDoc
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.test_design_input import DESIGN, PLAN, SPEC
from tests.integration.test_api_contract import _app, _client


@pytest.mark.asyncio
async def test_plan_edit_rechecks_dependencies_and_respects_baseline(tmp_path) -> None:
    app = _app(tmp_path)
    bench = app.state.workbench
    project = bench.create_project("排期示例")
    run = bench.create_run(project["id"], "座位查询", steward=True)
    run.engine.current = "6"
    run.artifacts.update(spec=copy.deepcopy(SPEC), design=copy.deepcopy(DESIGN), plan=copy.deepcopy(PLAN))
    gate = bench._gate(run, "PLAN基线确认", {"plan": copy.deepcopy(PLAN)})["gate"]
    url = f"/api/runs/{run.id}/plan"

    async with _client(app) as client:
        initial = (await client.get(f"{url}/preview")).json()
        assert initial["span"] == 3
        assert initial["critical"] == ["T-01", "T-02"]
        edit = {"code": "T-01", "title": "完成查询接口", "points": 5, "depends_on": [], "expected_revision": run.revision}
        cyclic = await client.patch(url, json={**edit, "depends_on": ["T-02"]})
        assert cyclic.status_code == 400 and "有环" in cyclic.json()["detail"]
        assert (await client.get(f"{url}/preview")).json() == initial
        saved = await client.patch(url, json=edit)
        assert saved.status_code == 200, saved.text
        assert (await client.get(f"{url}/preview")).json()["span"] == 6
        assert (await client.patch(url, json=edit)).status_code == 409
        revision = saved.json()["revision"]
        approval = await client.post(f"/api/gates/{gate['id']}/resolve", json={"decision": "approve", "expected_revision": revision})
        assert approval.status_code == 200, approval.text
        assert run.tasks["T-01"]["card"]["title"] == edit["title"]
        assert (await client.patch(url, json={**edit, "expected_revision": run.revision})).status_code == 400


@pytest.mark.asyncio
async def test_proposal_race_gathers_independent_drafts_and_fuses_selected_results(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path)
    bench = app.state.workbench
    project = bench.create_project("方案比选")
    run = bench.create_run(project["id"], "座位查询", steward=True, provider="deepseek")
    run.engine.current = "2"
    run.artifacts.update(idea_card={"raw": run.idea}, issues=[])
    focuses: set[str] = set()
    both_started = asyncio.Event()
    reviewed: list[str] = []

    async def write(run, focus="", *, candidates=None):
        if candidates:
            assert set(candidates) == {"A", "B"}
            return ProposalDoc(elevator="已融合两份方案"), []
        focuses.add(focus)
        if len(focuses) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return ProposalDoc(elevator=focus), []

    async def review(run):
        reviewed.append(run.artifacts["proposal"]["elevator"])
        return bench._gate(run, "评审确认", {"pass": True})

    monkeypatch.setattr(bench, "_write_proposal", write)
    monkeypatch.setattr(bench, "run_review", review)
    result = await bench.run_proposal(run)
    gate = result["gate"]
    assert gate["kind"] == "方案比选"
    assert len(gate["payload"]["candidates"]) == 2
    assert reviewed == []
    async with _client(app) as client:
        url = f"/api/gates/{gate['id']}/resolve"
        invalid = await client.post(url, json={"decision": "approve", "payload": {"candidate": "C"}})
        assert invalid.status_code == 400 and gate["status"] == "pending"
        resolved = await client.post(url, json={"decision": "approve", "payload": {"candidate": "fusion"}})
    assert resolved.status_code == 200, resolved.text
    assert reviewed == ["已融合两份方案"]
    assert run.engine.current == "3"


@pytest.mark.asyncio
async def test_reviewed_experience_survives_restart_and_stays_project_scoped(tmp_path) -> None:
    app = _app(tmp_path)
    bench = app.state.workbench
    project = bench.create_project("座位查询")
    other = bench.create_project("另一项目")
    run = bench.create_run(project["id"], "做一个座位查询应用", steward=True)
    async with _client(app) as client:
        result = await client.post(f"/api/runs/{run.id}/experiences", json={"title": "管理空状态", "lesson": "验证空列表时的提示。"})
        item = result.json()
        assert item["status"] == "candidate"
        route = f"/api/runs/{run.id}/experiences/{item['id']}"
        assert (await client.post(route, json={"decision": "publish"})).json()["status"] == "published"
        assert (await client.post(route, json={"decision": "reject"})).status_code == 400
    app.state.workbench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    async with _client(app) as client:
        experiences = (await client.get(f"/api/projects/{project['id']}/experiences")).json()
        assert len(experiences) == 1 and experiences[0]["status"] == "published"
        assert (await client.get(f"/api/projects/{other['id']}/experiences")).json() == []
