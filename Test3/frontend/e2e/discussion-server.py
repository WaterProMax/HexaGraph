"""Dedicated offline server for the discussion E2E cases; never inherit credentials or data.

Besides the original scripted/simulated app setup this test-only script installs an
async gate that can hold a scripted model call open until the Playwright test
releases it.  The scripted fixture answers instantly, so without a gate the UI can
never press pause before a decision package exists.  The gate lives only in this
E2E server (no product code): it is open by default so the existing
``discussion-flow.pw.ts`` case is unaffected, it never blocks the event loop, and
it releases itself after a safety timeout.

It also installs ``POST /api/e2e/seed-workstation-run`` (test-only): the seed
predates the fix for the ``POST /discussion-sessions/{id}/plan`` checkpoint
regression (planning calls now run with ``checkpoint=False`` after approval) and
is kept so the role-memory specs can exercise the workstation without driving a
full discussion; the workstation page and task role-memory API are the real ones.
"""
import asyncio
import os
import tempfile
from pathlib import Path

os.environ['TEST3_LLM_PROVIDER'] = 'scripted'
os.environ['TEST3_SCRIPTED_FIXTURE'] = 'discussion-e2e'
os.environ['DASHSCOPE_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''

# Operations the E2E tests may hold: proposal, review, synthesis, plan, plan_rewrite.
DEFAULT_GATE_TIMEOUT_SECONDS = 60.0
MAX_GATE_TIMEOUT_SECONDS = 600.0


class E2EDiscussionGate:
    """Loopback-only model-call gate used by the deterministic E2E cases.

    ``holds`` is a set of ``discussion_operation`` values; while a hold is active
    and the gate is not released, a matching scripted call waits asynchronously
    (the HTTP routes keep running) until released or the safety timeout expires.
    """

    def __init__(self) -> None:
        self.released = True
        self.holds: set[str] = set()
        self.blocked: list[str] = []
        self.timeout_seconds = DEFAULT_GATE_TIMEOUT_SECONDS

    def snapshot(self) -> dict:
        return {
            "installed": True,
            "released": self.released,
            "holds": sorted(self.holds),
            "blocked_operations": list(self.blocked),
            "timeout_seconds": self.timeout_seconds,
        }

    def configure(self, payload: dict) -> dict:
        holds = payload.get("holds", [])
        if not isinstance(holds, list) or not all(isinstance(item, str) for item in holds):
            raise ValueError("holds must be a list of operation names")
        released = payload.get("released", True)
        if not isinstance(released, bool):
            raise ValueError("released must be a boolean")
        timeout = payload.get("timeout_seconds", DEFAULT_GATE_TIMEOUT_SECONDS)
        if not isinstance(timeout, (int, float)) or not (
            0 < timeout <= MAX_GATE_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_seconds must be in (0, 600]")
        self.holds = set(holds)
        self.released = released
        self.timeout_seconds = float(timeout)
        if released:
            self.blocked.clear()
        return self.snapshot()

    async def wait(self, operation: str) -> None:
        if self.released or operation not in self.holds:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        # Duplicates are possible for concurrent calls (e.g. two proposals); the
        # tests only read presence.
        self.blocked.append(operation)
        try:
            while not self.released and loop.time() < deadline:
                await asyncio.sleep(0.02)
        finally:
            try:
                self.blocked.remove(operation)
            except ValueError:
                pass


GATE = E2EDiscussionGate()


def install_gate(app) -> None:
    """Patch the scripted provider and expose the E2E control route (test-only)."""

    from fastapi import Request
    from fastapi.responses import JSONResponse

    from app.llm.providers import ScriptedProvider

    original_complete = ScriptedProvider.complete

    async def gated_complete(self, slot, messages, *, schema=None, tools=None, **kwargs):
        await GATE.wait(str(kwargs.get("discussion_operation") or ""))
        return await original_complete(
            self, slot, messages, schema=schema, tools=tools, **kwargs
        )

    # The discussion fixture provider inherits ``complete`` from this base class,
    # so one class-level patch covers it without touching product/fixture code.
    ScriptedProvider.complete = gated_complete  # type: ignore[method-assign]

    @app.get("/api/e2e/discussion-gate")
    async def read_discussion_gate():
        return GATE.snapshot()

    @app.post("/api/e2e/discussion-gate")
    async def write_discussion_gate(request: Request):
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a client error
            return JSONResponse(status_code=400, content={"detail": "request body must be JSON"})
        if not isinstance(payload, dict):
            return JSONResponse(status_code=400, content={"detail": "request body must be an object"})
        try:
            return GATE.configure(payload)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})


