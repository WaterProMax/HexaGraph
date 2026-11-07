from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from app.docs.checks import PROPOSAL_CHAPTERS, check_proposal
from app.fixtures.study_room import IDEA, scripted_full_queue
from app.llm.providers import ScriptedProvider, validate_tool_protocol
from app.llm.types import LLMResult
from app.orchestrator.transition import apply_transition
from app.schemas.common import AcceptanceCheck
from app.schemas.docs import ProposalDoc, TaskGraph
from app.workspace.gitops import commit, create_worktree, init_repo_sync, remove_worktree
from tests.e2e.test_must_fixes import _bench, _card, _ready_run, _spec_payload


class _RoutedProvider(ScriptedProvider):
    def __init__(self, by_task: dict[str, list]) -> None:
        super().__init__([])
        self.by_task = {key: list(items) for key, items in by_task.items()}

    async def complete(self, slot: str, messages: list[dict], *, schema=None, tools=None, **kwargs):
        self.calls.append({"slot": slot, "messages": messages, "schema": schema, "tools": tools})
        validate_tool_protocol(messages, tools)
        blob = json.dumps(messages, ensure_ascii=False)
        key = "T-01" if "T-01" in blob else "T-02"
        item = self.by_task[key].pop(0)
        if isinstance(item, dict) and item.get("tool_calls"):
            return LLMResult(tool_calls=item["tool_calls"], parsed=item.get("parsed"), text=item.get("text", ""), model=slot, tokens_in=int(item.get("tokens_in") or 0), tokens_out=int(item.get("tokens_out") or 0))
        if isinstance(item, dict):
            tokens_in, tokens_out = int(item.get("tokens_in") or 0), int(item.get("tokens_out") or 0)
            parsed = {k: v for k, v in item.items() if k not in {"tokens_in", "tokens_out", "tool_calls", "text"}}
            return LLMResult(text=json.dumps(parsed, ensure_ascii=False), parsed=parsed, model=slot, tokens_in=tokens_in, tokens_out=tokens_out)
        return LLMResult(text=str(item), model=slot)


def test_runtime_task_state_only_via_transition() -> None:
    src = Path(__file__).resolve().parents[2] / "app/services/runtime.py"
    matches = re.findall(r'task\["state"\]\s*=(?!=)', src.read_text(encoding="utf-8"))
    assert matches == []


@pytest.mark.asyncio
async def test_gate_reject_does_not_approve(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path, [_spec_payload("重写后的规格")])
    run = _ready_run(bench, _card())
    run.artifacts["idea_card"] = {"raw": "x"}
    run.artifacts["proposal"] = {"elevator": "e"}
    run.artifacts["issues"] = []
    run.artifacts["reviews"] = []
    spec_gate = bench._gate(run, "SPEC基线确认", {"spec": run.artifacts["spec"]})
    rewritten = await bench.resolve_gate(run, spec_gate["gate"]["id"], "reject", {"reason": "重写"})
    assert spec_gate["gate"]["status"] == "rejected"
    assert rewritten.get("gate", {}).get("kind") == "SPEC基线确认"
    assert run.artifacts.get("baseline_SPEC") is None

    replan_gate = bench._gate(run, "重排提案", {"task": "T-01"})
    replan_reject = await bench.resolve_gate(run, replan_gate["gate"]["id"], "reject", {"reason": "先不重排"})
    assert replan_reject == {"status": "rejected", "kind": "重排提案"}
    assert run.tasks["T-01"]["state"] != "cancelled"

    cr_gate = bench._gate(run, "变更决定", {"cr": {"code": "CR-01"}})
    run.crs.append({"code": "CR-01", "impact": {"downstream": []}, "eval_flags": {}})
    cr_reject = await bench.resolve_gate(run, cr_gate["gate"]["id"], "reject", {"code": "CR-01"})
    assert cr_reject["status"] == "rejected"


