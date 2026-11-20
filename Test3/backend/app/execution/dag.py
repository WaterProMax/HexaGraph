"""DAG ordering for granted execution (P5).

The task graph itself already lives in ``TaskCard.depends_on``.  These helpers
are pure: they answer "which tasks may start now" from edges plus a state map so
that the scheduler and the HTTP layer share one definition of "predecessor
succeeded".

Task states come from ``app.orchestrator.states``: success is ``done``; the
contract also names ``succeeded`` as an alias, so both are accepted here.  No
new task state is introduced for "success".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SUCCESS_STATES = frozenset({"done", "succeeded"})
SCHEDULABLE_STATES = frozenset({"pending", "ready"})


def ready_tasks(
    edges: list[tuple[str, str]],
    statuses: dict[str, str],
) -> list[str]:
    """Return successors whose predecessors all succeeded and that may run."""
    predecessors: dict[str, list[str]] = {}
    order: list[str] = []
    for pred, succ in edges:
        if succ not in order:
            order.append(succ)
        predecessors.setdefault(succ, []).append(pred)
    ready: list[str] = []
    for code in order:
        if statuses.get(code, "pending") not in SCHEDULABLE_STATES:
            continue
        if all(statuses.get(pred, "pending") in SUCCESS_STATES for pred in predecessors[code]):
            ready.append(code)
    return ready


def dag_blocked_tasks(
    edges: list[tuple[str, str]],
    statuses: dict[str, str],
    requested: set[str] | list[str],
) -> list[str]:
    """Return requested tasks whose predecessor has not succeeded yet."""
    predecessors: dict[str, list[str]] = {}
    for pred, succ in edges:
        predecessors.setdefault(succ, []).append(pred)
    blocked = [
        code
        for code in requested
        if any(statuses.get(pred, "pending") not in SUCCESS_STATES for pred in predecessors.get(code, []))
    ]
    return sorted(blocked)


def edges_from_tasks(tasks: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Build ``(predecessor, successor)`` edges from materialized run tasks."""
    edges: list[tuple[str, str]] = []
    for code, task in tasks.items():
        card = (task or {}).get("card") or {}
        for dep in card.get("depends_on") or []:
            edges.append((str(dep), str(code)))
    return edges


__all__ = [
    "SCHEDULABLE_STATES",
    "SUCCESS_STATES",
    "dag_blocked_tasks",
    "edges_from_tasks",
    "ready_tasks",
]