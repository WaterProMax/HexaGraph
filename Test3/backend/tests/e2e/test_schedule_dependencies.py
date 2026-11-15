from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from app.llm.providers import ScriptedProvider, validate_tool_protocol
from app.llm.types import LLMResult
from app.schemas.docs import TaskGraph
from app.services.runtime import Workbench
from tests.e2e.test_must_fixes import _bench, _card
from app.schemas.common import AcceptanceCheck


class _ByTaskProvider(ScriptedProvider):
    """按 task_card.code 路由预置输出；用于 A/B/C/D 依赖图，不写死产品分解。"""

    def __init__(self, by_task: dict[str, list]) -> None:
        super().__init__([])
        self.by_task = {key: list(items) for key, items in by_task.items()}

    async def complete(self, slot, messages, *, schema=None, tools=None, **kwargs):  # type: ignore[override]
        self.calls.append({"slot": slot, "messages": messages, "schema": schema, "tools": tools})
        validate_tool_protocol(messages, tools)
        blob = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
        match = re.search(r'<资料 name="task_card">\s*(.*?)\s*</资料>', blob, re.S)
        code = json.loads(match.group(1)).get("code") if match else None
        item = self.by_task[code].pop(0)
        if isinstance(item, dict) and item.get("tool_calls"):
            return LLMResult(tool_calls=item["tool_calls"], parsed=item.get("parsed"), text=item.get("text", ""), model=slot)
        parsed = {k: v for k, v in item.items() if k not in {"tokens_in", "tokens_out", "text"}} if isinstance(item, dict) else {}
        return LLMResult(text=json.dumps(parsed, ensure_ascii=False), parsed=parsed, model=slot)


def _task(code: str, deps: list[str], path: str) -> object:
    return _card(
        code=code,
        title=code,
        depends_on=deps,
        write_set=[path],
        outputs=[path],
        acceptance=[AcceptanceCheck(cmd=["python", "-m", "pytest", path, "-q"], pass_criteria="ok", from_criterion="F1")],
    )


def _queue(code: str, path: str) -> list:
    body = f"def test_{code.lower()}():\n    assert True\n"
    return [
        {"tool_calls": [{"name": "write_file", "arguments": {"path": path, "content": body}}]},
        {"done": True, "summary": code, "files": [path]},
        {"verdict": "pass", "issues": []},
    ]


def _dag(tmp_path: Path, provider: ScriptedProvider) -> tuple[Workbench, object]:
    bench, _ = _bench(tmp_path)
    bench.gateway.provider = provider
    project = bench.create_project("dag")
    run = bench.create_run(project["id"], "dag")
    run.engine.current = "7"
    graph = TaskGraph(
        tasks=[
            _task("A", [], "tests/test_a.py"),
            _task("B", ["A"], "tests/test_b.py"),
            _task("C", ["A"], "tests/test_c.py"),
            _task("D", ["B", "C"], "tests/test_d.py"),
        ]
    )
    run.artifacts["plan"] = graph.model_dump()
    bench._materialize_tasks(run)
    return bench, run


def _states(run) -> dict[str, str]:
    return {code: task["state"] for code, task in run.tasks.items()}


def _seed_repo(bench: Workbench, run) -> None:
    """给“已手工标记 done”的任务补上真实文件，避免集成回归误判。"""
    from app.workspace.gitops import init_repo_sync

    repo = bench.data_dir / "runs" / run.id / "repo"
    files = {"tests/__init__.py": "", ".gitignore": "__pycache__/\n*.pyc\n.pytest_cache/\n"}
    for code in ("A", "B", "C", "D"):
        files[f"tests/test_{code.lower()}.py"] = f"def test_{code.lower()}():\n    assert True\n"
    init_repo_sync(repo, files)


@pytest.mark.asyncio
async def test_downstream_does_not_start_before_dependency(tmp_path: Path) -> None:
    bench, run = _dag(tmp_path, _ByTaskProvider({}))
    assert _states(run) == {"A": "ready", "B": "pending", "C": "pending", "D": "pending"}
    run.tasks["A"]["state"] = "running"
    assert await bench.schedule_once(run) == []
    assert _states(run)["D"] == "pending"

    run.tasks["A"]["state"] = "done"
    bench._refresh_ready(run)
    states = _states(run)
    assert states["B"] == "ready" and states["C"] == "ready"
    assert states["D"] == "pending"


