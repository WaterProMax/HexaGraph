"""Pure grant scope policy (contracts.md C.3.2).

``run.revision`` / ``task.revision`` are optimistic-lock counters and are
deliberately not inputs here: a gate or control bump must never invalidate a
grant whose approved baseline hashes and task scope are unchanged.
"""

from __future__ import annotations

from typing import Protocol


class GrantLike(Protocol):
    task_codes: list[str]
    approved_baseline_hashes: dict[str, str]
    status: str


def grant_stale_reason(
    grant: GrantLike,
    *,
    approved_baseline_hashes: dict[str, str],
    requested_task_codes: set[str],
) -> str | None:
    """Return ``None`` when the request may run; otherwise a machine category.

    Subsets of ``grant.task_codes`` are legal: a human approved the grant once
    and continuous execution inside that scope must not ask for per-task
    approval again.
    """
    status = str(getattr(grant, "status", "active") or "active")
    if status in {"revoked", "consumed"}:
        return f"grant_{status}"
    if len(requested_task_codes) == 0:
        return "empty_request"
    extra = set(requested_task_codes) - set(grant.task_codes)
    if extra:
        return "scope_mismatch"
    for key, expected in grant.approved_baseline_hashes.items():
        if approved_baseline_hashes.get(key) != expected:
            return f"baseline_changed:{key}"
    return None


__all__ = ["GrantLike", "grant_stale_reason"]