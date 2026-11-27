"""Grant refresh after a human gate changes the approved baseline.

Only a real ``baseline_changed:<key>`` makes an active grant stale. A gate or
control that only increments ``run.revision`` must leave the grant active
(contracts C.3.1 / C.3.2).
"""

from __future__ import annotations

from app.execution.grant_policy import grant_stale_reason
from app.schemas.execution_grant import ExecutionGrant


def refresh_grant_status(
    grant: ExecutionGrant,
    *,
    approved_baseline_hashes: dict[str, str],
) -> ExecutionGrant:
    reason = grant_stale_reason(
        grant,
        approved_baseline_hashes=approved_baseline_hashes,
        requested_task_codes=set(grant.task_codes),
    )
    if reason is not None and reason.startswith("baseline_changed:"):
        return grant.model_copy(update={"status": "stale"})
    return grant


__all__ = ["refresh_grant_status"]