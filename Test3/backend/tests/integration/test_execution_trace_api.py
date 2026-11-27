"""I1 integration tests: real execution steps reach the trace API and event bus.

Offline only: a scripted provider, a temporary data dir and local git.  The
legacy path test drives the production ``Workbench.execute_task`` so it proves
the recorder is really wired into ``_execute_task_locked`` (not just unit-tested
in isolation), and that its events are pushed on ``run.events``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry, run_tool_agent
from app.execution.simulation import ExecutionPolicy
from app.execution.trace_log import EXECUTION_PATH_LEGACY, EXECUTION_PATH_SIMULATED
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.llm.types import LLMResult
from app.main import create_app
from app.schemas.common import AcceptanceCheck, Budget
from app.schemas.docs import TaskCard, TaskGraph
from app.schemas.execution_grant import ExecutionGrant
from app.services import runtime as runtime_module
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.tools.taskset import TaskToolset

#: A marker that exists only inside the write_file body.  It must never appear
#: in a step summary, an event payload or the trace API response.
WRITE_BODY_MARKER = "WRITE_BODY_MARKER_MUST_NOT_LEAK"
#: ``sk-`` shaped value in the task description (which is part of the prompt).
#: The recorder must redact it instead of copying the prompt into the trace.
SECRET_SHAPED = "sk-live-abcdef1234567890"


def _bench(tmp_path: Path, queue: list, policy: ExecutionPolicy | None = None) -> tuple[Workbench, ScriptedProvider]:
    provider = ScriptedProvider(queue)
    bench = Workbench(
        Gateway(load_models(), provider),
        RoleRegistry(load_roles()),
        tmp_path,
        execution_policy=policy or ExecutionPolicy(local_execution_authorized=True),
    )
    return bench, provider


def _card(code: str = "T-01", description: str = "trace probe") -> TaskCard:
    write_set = ["tests/test_feature.py"]
    return TaskCard.model_validate(
        {
            "code": code,
            "title": "trace",
            "kind": "impl",
            "module": "M1",
            "sources": ["F1"],
            "description": description,
            "write_set": write_set,
            "outputs": write_set,
            "acceptance": [
                AcceptanceCheck(cmd=["python", "-m", "pytest", "-q"], pass_criteria="ok", from_criterion="F1")
            ],
            "depends_on": [],
            "points": 2,
            "priority": "P0",
            "role": "coder",
            "budget": Budget(),
        }
    )


def _ready_run(bench: Workbench, codes: list[str] = ("T-01",), description: str = "trace probe"):
    project = bench.create_project("trace")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[_card(code, description) for code in codes]).model_dump()
    bench._materialize_tasks(run)
    for code in codes:
        run.tasks[code]["state"] = "ready"
    return run


def _tool_loop_queue() -> list:
    """read_file, write_file, final answer, then the reviewer verdict."""
    body = f"def test_feature():\n    assert True\n\n# {WRITE_BODY_MARKER}\n# {SECRET_SHAPED}\n"
    return [
        {"tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "tests/test_smoke.py"}}]},
        {"tool_calls": [{"id": "c2", "name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": body}}]},
        {"done": True, "summary": "implemented", "files": ["tests/test_feature.py"]},
        {"verdict": "pass", "issues": []},
    ]


def _client(bench: Workbench) -> AsyncClient:
    app = create_app()
    app.state.workbench = bench
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _steps(payload: dict) -> list[dict]:
    assert payload["attempts"], payload
    return payload["attempts"][-1]["steps"]


# --- legacy tool-agent path, wired through Workbench.execute_task -----------


@pytest.mark.asyncio
async def test_legacy_tool_loop_steps_reach_trace_api(tmp_path: Path) -> None:
    bench, _provider = _bench(tmp_path, _tool_loop_queue())
    try:
        run = _ready_run(bench, ["T-01"], description=f"trace probe {SECRET_SHAPED}")
        result = await bench.execute_task(run, "T-01")
        assert run.tasks["T-01"]["state"] == "done", result

        async with _client(bench) as client:
            response = await client.get(f"/api/runs/{run.id}/tasks/T-01/execution-trace")
        assert response.status_code == 200
        payload = response.json()
        assert payload["execution_path"] == EXECUTION_PATH_LEGACY
        assert payload["context_injected"] is True
        steps = _steps(payload)
        kinds = [step["kind"] for step in steps]
        assert kinds.count("llm") >= 1
        tool_steps = [step for step in steps if step["kind"] == "tool"]
        assert [step["name"] for step in tool_steps] == ["read_file", "write_file"]
        assert all(step["status"] == "ok" for step in tool_steps)
        assert all(isinstance(step["duration_ms"], int) for step in steps)

        # LLM steps carry model/slot/token/finish metadata but never the prompt.
        llm_steps = [step for step in steps if step["kind"] == "llm"]
        assert all(step["name"] == "coder" for step in llm_steps)
        assert all(step["model"] for step in llm_steps)
        assert all(step["slot"] == "coder" for step in llm_steps)
        assert "system:" in llm_steps[0]["input_summary"]

        # write_file: path + length + sha only; the body never enters the trace.
        write_step = next(step for step in tool_steps if step["name"] == "write_file")
        assert "path=tests/test_feature.py" in write_step["input_summary"]
        assert "sha256=" in write_step["input_summary"]
        assert WRITE_BODY_MARKER not in write_step["input_summary"]
        assert WRITE_BODY_MARKER not in write_step["output_summary"]
        assert SECRET_SHAPED not in json.dumps(payload, ensure_ascii=False)

        # read_file keeps a clipped preview (it read the seeded smoke test).
        read_step = next(step for step in tool_steps if step["name"] == "read_file")
        assert "chars=" in read_step["output_summary"]
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_trace_events_are_pushed_to_the_run_bus_without_secrets(tmp_path: Path) -> None:
    bench, _provider = _bench(tmp_path, _tool_loop_queue())
    try:
        run = _ready_run(bench, ["T-01"], description=f"trace probe {SECRET_SHAPED}")
        result = await bench.execute_task(run, "T-01")
        assert run.tasks["T-01"]["state"] == "done", result

        llm_events = [event for event in run.events if event["kind"] == "task.llm_step"]
        tool_events = [event for event in run.events if event["kind"] == "task.tool_step"]
        assert llm_events
        assert [event["payload"]["name"] for event in tool_events] == ["read_file", "write_file"]
        assert all(event["subject"] == "T-01" for event in llm_events + tool_events)
        assert all(event["payload"]["attempt_id"] for event in llm_events + tool_events)

        blob = json.dumps([event["payload"] for event in llm_events + tool_events], ensure_ascii=False)
        assert WRITE_BODY_MARKER not in blob
        assert "sk-" not in blob
        assert SECRET_SHAPED not in blob
        # The prompt preview is redacted rather than dropped.
        assert "***REDACTED***" in blob
    finally:
        await bench.close()


@pytest.mark.asyncio
async def test_unexecuted_task_trace_is_empty_and_not_404(tmp_path: Path) -> None:
    bench, _provider = _bench(tmp_path, _tool_loop_queue())
    try:
        run = _ready_run(bench, ["T-01", "T-02"], description=f"trace probe {SECRET_SHAPED}")
        result = await bench.execute_task(run, "T-01")
        assert run.tasks["T-01"]["state"] == "done", result

        async with _client(bench) as client:
            response = await client.get(f"/api/runs/{run.id}/tasks/T-02/execution-trace")
        assert response.status_code == 200
        payload = response.json()
        assert payload["task_code"] == "T-02"
        assert payload["attempts"] == []
        assert payload["execution_path"] == ""
        assert payload["context_injected"] is False
    finally:
        await bench.close()


# --- granted path -----------------------------------------------------------


@pytest.mark.asyncio
async def test_granted_path_records_exactly_one_command_step(tmp_path: Path, monkeypatch) -> None:
    """granted_v1 records the one real command, never a fake tool loop."""
    bench, _provider = _bench(tmp_path, [])
    try:
        run = _ready_run(bench, ["T-01"])
        task = run.tasks["T-01"]
        card = TaskCard.model_validate(task["card"])
        bench._begin_attempt(run, task, "T-01")
        bench._set_state(run, task, "scheduled")  # ready -> running, as in the locked path
        grant = ExecutionGrant(
            grant_id="G-1",
            run_id=run.id,
            execution_profile="granted_v1",
            task_codes=["T-01"],
            approved_baseline_hashes={},
            repo_remote="origin",
            repo_owner="owner",
            repo_name="repo",
            base_branch="teamwork-001",
            feature_branch="feat/trace",
            allowed_tool_refs=["python -m pytest"],
            created_at="2026-11-26T00:00:00+00:00",
        )

        async def fake_granted(*_args, **_kwargs):
            return SimpleNamespace(
                argv=["python", "-m", "pytest", "-q"],
                output="1 passed",
                exit_code=0,
                ok=True,
                evidence={"ok": True},
                evidence_path="",
            )

        monkeypatch.setattr(runtime_module, "create_worktree", lambda *a, **k: None)
        monkeypatch.setattr(runtime_module, "init_repo_sync", lambda *a, **k: None)
        monkeypatch.setattr(runtime_module, "execute_task_granted", fake_granted)
        monkeypatch.setattr(bench, "_block_unless_isolated", lambda *a, **k: None)

        result = await bench._execute_granted_task(
            run,
            "T-01",
            task,
            card,
            {"command": ["python", "-m", "pytest", "-q"], "writes": [], "tool_refs": ["python -m pytest"]},
            grant,
        )
        assert result["state"] == "done"
        attempt = task["attempt"]
        assert attempt["execution_path"] == "granted_v1"
        assert attempt["context_injected"] is False
        assert len(attempt["execution_steps"]) == 1
        step = attempt["execution_steps"][0]
        assert step["kind"] == "granted_command"
        assert step["name"] == "python"
        assert step["status"] == "ok"
        assert step["input_summary"] == "argv=python -m pytest -q"
        assert "exit=0" in step["output_summary"]

        events = [event for event in run.events if event["kind"] == "task.granted_command"]
        assert len(events) == 1
        assert events[0]["payload"]["kind"] == "granted_command"
        assert events[0]["payload"]["attempt_id"] == attempt["attempt_id"]
    finally:
        await bench.close()


# --- simulated path ---------------------------------------------------------


@pytest.mark.asyncio
async def test_simulated_path_records_no_llm_or_tool_steps(tmp_path: Path) -> None:
    bench, _provider = _bench(tmp_path, [], policy=ExecutionPolicy(simulated=True))
    try:
        run = _ready_run(bench, ["T-01"])
        started = await bench.schedule_once(run)
        assert started == ["T-01"]
        assert run.tasks["T-01"]["state"] == "done"

        async with _client(bench) as client:
            response = await client.get(f"/api/runs/{run.id}/tasks/T-01/execution-trace")
        assert response.status_code == 200
        payload = response.json()
        assert payload["execution_path"] == EXECUTION_PATH_SIMULATED
        assert payload["context_injected"] is False
        assert payload["attempts"], "the simulated run still has one attempt"
        assert payload["attempts"][-1]["steps"] == []
        assert not [event for event in run.events if event["kind"].startswith("task.llm_step")]
        assert not [event for event in run.events if event["kind"].startswith("task.tool_step")]
    finally:
        await bench.close()


# --- observer contract at the agent boundary -------------------------------


@pytest.mark.asyncio
async def test_observer_exception_is_fail_open(tmp_path: Path) -> None:
    """A raising observer must not interrupt the tool loop or change the result."""
    provider = ScriptedProvider(_tool_loop_queue()[:3])
    gateway = Gateway(load_models(), provider)
    toolset = TaskToolset(
        tmp_path,
        ["tests/test_feature.py"],
        whitelist=["python -m pytest"],
        timeout=5,
        env_allow=["PATH"],
        truncate=100,
    )

    def broken_observer(_kind: str, _data: dict) -> None:
        raise RuntimeError("observer down")

    result = await run_tool_agent(
        "coder",
        {"task_card": {"code": "T-01"}},
        toolset,
        registry=RoleRegistry(load_roles()),
        gateway=gateway,
        max_steps=5,
        on_step=broken_observer,
    )
    assert result == {"done": True, "summary": "implemented", "files": ["tests/test_feature.py"]}
    assert (tmp_path / "tests" / "test_feature.py").exists()


@pytest.mark.asyncio
async def test_no_on_step_keeps_the_original_agent_behaviour(tmp_path: Path) -> None:
    """Omitting on_step yields the same calls/result as the pre-I1 agent."""

    async def _run(observer, label: str):
        provider = ScriptedProvider(_tool_loop_queue()[:3])
        gateway = Gateway(load_models(), provider)
        toolset = TaskToolset(
            tmp_path / label,
            ["tests/test_feature.py"],
            whitelist=["python -m pytest"],
            timeout=5,
            env_allow=["PATH"],
            truncate=100,
        )
        result = await run_tool_agent(
            "coder",
            {"task_card": {"code": "T-01"}},
            toolset,
            registry=RoleRegistry(load_roles()),
            gateway=gateway,
            max_steps=5,
            **({} if observer is None else {"on_step": observer}),
        )
        return result, json.loads(json.dumps(provider.calls, ensure_ascii=False, default=str))

    steps: list[tuple[str, dict]] = []
    baseline_result, baseline_calls = await _run(None, "baseline")
    observed_result, observed_calls = await _run(lambda kind, data: steps.append((kind, data)), "observed")
    assert baseline_result == observed_result
    assert baseline_calls == observed_calls
    assert [kind for kind, _data in steps] == ["llm", "tool", "llm", "tool", "llm"]
    assert [data["name"] for kind, data in steps if kind == "tool"] == ["read_file", "write_file"]


class _StubGateway:
    """Minimal gateway double: returns queued LLMResult values or raises."""

    def __init__(self, results: list) -> None:
        self.results = list(results)

    async def complete(self, _slot, _messages, **_kwargs):
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_denied_tool_and_tool_error_are_observed_before_propagation() -> None:
    steps: list[tuple[str, dict]] = []
    gateway = _StubGateway(
        [
            LLMResult(tool_calls=[{"id": "c1", "name": "write_file", "arguments": {"path": "x", "content": "y"}}]),
            LLMResult(text="done", parsed={"done": True}),
        ]
    )
    async def _denied(_name: str, _args: dict) -> dict:
        return {"ok": False, "denied": True, "error": "写集外: x"}

    denied_toolset = SimpleNamespace(specs=None, execute=_denied)
    result = await run_tool_agent(
        "coder",
        {"task_card": {"code": "T-01"}},
        denied_toolset,
        registry=RoleRegistry(load_roles()),
        gateway=gateway,
        max_steps=4,
        on_step=lambda kind, data: steps.append((kind, data)),
    )
    assert result == {"done": True}
    tool_data = [data for kind, data in steps if kind == "tool"][0]
    assert tool_data["status"] == "denied"
    assert tool_data["error"] == "写集外: x"

    async def _explode(_name: str, _args: dict) -> dict:
        raise RuntimeError("tool exploded")

    exploding = SimpleNamespace(specs=None, execute=_explode)
    gateway = _StubGateway(
        [LLMResult(tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}])]
    )
    steps.clear()
    with pytest.raises(RuntimeError, match="tool exploded"):
        await run_tool_agent(
            "coder",
            {"task_card": {"code": "T-01"}},
            exploding,
            registry=RoleRegistry(load_roles()),
            gateway=gateway,
            max_steps=4,
            on_step=lambda kind, data: steps.append((kind, data)),
        )
    error_data = [data for kind, data in steps if kind == "tool"][0]
    assert error_data["status"] == "error"
    assert error_data["error"] == "tool exploded"

    steps.clear()
    with pytest.raises(ValueError, match="model down"):
        await run_tool_agent(
            "coder",
            {"task_card": {"code": "T-01"}},
            denied_toolset,
            registry=RoleRegistry(load_roles()),
            gateway=_StubGateway([ValueError("model down")]),
            max_steps=4,
            on_step=lambda kind, data: steps.append((kind, data)),
        )
    assert steps[0][0] == "llm"
    assert steps[0][1]["status"] == "error"
    assert steps[0][1]["error"] == "model down"