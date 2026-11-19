from __future__ import annotations

from typing import Any

from app.orchestrator.states import can_transition
from app.orchestrator.transition import apply_transition
from app.workspace.gitops import is_merged


def recover_tasks(tasks: dict[str, dict[str, Any]], repo, branch_for) -> list[dict[str, Any]]:
    """重启后把中断的任务恢复成可继续调度的状态。

    返回每一次真实发生的状态迁移，供调用方补写事件（恢复动作必须可追踪）。
    每个元素形如 ``{"code", "event", "from", "to", "reason"}``。
    """
    actions: list[dict[str, Any]] = []
    for code, task in tasks.items():
        state = task["state"]
        if state not in {"running", "verifying"}:
            continue
        if is_merged(repo, branch_for(code)):
            if state == "running" and can_transition(state, "code_finished"):
                apply_transition(task, "code_finished", reason="recover-merged")
                actions.append(
                    {"code": code, "event": "code_finished", "from": state, "to": task["state"], "reason": "recover-merged"}
                )
            if task["state"] == "verifying" and can_transition(task["state"], "accepted"):
                apply_transition(task, "accepted", reason="recover-merged")
                actions.append(
                    {"code": code, "event": "accepted", "from": "verifying", "to": task["state"], "reason": "recover-merged"}
                )
        else:
            apply_transition(task, "interrupted", reason="recover")
            actions.append(
                {"code": code, "event": "interrupted", "from": state, "to": task["state"], "reason": "recover"}
            )
    return actions
