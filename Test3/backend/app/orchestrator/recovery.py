from __future__ import annotations

from typing import Any

from app.workspace.gitops import is_merged


def recover_tasks(tasks: dict[str, dict[str, Any]], repo, branch_for) -> list[str]:
    events = []
    for code, task in tasks.items():
        if task["state"] in {"running", "verifying"}:
            if is_merged(repo, branch_for(code)):
                task["state"] = "done"
                events.append(f"{code}:merged-done")
            else:
                task["state"] = "ready"
                events.append(f"{code}:interrupted")
    return events
