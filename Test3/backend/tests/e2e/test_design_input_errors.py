"""Design-spec import error categories persist on the run, without secret dumps."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from app.agents.runtime import RoleRegistry
from app.errors import CATEGORY_TITLES, user_message_for_category
from app.llm.gateway import Gateway
from app.schemas.design_input import DesignSource
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from tests.e2e.test_design_input import DESIGN, SPEC, _intake, finish_design_import
from tests.e2e.test_design_input_lifecycle import _hold_bench, _wait_not_importing
from tests.e2e.test_must_fixes import _bench


class HttpStatusError(Exception):
    def __init__(self, status: int, text: str = "") -> None:
        self.status_code = status
        super().__init__(text or f"status {status}")


class RaiseProvider:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[dict] = []

    async def complete(self, slot: str, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append({"slot": slot, "messages": messages, "kwargs": kwargs})
        raise self.exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]


def _raise_bench(tmp_path, exc: Exception):
    provider = RaiseProvider(exc)
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    return bench, provider


def _secret_blob(*parts: object) -> str:
    return " ".join(json.dumps(p, ensure_ascii=False) if not isinstance(p, str) else p for p in parts).lower()


def _assert_no_secrets(blob: str) -> None:
    assert "sk-" not in blob
    assert "authorization" not in blob
    assert "bearer" not in blob
    assert "/etc/passwd" not in blob
    assert "traceback" not in blob


def _assert_not_success(run, result: dict) -> None:
    assert result["status"] != "awaiting_confirmation"
    assert run.artifacts.get("design_input_status") != "awaiting_confirmation"
    assert run.gates == []
    assert "baseline_DESIGN" not in run.artifacts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (ConnectionError("Connection refused to api.dashscope.aliyuncs.com"), "connection"),
        (HttpStatusError(401, "Authorization: Bearer sk-secret-key"), "auth"),
        (HttpStatusError(429, "Too Many Requests"), "rate_limit"),
        (TimeoutError("read timed out talking to dashscope"), "timeout"),
        (ImportError("Using SOCKS proxy, but the 'socksio' package is not installed."), "environment"),
    ],
)
async def test_design_import_llm_failures_set_error_category(tmp_path, exc: Exception, category: str) -> None:
    bench, _ = _raise_bench(tmp_path, exc)
    project = bench.create_project("p")
    result = await finish_design_import(
        bench, await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    )
    run = bench.runs[result["run_id"]]
    title = user_message_for_category(category)
    assert result["error_category"] == category
    assert run.artifacts.get("design_input_error_category") == category
    assert result["status"] == "failed"
    assert result["message"] == title
    assert result["errors"]
    assert title in " ".join(result["errors"])
    _assert_not_success(run, result)
    blob = _secret_blob(result, run.artifacts.get("design_input_message"), run.artifacts.get("design_input_errors"))
    _assert_no_secrets(blob)
    assert "dashscope" not in blob
    assert "api.dashscope" not in blob


@pytest.mark.asyncio
async def test_design_import_timeout_watchdog_sets_timeout_category(tmp_path) -> None:
    bench, provider, hold = _hold_bench(tmp_path, _intake(), import_timeout_s=0.08)
    project = bench.create_project("p")
    result = await asyncio.wait_for(
        bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource()),
        timeout=1.0,
    )
    status = await _wait_not_importing(bench, result["run_id"], timeout=2.0)
    run = bench.runs[result["run_id"]]
    viewed = bench._design_run_result(run)
    assert status == "failed"
    assert viewed["error_category"] == "timeout"
    assert run.artifacts.get("design_input_error_category") == "timeout"
    assert viewed["message"]
    assert "超时" in viewed["message"] or "超时" in " ".join(viewed["errors"])
    _assert_not_success(run, viewed)
    hold.set()
    try:
        await asyncio.wait_for(provider.finished.wait(), timeout=0.5)
    except TimeoutError:
        pass
    assert run.artifacts.get("design_input_status") != "awaiting_confirmation"


@pytest.mark.asyncio
async def test_design_import_missing_fields_sets_category_and_keeps_missing(tmp_path) -> None:
    bench, _ = _bench(tmp_path, _intake(["未给出并发上限"]))
    project = bench.create_project("p")
    result = await finish_design_import(
        bench, await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    )
    run = bench.runs[result["run_id"]]
    assert result["status"] == "needs_input"
    assert result["error_category"] == "missing_fields"
    assert result["missing"] == ["未给出并发上限"]
    assert result["message"] == CATEGORY_TITLES["missing_fields"] or "缺" in result["message"]
    assert run.artifacts.get("design_input_error_category") == "missing_fields"
    _assert_not_success(run, result)


@pytest.mark.asyncio
async def test_design_import_invalid_structure_from_checks_sets_category(tmp_path) -> None:
    design = copy.deepcopy(DESIGN)
    design["modules"][0]["sources"] = ["F999"]
    queue = [
        {"spec": copy.deepcopy(SPEC), "missing": [], "notes": "ok"},
        {"design": design, "missing": [], "notes": "ok"},
    ]
    bench, _ = _bench(tmp_path, queue)
    project = bench.create_project("p")
    result = await finish_design_import(
        bench, await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    )
    run = bench.runs[result["run_id"]]
    assert result["status"] == "needs_input"
    assert result["error_category"] == "invalid_structure"
    assert result["errors"]
    assert any("F999" in item or "来源不存在" in item for item in result["errors"])
    assert result["message"] == CATEGORY_TITLES["invalid_structure"] or "结构" in result["message"]
    assert run.artifacts.get("design_input_error_category") == "invalid_structure"
    _assert_not_success(run, result)


@pytest.mark.asyncio
async def test_design_import_unparseable_model_output_is_invalid_structure(tmp_path) -> None:
    bench, _ = _bench(tmp_path, [{"foo": 1}, {"foo": 1}])
    project = bench.create_project("p")
    result = await finish_design_import(
        bench, await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    )
    run = bench.runs[result["run_id"]]
    assert result["status"] == "failed"
    assert result["error_category"] == "invalid_structure"
    assert run.artifacts.get("design_input_error_category") == "invalid_structure"
    _assert_not_success(run, result)
    blob = _secret_blob(result, run.artifacts.get("design_input_errors"), run.artifacts.get("design_input_message"))
    _assert_no_secrets(blob)
    assert "validation error" not in blob
    assert "traceback" not in blob


@pytest.mark.asyncio
async def test_successful_import_has_no_error_category(tmp_path) -> None:
    bench, _ = _bench(tmp_path, _intake())
    project = bench.create_project("p")
    result = await finish_design_import(
        bench, await bench.create_design_run(project["id"], "目标：学生查看空位。", DesignSource())
    )
    assert result["status"] == "awaiting_confirmation"
    assert not result.get("error_category")
    run = bench.runs[result["run_id"]]
    assert not run.artifacts.get("design_input_error_category")
    assert any(g["kind"] == "DESIGN基线确认" for g in run.gates)