def install_seed(app) -> None:
    """TEST-ONLY workstation seed route (see the docstring for why it exists).

    The seed predates the fix for the POST /discussion-sessions/{id}/plan
    checkpoint regression and is kept for deterministic isolation: the
    workstation page and task role-memory API exercised here are the real ones.

    It uses only real internal bench helpers (``create_project``, ``BotRegistry``,
    ``MembershipService``, ``create_run``, ``_materialize_tasks``,
    ``_persist_snapshot``) plus the already-published discussion-e2e fixture plan
    data (the same deterministic task graph the scripted plan call would produce).
    It never rewrites a product module, never patches product behavior and never
    simulates a memory response.
    """

    from fastapi import Request

    @app.post("/api/e2e/seed-workstation-run")
    async def seed_workstation_run(request: Request):
        import copy
        import uuid

        from app.bots.registry import BotRegistry
        from app.fixtures.discussion_e2e import _plan
        from app.projects.membership import MembershipCreate, MembershipService
        from app.schemas.bot import BotCreate

        bench = request.app.state.workbench
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - an empty body is fine
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        idea = str(
            payload.get("idea")
            or "做一个能按楼层查看自习室剩余座位并允许到场学生上报的小程序。"
        )
        unique = uuid.uuid4().hex[:8]
        project = bench.create_project(f"角色记忆种子-{unique}", "python-pytest")
        async with bench.db_session() as session:
            registry = BotRegistry(session)
            leader = await registry.create(
                BotCreate(
                    display_name=f"Seed-Leader-{unique}",
                    role_template="leader",
                    provider_ref="dashscope",
                    model="qwen-max",
                    slot="flagship",
                    secret_ref="DASHSCOPE_API_KEY",
                )
            )
            member = await registry.create(
                BotCreate(
                    display_name=f"Seed-Member-{unique}",
                    role_template="pm",
                    provider_ref="dashscope",
                    model="qwen-plus",
                    slot="coder",
                    secret_ref="DASHSCOPE_API_KEY",
                )
            )
            service = MembershipService(
                session, project_exists=lambda pid: pid in bench.projects
            )
            await service.add(
                project["id"],
                MembershipCreate(bot_id=leader.bot_id, role_in_project="lead", is_leader=True),
            )
            await service.add(
                project["id"],
                MembershipCreate(bot_id=member.bot_id, role_in_project="dev", is_leader=False),
            )
            await session.commit()

        run = bench.create_run(project["id"], idea)
        fixture = _plan(revised=False)
        # Same deterministic plan data the scripted `plan` model call returns.
        run.artifacts.update(
            plan=copy.deepcopy(fixture["plan"]),
            spec=copy.deepcopy(fixture["spec"]),
            design=copy.deepcopy(fixture["design"]),
        )
        bench._materialize_tasks(run)
        bench._persist_snapshot(run)
        tasks = [
            {"code": code, "role": str(task.get("card", {}).get("role") or "")}
            for code, task in sorted(run.tasks.items())
        ]
        return {
            "seed": "test-only: deterministic workstation seed (no discussion required)",
            "run_id": run.id,
            "project_id": project["id"],
            "leader_bot_id": leader.bot_id,
            "member_bot_id": member.bot_id,
            "tasks": tasks,
        }


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    import uvicorn
    from app.execution.simulation import ExecutionPolicy
    from app.main import create_app
    with tempfile.TemporaryDirectory(prefix='hexagraph-discussion-e2e-') as data:
        os.environ['TEST3_DATA_DIR'] = data
        # Side-effect-free executor: this E2E must not write a repo, run commands
        # or merge branches. Product defaults remain the real executor.
        app = create_app(execution_policy=ExecutionPolicy(simulated=True))
        install_gate(app)
        install_seed(app)
        uvicorn.run(app, host='127.0.0.1', port=8766)