@pytest.mark.asyncio
async def test_b_failure_blocks_d_but_does_not_cancel_c(tmp_path: Path) -> None:
    bench, run = _dag(tmp_path, _ByTaskProvider({}))
    run.tasks["A"]["state"] = "done"
    run.tasks["C"]["state"] = "done"
    run.tasks["B"]["state"] = "failed"
    bench._refresh_ready(run)
    assert _states(run)["D"] == "pending"
    assert await bench.schedule_once(run) == []
    assert run.tasks["C"]["state"] == "done"


@pytest.mark.asyncio
async def test_d_starts_after_b_retry_success_and_c_done(tmp_path: Path) -> None:
    provider = _ByTaskProvider({"D": _queue("D", "tests/test_d.py")})
    bench, run = _dag(tmp_path, provider)
    _seed_repo(bench, run)
    run.tasks["A"]["state"] = "done"
    run.tasks["C"]["state"] = "done"
    run.tasks["B"]["state"] = "done"
    bench._refresh_ready(run)
    assert run.tasks["D"]["state"] == "ready"
    started = await bench.schedule_once(run)
    assert started == ["D"]
    assert run.tasks["D"]["state"] == "done"


@pytest.mark.asyncio
async def test_pause_stops_dispatch_and_resume_restores(tmp_path: Path) -> None:
    provider = _ByTaskProvider(
        {
            "B": _queue("B", "tests/test_b.py"),
            "C": _queue("C", "tests/test_c.py"),
            "D": _queue("D", "tests/test_d.py"),
        }
    )
    bench, run = _dag(tmp_path, provider)
    _seed_repo(bench, run)
    run.tasks["A"]["state"] = "done"
    bench._refresh_ready(run)
    assert run.tasks["B"]["state"] == "ready" and run.tasks["C"]["state"] == "ready"
    bench.set_run_control(run, "pause")
    assert await bench.schedule_once(run) == []
    assert run.tasks["B"]["state"] == "ready"

    bench.set_run_control(run, "resume")
    started = await bench.schedule_once(run)
    assert {"B", "C"} <= set(started)
    assert run.tasks["B"]["state"] == "done"
    assert run.tasks["C"]["state"] == "done"


@pytest.mark.asyncio
async def test_terminate_stops_dispatch_and_ignores_late_results(tmp_path: Path) -> None:
    bench, run = _dag(tmp_path, _ByTaskProvider({}))
    run.tasks["A"]["state"] = "done"
    bench._refresh_ready(run)
    bench.set_run_control(run, "terminate", confirm=True)
    assert run.status == "terminated"
    assert run.tasks["B"]["state"] == "cancelled"
    assert await bench.schedule_once(run) == []

    late = await bench.execute_task(run, "B")
    assert late["kind"] == "已终止"
    assert run.tasks["B"]["state"] == "cancelled"
    assert run.engine.current == "7"


@pytest.mark.asyncio
async def test_duplicate_schedule_requests_dispatch_once(tmp_path: Path) -> None:
    provider = _ByTaskProvider({"A": _queue("A", "tests/test_a.py")})
    bench, run = _dag(tmp_path, provider)
    for code in ("B", "C", "D"):
        run.tasks[code]["state"] = "cancelled"
    assert run.tasks["A"]["state"] == "ready"
    results = await asyncio.gather(bench.schedule_once(run), bench.schedule_once(run))
    started = [code for batch in results for code in batch]
    assert started.count("A") == 1
    assert run.tasks["A"]["state"] == "done"
    assert sum(1 for call in provider.calls if call["slot"] == "coder") == 2


@pytest.mark.asyncio
async def test_running_task_occupies_slot_and_blocks_same_write_set(tmp_path: Path) -> None:
    bench, run = _dag(tmp_path, _ByTaskProvider({}))
    run.tasks["A"]["state"] = "running"
    assert await bench.schedule_once(run) == []
    assert run.tasks["B"]["state"] == "pending"
