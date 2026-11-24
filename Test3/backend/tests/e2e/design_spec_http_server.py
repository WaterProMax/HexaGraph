"""真实 HTTP 离线验证服务器：显式 ScriptedProvider，不读取 .env，不启动真实模型。

从 Test3/backend 运行：
  PATH="$PWD/.venv/bin:$PATH" .venv/bin/python tests/e2e/design_spec_http_server.py
"""
from __future__ import annotations

import argparse
import copy
import sys
import tempfile
from pathlib import Path

import uvicorn

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.runtime import RoleRegistry
from app.execution.simulation import ExecutionPolicy
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.test_design_input import PLAN, _intake


def execution_queue(code: str, path: str) -> list[dict]:
    return [
        {"tool_calls": [{"name": "write_file", "arguments": {"path": path, "content": f"# offline fixture for {code}\n"}}]},
        {"done": True, "summary": code, "files": [path]},
        {"verdict": "pass", "issues": []},
    ]


def build_offline_queue() -> list[dict]:
    """One successful seat-query import, then one missing import; then the queue is exhausted.

    Matches `examples/design-specs/self-study-room.md`. Does not start the 5s auto-scheduler.
    Tests and demos must each start their own process with a fresh data dir.
    """
    plan = copy.deepcopy(PLAN)
    for task in plan["tasks"]:
        task["acceptance"][0]["cmd"] = ["python", "-m", "pytest", "tests/test_smoke.py", "-q"]
    return (
        _intake()
        + [plan]
        + execution_queue("T-01", "src/seats.py")
        + execution_queue("T-02", "tests/test_seats.py")
        + _intake(["缺少并发冲突处理与可检查的验收条件"])
    )


def create_offline_app(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    provider = ScriptedProvider(build_offline_queue())
    gateway = Gateway(load_models(), provider, data_dir=data_dir)
    workbench = Workbench(
        gateway,
        RoleRegistry(load_roles()),
        data_dir,
        execution_policy=ExecutionPolicy(local_execution_authorized=True),
    )
    workbench.schedule_mode = "manual"
    app = create_app()
    app.state.workbench = workbench
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="hexagraph-design-http-"))
    app = create_offline_app(data_dir)

    # 不运行 app.main lifespan，避免 Settings 读取 .env；本服务器只用于测试。
    print(f"OFFLINE_SCRIPTED_DATA_DIR={data_dir}", flush=True)
    print("OFFLINE_SCHEDULE_MODE=manual", flush=True)
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning", lifespan="off")
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