@pytest.mark.asyncio
async def test_design_and_plan_reject_rewrites(tmp_path: Path) -> None:
    design = {
        "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
        "modules": [{"code": "M1", "name": "m", "responsibility": "r", "sources": ["F1"], "provides": ["C1"], "depends_on": [], "data": []}],
        "interfaces": [{"code": "C1", "provider": "M1", "consumers": ["M1"], "inputs": [], "outputs": [], "errors": []}],
        "data": [],
        "decisions": [],
        "contingencies": [],
        "appendix": "",
    }
    reviews = [
        {"reviewer": "架构", "dimension": "架构一致性", "score": 4, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]},
        {"reviewer": "质量", "dimension": "实现质量", "score": 4, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]},
    ]
    plan = {
        "tasks": [
            _card().model_dump(),
            _card(code="T-02", kind="test", role="tester", write_set=["tests/test_b.py"], outputs=["tests/test_b.py"], depends_on=["T-01"]).model_dump(),
        ],
        "notes": "",
        "capacity": 40,
    }
    bench, _ = _bench(tmp_path, [design, *reviews, plan])
    run = _ready_run(bench, _card())
    run.artifacts["issues"] = []
    run.artifacts["spec"] = {
        "features": [{"code": "F1", "kind": "功能", "title": "t", "scenario": "S1", "priority": "P0", "impact": "x", "acceptance": ["a"], "manual": [False], "sources": ["初步做法"]}],
        "nonfunc": [],
        "scenarios": [{"code": "S1"}],
        "out_of_scope": [],
        "open_questions": [],
        "review_followup": [],
        "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
    }
    design_gate = bench._gate(run, "DESIGN基线确认", {})
    design_result = await bench.resolve_gate(run, design_gate["gate"]["id"], "reject", {"reason": "重写设计"})
    assert design_gate["gate"]["status"] == "rejected"
    assert design_result["gate"]["kind"] == "DESIGN基线确认"
    plan_gate = bench._gate(run, "PLAN基线确认", {})
    plan_result = await bench.resolve_gate(run, plan_gate["gate"]["id"], "reject", {"reason": "重写计划"})
    assert plan_gate["gate"]["status"] == "rejected"
    assert plan_result["gate"]["kind"] == "PLAN基线确认"
    assert plan_result.get("status") != "executing"


@pytest.mark.asyncio
async def test_discussion_reject_does_not_write_proposal(tmp_path: Path) -> None:
    from app.fixtures.study_room import scripted_m1_queue

    bench, _ = _bench(tmp_path, scripted_m1_queue())
    project = bench.create_project("rej")
    run = bench.create_run(project["id"], IDEA.raw)
    first = await bench.start_idea(run)
    second = await bench.resolve_gate(run, first["gate"]["id"], "approve", {})
    assert second["gate"]["kind"] == "争议清单查看与裁决"
    third = await bench.resolve_gate(run, second["gate"]["id"], "reject", {})
    assert third["gate"]["kind"] == "争议清单查看与裁决"
    assert "proposal" not in run.artifacts


