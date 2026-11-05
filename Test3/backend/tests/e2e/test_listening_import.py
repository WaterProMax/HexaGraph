from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import ROOT, get_settings, load_models, load_roles


@pytest.mark.asyncio
async def test_import_study_room_feedback(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    project = bench.create_project("fb")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["issues"] = [
        {"code": "I-03", "text": "上报的人够不够", "status": "待定", "destination": "风险与待定"},
        {"code": "I-07", "text": "第一版只覆盖一栋楼", "status": "采纳", "destination": "本版不做"},
    ]
    provider.queue = [
        {
            "items": [
                {"category": "体验问题", "summary": "灰色数据太多", "quotes": [1], "count": 1, "basis": "归纳", "linked_issue": "I-03"},
                {"category": "新需求", "summary": "空位预测", "quotes": [10], "count": 1, "basis": "归纳", "new_direction": False},
                {"category": "缺陷", "summary": "上报看到学号", "quotes": [12], "count": 1, "basis": "用户原话", "red_line": True},
            ]
        },
        {"dimension": "价值", "score": 3, "red_line": False, "reason": "体验"},
        {"dimension": "成本", "score": 3, "red_line": False, "reason": "小"},
        {"dimension": "风险", "score": 5, "red_line": True, "reason": "隐私"},
    ]
    rows = json.loads((ROOT / "examples/study-room/feedback/batch1.json").read_text(encoding="utf-8"))
    await bench.import_feedback(run, rows, "test-key")
    assert len(run.raw_feedback) >= 17
    assert any(i.get("red_line") for i in run.feedback)
    assert any(i.get("route") == "继续观察" or i.get("category") == "新需求" for i in run.feedback)
    assert "sk-" not in json.dumps(run.raw_feedback)


@pytest.mark.asyncio
async def test_listening_without_scripted_does_not_hardcode_study_room(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "test3_scripted_fixture", "")
    provider = ScriptedProvider()
    bench = Workbench(Gateway(load_models(), provider), RoleRegistry(load_roles()), tmp_path)
    project = bench.create_project("fb")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["issues"] = [
        {"code": "I-03", "text": "上报的人够不够", "status": "待定"},
        {"code": "I-04", "text": "比微信群好在哪", "status": "待定"},
    ]
    rows = [
        {"author": "x", "text": "哈哈 测试一下 学号 隐私 别的楼 灰色 预测"},
    ]
    await bench.import_feedback(run, rows, "test-key")
    assert run.feedback
    for item in run.feedback:
        assert item.get("category") == ""
        assert item.get("linked_issue") != "I-03"
        assert item.get("linked_issue") != "I-04"
        assert item.get("category") != "缺陷"
        assert not item.get("red_line")
