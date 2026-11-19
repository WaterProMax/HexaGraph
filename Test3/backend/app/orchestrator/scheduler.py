from __future__ import annotations

from typing import Iterable

from app.docs.checks import critical_path
from app.schemas.docs import TaskCard, TaskGraph

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def conflicts_with_running(task: TaskCard, running: Iterable[TaskCard]) -> bool:
    for other in running:
        if _overlap(task.write_set, other.write_set):
            return True
    return False


def critical_remaining(graph: TaskGraph, states: dict[str, str]) -> dict[str, int]:
    tasks = {t.code: t for t in graph.tasks}
    memo: dict[str, int] = {}

    def walk(code: str) -> int:
        if code in memo:
            return memo[code]
        if states.get(code) in {"done", "skipped", "cancelled"}:
            memo[code] = 0
            return 0
        task = tasks[code]
        downs = [o.code for o in graph.tasks if code in o.depends_on]
        memo[code] = task.points + max((walk(d) for d in downs), default=0)
        return memo[code]

    for code in tasks:
        walk(code)
    return memo


def select_tasks(
    graph: TaskGraph,
    states: dict[str, str],
    *,
    run_paused: bool = False,
    paused: set[str] | None = None,
    locked: set[str] | None = None,
    running: list[TaskCard] | None = None,
    concurrency: int = 6,
    budget_exhausted: set[str] | None = None,
    skip_continue: set[str] | None = None,
) -> list[TaskCard]:
    if run_paused:
        return []
    paused = paused or set()
    locked = locked or set()
    running = running or []
    budget_exhausted = budget_exhausted or set()
    skip_continue = skip_continue or set()
    remaining = critical_remaining(graph, states)
    slots = max(0, concurrency - len(running))
    if slots == 0:
        return []
    ready: list[TaskCard] = []
    for task in graph.tasks:
        state = states.get(task.code, "pending")
        if state != "ready":
            continue
        if task.code in paused or task.code in locked:
            continue
        if not _deps_done(task, states, skip_continue):
            continue
        if conflicts_with_running(task, running):
            continue
        if task.code in budget_exhausted:
            continue
        ready.append(task)
    ready.sort(
        key=lambda t: (
            -remaining.get(t.code, 0),
            PRIORITY_RANK[t.priority],
            t.points,
            t.code,
        )
    )
    return ready[:slots]


def _deps_done(task: TaskCard, states: dict[str, str], skip_continue: set[str]) -> bool:
    for dep in task.depends_on:
        st = states.get(dep, "pending")
        if st == "done":
            continue
        if st == "skipped" and dep in skip_continue:
            continue
        return False
    return True


def _overlap(left: list[str], right: list[str]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
                return True
    return False


def path_highlight(graph: TaskGraph) -> list[str]:
    return critical_path(graph)


def preview_schedule(graph: TaskGraph, concurrency: int) -> dict:
    """Estimate a schedule in effort points using the same selection order as the runner."""
    states = {task.code: "pending" for task in graph.tasks}
    active: list[tuple[int, TaskCard]] = []
    rows: list[dict] = []
    now = 0
    while len(rows) < len(graph.tasks) or active:
        for task in graph.tasks:
            if states[task.code] == "pending" and _deps_done(task, states, set()):
                states[task.code] = "ready"
        running = [task for _, task in active]
        for task in select_tasks(graph, states, concurrency=concurrency, running=running):
            if conflicts_with_running(task, running):
                continue
            end = now + task.points
            states[task.code] = "running"
            active.append((end, task))
            running.append(task)
            rows.append({"code": task.code, "start": now, "end": end})
        if not active:
            break
        now = min(end for end, _ in active)
        for end, task in active:
            if end == now:
                states[task.code] = "done"
        active = [(end, task) for end, task in active if end > now]
    return {"rows": rows, "span": now, "concurrency": concurrency, "critical": critical_path(graph)}
