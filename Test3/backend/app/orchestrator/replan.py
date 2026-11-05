from __future__ import annotations

from typing import Any

from app.docs.checks import check_task_graph
from app.schemas.docs import DesignDoc, SpecDoc, TaskGraph


def propose_replan(graph: TaskGraph, spec: SpecDoc, design: DesignDoc, capacity: int) -> dict[str, Any]:
    errors = check_task_graph(graph, spec, design, capacity)
    return {"ok": not errors, "errors": errors, "graph": graph}
