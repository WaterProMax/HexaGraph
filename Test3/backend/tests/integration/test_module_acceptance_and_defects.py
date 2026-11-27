from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import DefectRow, ModuleAcceptanceRow

EVIDENCE = "file://logs/t01.log"


def _card(code: str) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": code,
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": "d",
            "write_set": [f"src/{code.lower()}.py"],
            "outputs": [f"src/{code.lower()}.py"],
            "acceptance": [
                AcceptanceCheck(
                    cmd=["python", "-m", "pytest", f"tests/test_{code.lower()}.py", "-q"],
                    pass_criteria="ok",
                    from_criterion="F1",
                )
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


@pytest.fixture
async def app(tmp_path):
    app = create_app()
    app.state.workbench = Workbench(
        Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path
    )
    await app.state.workbench._ensure_db()
    try:
        yield app
    finally:
        await app.state.workbench.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _run(app) -> str:
    bench = app.state.workbench
    project = bench.create_project("acceptance")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T-01")]).model_dump()
    bench._materialize_tasks(run)
    task = run.tasks["T-01"]
    task["state"] = "done"
    task["evidence"] = [{"kind": "command", "summary": "ok", "path": EVIDENCE}]
    return run.id


def _acceptance_body(**overrides) -> dict:
    body = {
        "module_id": "M1",
        "task_codes": ["T-01"],
        "status": "accepted",
        "evidence_uris": [EVIDENCE],
        "reviewer": "bot-reviewer",
        "comment": "looks good",
    }
    body.update(overrides)
    return body


def _defect_body(**overrides) -> dict:
    body = {
        "task_code": "T-01",
        "module_id": "M1",
        "evidence_uris": [EVIDENCE],
        "detail": "回归输出缺失",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_accepted_module_with_existing_evidence(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "accepted"
    assert body["reviewer"] == "bot-reviewer"
    async with app.state.workbench.db_session() as session:
        rows = (await session.execute(select(ModuleAcceptanceRow))).scalars().all()
    assert [row.acceptance_id for row in rows] == [body["acceptance_id"]]


@pytest.mark.asyncio
async def test_accepted_with_model_self_review_is_rejected(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(model_self_review=True, evidence_uris=[]),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 400, res.text
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_accepted_without_evidence_is_rejected(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(evidence_uris=[]),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_rejected_acceptance_requires_evidence(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(status="rejected", evidence_uris=[]),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_rejected_acceptance_opens_defect_and_fails_task(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(status="rejected", comment="缺回归证据"),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 201, res.text
    assert app.state.workbench.runs[run_id].tasks["T-01"]["state"] == "failed"
    async with app.state.workbench.db_session() as session:
        defects = (await session.execute(select(DefectRow))).scalars().all()
    assert len(defects) == 1
    assert defects[0].payload["status"] == "open"
    assert defects[0].task_code == "T-01"


@pytest.mark.asyncio
async def test_defect_returns_task_to_failed(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/defects",
            json=_defect_body(),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "open"
    assert body["task_code"] == "T-01"
    assert app.state.workbench.runs[run_id].tasks["T-01"]["state"] == "failed"


@pytest.mark.asyncio
async def test_reverification_resolves_defect_without_deleting_history(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        rejected = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(status="rejected", comment="缺回归证据"),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
        assert rejected.status_code == 201, rejected.text
        # Human repair: the task is done again with evidence, then re-verified.
        run = app.state.workbench.runs[run_id]
        run.tasks["T-01"]["state"] = "done"
        run.tasks["T-01"]["evidence"] = [{"kind": "command", "summary": "ok", "path": EVIDENCE}]
        accepted = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(comment="复验通过"),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["run_evidence"]["level"] == "scripted"
    assert accepted.json()["decision"] == "accepted"
    assert accepted.json()["evidence_uris"] == [EVIDENCE]
    async with app.state.workbench.db_session() as session:
        defects = (await session.execute(select(DefectRow))).scalars().all()
    assert len(defects) == 1
    assert defects[0].payload["status"] == "resolved"
    assert defects[0].payload["resolved_by_acceptance_id"] == accepted.json()["acceptance_id"]
    assert defects[0].payload["detail"] == "缺回归证据"


@pytest.mark.asyncio
async def test_unknown_run_is_404(app) -> None:
    async with _client(app) as client:
        accepted = await client.post(
            "/api/runs/no-such-run/module-acceptances",
            json=_acceptance_body(),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
        defect = await client.post(
            "/api/runs/no-such-run/defects",
            json=_defect_body(),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert accepted.status_code == 404
    assert accepted.json()["error_category"] == "run_not_found"
    assert defect.status_code == 404


@pytest.mark.asyncio
async def test_missing_actor_header_is_400(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run_id}/module-acceptances", json=_acceptance_body())
    assert res.status_code == 400
    assert res.json()["error_category"] == "validation_error"


@pytest.mark.asyncio
async def test_reviewer_must_match_actor(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(
            f"/api/runs/{run_id}/module-acceptances",
            json=_acceptance_body(reviewer="someone-else"),
            headers={"X-Bot-Id": "bot-reviewer"},
        )
    assert res.status_code == 403
    assert res.json()["error_category"] == "forbidden"


@pytest.mark.asyncio
async def test_concurrent_defects_keep_both_rows(app) -> None:
    run_id = _run(app)
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post(
                f"/api/runs/{run_id}/defects",
                json=_defect_body(detail="first comment"),
                headers={"X-Bot-Id": "bot-a"},
            ),
            client.post(
                f"/api/runs/{run_id}/defects",
                json=_defect_body(detail="second comment"),
                headers={"X-Bot-Id": "bot-b"},
            ),
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    async with app.state.workbench.db_session() as session:
        defects = (await session.execute(select(DefectRow))).scalars().all()
    details = sorted(row.payload["detail"] for row in defects)
    assert details == ["first comment", "second comment"]


@pytest.mark.asyncio
async def test_legacy_run_acceptance_path_unchanged(app) -> None:
    """P5 does not reroute or relax the legacy whole-run accept endpoint."""
    run_id = _run(app)
    async with _client(app) as client:
        res = await client.post(f"/api/runs/{run_id}/accept")
    # SPEC is absent, so the legacy endpoint keeps its own 409/400 shape.
    assert res.status_code in {400, 409}
    assert "error_category" not in res.json() or res.json()["error_category"] != "granted_acceptance_disabled"