@pytest.mark.asyncio
async def test_concurrent_merge_rollback_keeps_other_task(tmp_path: Path) -> None:
    write_a = {
        "tool_calls": [
            {"name": "write_file", "arguments": {"path": "tests/test_a.py", "content": "def test_a():\n    assert True\n"}}
        ]
    }
    write_b = {
        "tool_calls": [
            {"name": "write_file", "arguments": {"path": "tests/test_b.py", "content": "def test_b():\n    assert True\n"}}
        ]
    }
    provider = _RoutedProvider(
        {
            "T-01": [write_a, {"done": True, "summary": "a"}, {"verdict": "pass", "issues": []}],
            "T-02": [write_b, {"done": True, "summary": "b"}, {"verdict": "pass", "issues": []}],
        }
    )
    bench, _ = _bench(tmp_path, [])
    bench.gateway.provider = provider
    card_a = _card(code="T-01", write_set=["tests/test_a.py"], outputs=["tests/test_a.py"], acceptance=[AcceptanceCheck(cmd=["python", "-m", "pytest", "tests/test_a.py", "-q"], pass_criteria="ok", from_criterion="F1")])
    card_b = _card(code="T-02", write_set=["tests/test_b.py"], outputs=["tests/test_b.py"], acceptance=[AcceptanceCheck(cmd=["python", "-m", "pytest", "tests/test_b.py", "-q"], pass_criteria="ok", from_criterion="F1")])
    project = bench.create_project("race")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[card_a, card_b]).model_dump()
    run.artifacts["spec"] = {"features": [{"code": "F1", "kind": "功能", "title": "t", "scenario": "S1", "priority": "P0", "impact": "x", "acceptance": ["a"], "manual": [False], "sources": ["初步做法"]}], "nonfunc": [], "scenarios": [{"code": "S1"}], "chapters": []}
    bench._materialize_tasks(run)
    run.limits["orchestrator"]["max_repair_rounds"] = 1
    calls = {"n": 0}
    original = bench._run_regression

    async def flaky(target, repo):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "reason": "boom"}
        return await original(target, repo)

    bench._run_regression = flaky  # type: ignore[method-assign]
    await asyncio.gather(bench.execute_task(run, "T-01"), bench.execute_task(run, "T-02"))
    repo = bench.data_dir / "runs" / run.id / "repo"
    states = {code: run.tasks[code]["state"] for code in ("T-01", "T-02")}
    assert "done" in states.values()
    assert any(state != "done" for state in states.values())
    assert (repo / "tests" / "test_b.py").exists() or (repo / "tests" / "test_a.py").exists()
    surviving = "T-02" if run.tasks["T-02"]["state"] == "done" else "T-01"
    lost = "T-01" if surviving == "T-02" else "T-02"
    assert run.tasks[lost]["state"] != "done"
    keep = "tests/test_b.py" if surviving == "T-02" else "tests/test_a.py"
    drop = "tests/test_a.py" if keep.endswith("b.py") else "tests/test_b.py"
    assert (repo / keep).exists()
    assert not (repo / drop).exists() or (repo / drop).read_text(encoding="utf-8") in {"", "\n"}


@pytest.mark.asyncio
async def test_restart_recovers_running_task(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path)
    run = _ready_run(bench, _card())
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    apply_transition(run.tasks["T-01"], "scheduled")
    bench.emit(run, "task.state_changed", "T-01", {"code": "T-01", "event": "scheduled", "from": "ready", "to": "running"})
    run_id = run.id
    bench2, _ = _bench(tmp_path)
    restored = bench2.runs[run_id]
    assert restored.tasks["T-01"]["state"] == "ready"


@pytest.mark.asyncio
async def test_concurrent_token_accounting(tmp_path: Path) -> None:
    write = {
        "tool_calls": [
            {"name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": "def test_feature():\n    assert True\n"}}
        ]
    }
    a = [
        {**write, "tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_a.py", "content": "def test_a():\n    assert True\n"}}]},
        {"done": True, "summary": "a", "tokens_in": 1000, "tokens_out": 0},
        {"verdict": "pass", "issues": []},
    ]
    b = [
        {**write, "tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_b.py", "content": "def test_b():\n    assert True\n"}}]},
        {"done": True, "summary": "b", "tokens_in": 1000, "tokens_out": 0},
        {"verdict": "pass", "issues": []},
    ]
    bench, _ = _bench(tmp_path, [])
    bench.gateway.provider = _RoutedProvider({"T-01": a, "T-02": b})
    card_a = _card(code="T-01", write_set=["tests/test_a.py"], outputs=["tests/test_a.py"], acceptance=[AcceptanceCheck(cmd=["python", "-m", "pytest", "tests/test_a.py", "-q"], pass_criteria="ok", from_criterion="F1")])
    card_b = _card(code="T-02", write_set=["tests/test_b.py"], outputs=["tests/test_b.py"], acceptance=[AcceptanceCheck(cmd=["python", "-m", "pytest", "tests/test_b.py", "-q"], pass_criteria="ok", from_criterion="F1")])
    project = bench.create_project("tok")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["plan"] = TaskGraph(tasks=[card_a, card_b]).model_dump()
    run.artifacts["spec"] = {"features": [{"code": "F1", "kind": "功能", "title": "t", "scenario": "S1", "priority": "P0", "impact": "x", "acceptance": ["a"], "manual": [False], "sources": ["初步做法"]}], "nonfunc": [], "scenarios": [{"code": "S1"}], "chapters": []}
    bench._materialize_tasks(run)
    await asyncio.gather(bench.execute_task(run, "T-01"), bench.execute_task(run, "T-02"))
    assert run.tokens_used == 2000
    assert run.tasks["T-01"]["tokens_used"] == 1000
    assert run.tasks["T-02"]["tokens_used"] == 1000


