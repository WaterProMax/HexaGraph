"""A1 integration tests: assignment overlay over the real HTTP routes.

Offline only: scripted provider, temporary data dir, no real model calls and
no product safety gate changes.  The CAS source is the task-level revision
(see tests/unit/test_task_assignment.py for the locked declaration).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.bots.registry import BotRegistry
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.projects.membership import MembershipCreate, MembershipService
from app.schemas.bot import BotCreate
from app.schemas.docs import TaskCard, TaskGraph
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


def _bench(tmp_path: Path, policy: ExecutionPolicy | None = None) -> Workbench:
    return Workbench(
        Gateway(load_models(), ScriptedProvider()),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=policy,
    )


def _bot(name: str) -> BotCreate:
    return BotCreate(
        display_name=name,
        role_template="developer",
        provider_ref="dashscope",
        model="qwen-plus",
        slot="coder",
        secret_ref="DASHSCOPE_API_KEY",
    )


def _card(code: str, role: str) -> TaskCard:
    return TaskCard.model_validate(
        {
            "code": code,
            "title": f"Task {code}",
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": f"Desc for {code}",
            "write_set": [f"src/{code}.py"],
            "acceptance": [
                {"cmd": ["python", "-m", "pytest", "-q"], "pass_criteria": "ok", "from_criterion": "F1"}
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": role,
        }
    )


def _client(bench: Workbench) -> AsyncClient:
    app = create_app()
    app.state.workbench = bench
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


@pytest.fixture
async def env(tmp_path: Path):
    bench = _bench(tmp_path)
    project = bench.create_project("assignment-api")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card("T1", "coder"), _card("T2", "tester")]).model_dump()
    bench._materialize_tasks(run)
    for code in ("T1", "T2"):
        run.tasks[code]["state"] = "ready"
    async with bench.db_session() as session:
        leader = await BotRegistry(session).create(_bot("Leader"))
        member = await BotRegistry(session).create(_bot("Member"))
        outsider = await BotRegistry(session).create(_bot("Outsider"))
        await session.commit()
    async with bench.db_session() as session:
        memberships = MembershipService(session, project_exists=lambda pid: pid == project["id"])
        await memberships.add(project["id"], MembershipCreate(bot_id=leader.bot_id, role_in_project="dev", is_leader=True))
        await memberships.add(project["id"], MembershipCreate(bot_id=member.bot_id, role_in_project="dev"))
        await session.commit()
    data = SimpleNamespace(
        bench=bench,
        tmp_path=tmp_path,
        project_id=project["id"],
        run=run,
        leader=leader.bot_id,
        member=member.bot_id,
        outsider=outsider.bot_id,
    )
    yield data
    await bench.close()


def _url(env, code: str = "T1") -> str:
    return f"/api/runs/{env.run.id}/tasks/{code}/assignment"


def _body(env, assignee, revision: int | None = None) -> dict:
    if revision is None:
        revision = int(env.run.tasks["T1"]["revision"])
    return {"assignee_bot_id": assignee, "expected_revision": revision}


async def test_public_tasks_default_assignment_null(env) -> None:
    async with _client(env.bench) as client:
        response = await client.get(f"/api/runs/{env.run.id}/tasks")
    assert response.status_code == 200
    for task in response.json():
        assert task["assignment"] is None


async def test_leader_put_then_read_back_everywhere(env) -> None:
    async with _client(env.bench) as client:
        response = await client.put(
            _url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader}
        )
        assert response.status_code == 200, response.text
        assignment = response.json()["assignment"]
        assert assignment["assignee_bot_id"] == env.member
        assert assignment["assignee_display_name"] == "Member"
        assert assignment["assigned_by_bot_id"] == env.leader
        assert assignment["assigned_at"]
        assert int(assignment["revision"]) == 1

        tasks = (await client.get(f"/api/runs/{env.run.id}/tasks")).json()
        by_code = {task["code"]: task for task in tasks}
        assert by_code["T1"]["assignment"]["assignee_bot_id"] == env.member
        assert by_code["T2"]["assignment"] is None

        monitor = (await client.get(f"/api/runs/{env.run.id}/monitor")).json()
        rows = {row["code"]: row for row in monitor["tasks"]}
        assert rows["T1"]["assignee_bot_id"] == env.member
        assert rows["T1"]["assignee_display_name"] == "Member"
        assert rows["T2"]["assignee_bot_id"] is None
        assert rows["T2"]["assignee_display_name"] is None

        detail = (await client.get(f"/api/tasks/{env.run.id}:T1")).json()
        assert detail["assignment"]["assignee_display_name"] == "Member"


async def test_put_requires_actor_header(env) -> None:
    async with _client(env.bench) as client:
        response = await client.put(_url(env), json=_body(env, env.member))
    assert response.status_code == 400
    assert response.json()["error_category"] == "validation_error"


async def test_put_unknown_actor_bot(env) -> None:
    async with _client(env.bench) as client:
        response = await client.put(
            _url(env), json=_body(env, env.member), headers={"X-Bot-Id": "bot-missing"}
        )
    assert response.status_code == 404
    assert response.json()["error_category"] == "bot_not_found"


async def test_put_non_leader_forbidden(env) -> None:
    async with _client(env.bench) as client:
        for actor in (env.member, env.outsider):
            response = await client.put(
                _url(env), json=_body(env, env.member), headers={"X-Bot-Id": actor}
            )
            assert response.status_code == 403
            assert response.json()["error_category"] == "forbidden"
    assert env.run.tasks["T1"].get("assignment") is None


async def test_put_assignee_not_member(env) -> None:
    async with _client(env.bench) as client:
        response = await client.put(
            _url(env), json=_body(env, env.outsider), headers={"X-Bot-Id": env.leader}
        )
    assert response.status_code == 400
    assert response.json()["error_category"] == "assignee_not_member"


async def test_put_stale_revision_conflict(env) -> None:
    async with _client(env.bench) as client:
        ok = await client.put(_url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader})
        assert ok.status_code == 200
        stale = await client.put(
            _url(env),
            json={"assignee_bot_id": env.leader, "expected_revision": 0},
            headers={"X-Bot-Id": env.leader},
        )
        assert stale.status_code == 409
        assert stale.json()["error_category"] == "revision_conflict"
        tasks = (await client.get(f"/api/runs/{env.run.id}/tasks")).json()
        by_code = {task["code"]: task for task in tasks}
        assert by_code["T1"]["assignment"]["assignee_bot_id"] == env.member


async def test_put_null_clears_and_emits_events(env) -> None:
    async with _client(env.bench) as client:
        await client.put(_url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader})
        cleared = await client.put(_url(env), json=_body(env, None), headers={"X-Bot-Id": env.leader})
        assert cleared.status_code == 200
        assert cleared.json()["assignment"] is None
        events = (await client.get(f"/api/runs/{env.run.id}/events/history")).json()
        kinds = [event["kind"] for event in events]
        assert "task.assigned" in kinds
        assert "task.assignment_cleared" in kinds


async def test_put_missing_run_or_task(env) -> None:
    async with _client(env.bench) as client:
        missing_run = await client.put(
            "/api/runs/run-missing/tasks/T1/assignment",
            json={"assignee_bot_id": env.member, "expected_revision": 1},
            headers={"X-Bot-Id": env.leader},
        )
        assert missing_run.status_code == 404
        assert missing_run.json()["error_category"] == "run_not_found"
        missing_task = await client.put(
            _url(env, "T-404"), json=_body(env, env.member), headers={"X-Bot-Id": env.leader}
        )
        assert missing_task.status_code == 404
        assert missing_task.json()["error_category"] == "task_not_found"


async def test_put_invalid_body(env) -> None:
    async with _client(env.bench) as client:
        missing_revision = await client.put(
            _url(env), json={"assignee_bot_id": env.member}, headers={"X-Bot-Id": env.leader}
        )
        assert missing_revision.status_code == 400
        assert missing_revision.json()["error_category"] == "validation_error"
        bad_type = await client.put(
            _url(env),
            json={"assignee_bot_id": 123, "expected_revision": 1},
            headers={"X-Bot-Id": env.leader},
        )
        assert bad_type.status_code == 400
        assert bad_type.json()["error_category"] == "validation_error"


async def test_put_after_terminate_is_read_only(env) -> None:
    env.bench.set_run_control(env.run, "terminate", confirm=True)
    async with _client(env.bench) as client:
        response = await client.put(
            _url(env),
            json={"assignee_bot_id": env.member, "expected_revision": int(env.run.tasks["T1"]["revision"])},
            headers={"X-Bot-Id": env.leader},
        )
    assert response.status_code == 409
    assert response.json()["error_category"] == "run_read_only"


async def test_role_memory_routes_and_subject_unchanged(env) -> None:
    async with _client(env.bench) as client:
        await client.put(_url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader})
        base = f"/api/runs/{env.run.id}/tasks/T1/role-memory"
        read = await client.get(f"{base}/coder", headers={"X-Bot-Id": env.member})
        assert read.status_code == 200
        write = await client.put(
            f"{base}/coder",
            json={"expected_revision": 0, "manual_text": "优先覆盖空输入"},
            headers={"X-Bot-Id": env.leader},
        )
        assert write.status_code == 200
        # A bot id is never a valid memory role: the subject stays role-scoped.
        bot_scoped = await client.get(f"{base}/{env.member}", headers={"X-Bot-Id": env.member})
        assert bot_scoped.status_code == 422


async def test_public_task_never_leaks_memory_or_step_bodies(env) -> None:
    async with _client(env.bench) as client:
        await client.put(_url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader})
        await client.put(
            f"/api/runs/{env.run.id}/tasks/T1/role-memory/coder",
            json={"expected_revision": 0, "manual_text": "秘密备注"},
            headers={"X-Bot-Id": env.leader},
        )
        tasks = (await client.get(f"/api/runs/{env.run.id}/tasks")).json()
    for task in tasks:
        assert "role_memory" not in task
        attempt = task.get("attempt")
        if isinstance(attempt, dict):
            assert "execution_steps" not in attempt


async def test_assignment_survives_full_restore(env) -> None:
    async with _client(env.bench) as client:
        await client.put(_url(env), json=_body(env, env.member), headers={"X-Bot-Id": env.leader})
    restored_bench = _bench(env.tmp_path)
    try:
        restored_bench.restore_runs()
        assert env.run.id in restored_bench.runs
        async with _client(restored_bench) as client:
            tasks = (await client.get(f"/api/runs/{env.run.id}/tasks")).json()
        by_code = {task["code"]: task for task in tasks}
        assert by_code["T1"]["assignment"]["assignee_bot_id"] == env.member
        assert by_code["T1"]["assignment"]["assignee_display_name"] == "Member"
    finally:
        await restored_bench.close()


async def test_schedule_does_not_require_assignment(tmp_path: Path) -> None:
    bench = _bench(tmp_path, ExecutionPolicy(simulated=True))
    try:
        project = bench.create_project("schedule-without-assignment")
        run = bench.create_run(project["id"], "idea")
        run.artifacts["plan"] = TaskGraph(tasks=[_card("T1", "coder")]).model_dump()
        bench._materialize_tasks(run)
        run.tasks["T1"]["state"] = "ready"
        assert run.tasks["T1"].get("assignment") is None
        async with _client(bench) as client:
            response = await client.post(f"/api/runs/{run.id}/schedule", json={})
        assert response.status_code == 200, response.text
        assert "T1" in response.json()["started"]
    finally:
        await bench.close()