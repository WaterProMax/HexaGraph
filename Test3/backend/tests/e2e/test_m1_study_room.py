from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.fixtures.study_room import IDEA, scripted_m1_queue
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import load_models, load_roles


@pytest.mark.asyncio
async def test_m1_study_room_scripted(tmp_path: Path) -> None:
    models = load_models()
    roles = load_roles()
    provider = ScriptedProvider(scripted_m1_queue())
    gw = Gateway(models, provider)
    bench = Workbench(gw, RoleRegistry(roles), tmp_path)
    project = bench.create_project("study-room")
    run = bench.create_run(project["id"], IDEA.raw)
    r0 = await bench.start_idea(run)
    assert r0["gate"]["kind"] == "初步做法确认"
    r1 = await bench.resolve_gate(run, r0["gate"]["id"], "approve", {})
    assert r1["gate"]["kind"] == "争议清单查看与裁决"
    issues = {i["code"]: i for i in run.artifacts["issues"]}
    assert issues["I-01"]["status"] == "采纳"
    assert issues["I-03"]["status"] == "待定"
    assert issues["I-04"]["status"] == "待定"
    assert issues["I-07"]["status"] == "采纳"
    r2 = await bench.resolve_gate(run, r1["gate"]["id"], "approve", {})
    assert r2["gate"]["kind"] == "评审确认"
    r3 = await bench.resolve_gate(run, r2["gate"]["id"], "approve", {})
    spec = run.artifacts["spec"]
    titles = " ".join(f["title"] for f in spec["features"])
    assert "门禁" not in titles
    open_codes = {q["code"] for q in spec["open_questions"]}
    assert {"I-03", "I-04"} <= open_codes
    sources = [s for f in spec["features"] for s in f["sources"]]
    assert "I-02" in sources
    assert r3["gate"]["kind"] == "SPEC基线确认"
    from app.fixtures.study_room import QUESTIONS

    first_round = provider.calls[2:7]
    roles = ("产品经理", "用户代表", "付费方代表", "开发", "测试")
    texts = {role: [q.text for q in QUESTIONS if q.role == role] for role in roles}
    assert len(first_round) == 5
    for call, role in zip(first_round, roles, strict=True):
        blob = str(call["messages"])
        for other, qs in texts.items():
            if other == role:
                continue
            for text in qs:
                assert text not in blob, f"{role} saw {other} question: {text}"
    assert any(e.get("payload", {}).get("rule") for e in run.events if e["kind"] == "discussion.message")