@pytest.mark.asyncio
async def test_doc_rewrite_loop_then_pass(tmp_path: Path) -> None:
    bad = {"elevator": "e", "chapters": ["电梯演讲"], "features": [], "risks": [], "estimate_total": 0, "capacity": 40}
    good = {
        "elevator": "e",
        "nabcd": {},
        "do": [],
        "dont": [],
        "implementation": "x",
        "features": [{"name": "查看", "sources": ["初步做法"], "points": 3}],
        "risks": [],
        "estimate_total": 3,
        "capacity": 40,
        "chapters": list(PROPOSAL_CHAPTERS),
    }
    bench, _ = _bench(tmp_path, [bad, good])
    project = bench.create_project("rw")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["idea_card"] = {"raw": "x", "approach": "a", "features": ["查看"]}
    run.artifacts["issues"] = []
    doc, errors = await bench._write_checked(
        run,
        "proposal_writer",
        {"idea_card": run.artifacts["idea_card"], "issue_list": []},
        lambda item: check_proposal(item, [], capacity=40),
        ProposalDoc,
        max_rewrites=2,
    )
    assert errors == []
    assert isinstance(doc, ProposalDoc)
    assert doc.features


@pytest.mark.asyncio
async def test_design_reviewers_are_called(tmp_path: Path) -> None:
    design = {
        "chapters": ["概述", "模块", "接口", "数据", "决策", "预案", "附录"],
        "modules": [{"code": "M1", "name": "m", "responsibility": "r", "sources": ["F1"], "provides": ["C1"], "depends_on": [], "data": []}],
        "interfaces": [{"code": "C1", "provider": "M1", "consumers": ["M1"], "inputs": [], "outputs": [], "errors": []}],
        "data": [],
        "decisions": [],
        "contingencies": [],
        "appendix": "",
    }
    bench, provider = _bench(
        tmp_path,
        [
            design,
            {"reviewer": "架构", "dimension": "架构一致性", "score": 4, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]},
            {"reviewer": "质量", "dimension": "实现质量", "score": 4, "opinions": [{"text": "ok", "kind": "验证类", "blocking": False}]},
        ],
    )
    run = _ready_run(bench, _card())
    run.artifacts["issues"] = []
    run.artifacts["spec"] = {
        "features": [{"code": "F1", "kind": "功能", "title": "t", "scenario": "S1", "priority": "P0", "impact": "x", "acceptance": ["a"], "manual": [False], "sources": ["初步做法"]}],
        "nonfunc": [],
        "scenarios": [{"code": "S1"}],
        "out_of_scope": [],
        "open_questions": [],
        "review_followup": [],
        "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
    }
    result = await bench.run_design(run)
    assert result["gate"]["kind"] == "DESIGN基线确认"
    assert len(provider.calls) >= 3
    assert run.artifacts.get("design_reviews")


