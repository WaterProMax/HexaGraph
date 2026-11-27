from __future__ import annotations

from app.execution.dag import (
    SUCCESS_STATES,
    dag_blocked_tasks,
    edges_from_tasks,
    ready_tasks,
)


def test_ready_task_after_predecessor_done() -> None:
    edges = [("T-01", "T-02")]
    assert ready_tasks(edges, {"T-01": "done", "T-02": "pending"}) == ["T-02"]


def test_succeeded_is_an_alias_for_done() -> None:
    edges = [("T-01", "T-02")]
    assert "succeeded" in SUCCESS_STATES
    assert ready_tasks(edges, {"T-01": "succeeded", "T-02": "ready"}) == ["T-02"]


def test_predecessor_not_successful_blocks_successor() -> None:
    edges = [("T-01", "T-02")]
    assert ready_tasks(edges, {"T-01": "pending", "T-02": "pending"}) == []
    assert dag_blocked_tasks(edges, {"T-01": "pending", "T-02": "pending"}, {"T-02"}) == ["T-02"]


def test_failed_predecessor_blocks_successor() -> None:
    edges = [("T-01", "T-02")]
    assert "failed" not in SUCCESS_STATES
    assert dag_blocked_tasks(edges, {"T-01": "failed", "T-02": "ready"}, {"T-02"}) == ["T-02"]


def test_ready_task_requires_pending_or_ready_state() -> None:
    edges = [("T-01", "T-02")]
    assert ready_tasks(edges, {"T-01": "done", "T-02": "running"}) == []


def test_multiple_predecessors_must_all_succeed() -> None:
    edges = [("T-01", "T-03"), ("T-02", "T-03")]
    statuses = {"T-01": "done", "T-02": "pending", "T-03": "pending"}
    assert ready_tasks(edges, statuses) == []
    statuses["T-02"] = "done"
    assert ready_tasks(edges, statuses) == ["T-03"]


def test_edges_from_tasks_uses_card_depends_on() -> None:
    tasks = {
        "T-01": {"card": {"depends_on": []}},
        "T-02": {"card": {"depends_on": ["T-01"]}},
    }
    assert edges_from_tasks(tasks) == [("T-01", "T-02")]


def test_dag_blocked_tasks_returns_sorted_unique() -> None:
    edges = [("T-01", "T-02"), ("T-01", "T-03")]
    statuses = {"T-01": "running", "T-02": "pending", "T-03": "pending"}
    assert dag_blocked_tasks(edges, statuses, {"T-03", "T-02"}) == ["T-02", "T-03"]