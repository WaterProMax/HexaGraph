from __future__ import annotations

import json
from pathlib import Path

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.services.runtime import Workbench
from app.settings import ROOT, load_models, load_roles


def test_import_study_room_feedback(tmp_path: Path) -> None:
    bench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    project = bench.create_project("fb")
    run = bench.create_run(project["id"], "idea")
    run.artifacts["issues"] = [
        {"code": "I-03", "text": "上报的人够不够", "status": "待定", "destination": "风险与待定"},
        {"code": "I-07", "text": "第一版只覆盖一栋楼", "status": "采纳", "destination": "本版不做"},
    ]
    rows = json.loads((ROOT / "examples/study-room/feedback/batch1.json").read_text(encoding="utf-8"))
    bench.import_feedback(run, rows, "test-key")
    assert len(run.raw_feedback) >= 17
    assert any(i.get("red_line") for i in run.feedback)
    assert any(i.get("route") == "继续观察" or i.get("category") == "新需求" for i in run.feedback)
    assert "sk-" not in json.dumps(run.raw_feedback)