@pytest.mark.asyncio
async def test_conflict_roundtrip_reruns_origin(tmp_path: Path) -> None:
    combined = "def test_feature():\n    assert True\n# main side\n"
    bench, _ = _bench(
        tmp_path,
        [
            {"tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": "def test_feature():\n    assert True\n"}}]},
            {"done": True, "summary": "origin"},
            {"verdict": "pass", "issues": []},
            {"tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": combined}}]},
            {"done": True, "summary": "conflict"},
            {"verdict": "pass", "issues": []},
            {"tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": combined}}]},
            {"done": True, "summary": "origin-rerun"},
            {"verdict": "pass", "issues": []},
        ],
    )
    run = _ready_run(bench, _card())
    repo = bench.data_dir / "runs" / run.id / "repo"
    init_repo_sync(repo, {"README.md": "x\n", "tests/test_feature.py": "base\n"})
    wt = bench.data_dir / "runs" / run.id / "wt" / "T-01"
    create_worktree(repo, wt, "task/T-01")
    (repo / "tests/test_feature.py").write_text("main side\n", encoding="utf-8")
    commit(repo, "main change")
    first = await bench.execute_task(run, "T-01")
    assert first["kind"] == "合并冲突"
    conflict = next(task for task in run.tasks.values() if task.get("conflict_resolve"))
    resolved = await bench.execute_task(run, conflict["code"])
    assert resolved.get("state") == "done", resolved
    assert run.tasks["T-01"]["state"] == "ready"
    rerun = await bench.execute_task(run, "T-01")
    assert rerun.get("state") == "done", rerun
    text = (repo / "tests/test_feature.py").read_text(encoding="utf-8")
    assert "test_feature" in text
    assert "main side" in text


@pytest.mark.asyncio
async def test_idea_to_acceptance_exports_release(tmp_path: Path) -> None:
    bench, _ = _bench(tmp_path, scripted_full_queue())
    project = bench.create_project("full")
    run = bench.create_run(project["id"], IDEA.raw)
    r0 = await bench.start_idea(run)
    r1 = await bench.resolve_gate(run, r0["gate"]["id"], "approve", {})
    r2 = await bench.resolve_gate(run, r1["gate"]["id"], "approve", {})
    r3 = await bench.resolve_gate(run, r2["gate"]["id"], "approve", {})
    assert r3["gate"]["kind"] == "SPEC基线确认"
    r4 = await bench.resolve_gate(run, r3["gate"]["id"], "approve", {})
    assert r4["gate"]["kind"] == "DESIGN基线确认"
    r5 = await bench.resolve_gate(run, r4["gate"]["id"], "approve", {})
    assert r5["gate"]["kind"] == "PLAN基线确认"
    r6 = await bench.resolve_gate(run, r5["gate"]["id"], "approve", {})
    assert r6["status"] == "executing"
    await bench.schedule_once(run)
    assert run.tasks["T-01"]["state"] == "done"
    assert run.tasks["T-02"]["state"] == "done"
    accepted = await bench.accept(run)
    assert accepted["gate"]["kind"] == "验收确认"
    run.engine.current = "8"
    done = await bench.resolve_gate(run, accepted["gate"]["id"], "approve", {})
    assert done["status"] == "done"
    release = Path(run.artifacts["release_dir"])
    assert (release / "code").exists()
    assert (release / "trace.json").exists()
    assert run.artifacts.get("build_tag") == "build-1.0"


@pytest.mark.asyncio
async def test_schedule_loop_completes_ready_task(tmp_path: Path) -> None:
    queue = [
        {"tool_calls": [{"name": "write_file", "arguments": {"path": "tests/test_feature.py", "content": "def test_feature():\n    assert True\n"}}]},
        {"done": True, "summary": "ok"},
        {"verdict": "pass", "issues": []},
    ]
    bench, _ = _bench(tmp_path, queue)
    run = _ready_run(bench, _card())
    bench.schedule_interval = 0.05
    bench.start_loop()
    for _ in range(40):
        if run.tasks["T-01"]["state"] == "done":
            break
        await asyncio.sleep(0.05)
    await bench.stop_loop()
    assert run.tasks["T-01"]["state"] == "done"


def test_worktree_remove_allows_recreate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_sync(repo, {"README.md": "x\n"})
    wt = tmp_path / "wt"
    create_worktree(repo, wt, "task/T-01")
    remove_worktree(repo, wt)
    assert not wt.exists()
    create_worktree(repo, wt, "task/T-01")
    assert wt.exists()
