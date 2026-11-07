from __future__ import annotations

from typing import Any

from app.orchestrator.states import can_transition
from app.orchestrator.transition import apply_transition
from app.workspace.gitops import is_merged


def recover_tasks(tasks: dict[str, dict[str, Any]], repo, branch_for) -> list[str]:
    events = []
    for code, task in tasks.items():
        if task["state"] not in {"running", "verifying"}:
            continue
        if is_merged(repo, branch_for(code)):
            if task["state"] == "running" and can_transition(task["state"], "code_finished"):
                apply_transition(task, "code_finished", reason="recover-merged")
            if task["state"] == "verifying" and can_transition(task["state"], "accepted"):
                apply_transition(task, "accepted", reason="recover-merged")
            events.append(f"{code}:merged-done")
        else:
            apply_transition(task, "interrupted", reason="recover")
            events.append(f"{code}:interrupted")
    return events
