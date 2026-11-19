"""SQLite repository for ExecutionGrant.

``add`` participates in the caller's SQLAlchemy session/transaction: a caller
rollback leaves no grant behind. The table is the single write authority for
this new domain; legacy runs keep their JSONL/snapshot storage.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.execution_grant import ExecutionGrant, GrantStatus
from app.storage.models import ExecutionGrantRow


def _to_grant(row: ExecutionGrantRow) -> ExecutionGrant:
    grant = ExecutionGrant.model_validate_json(row.payload)
    # The indexed status column is the queryable copy; keep payload and column
    # consistent if an older row is read after a status update.
    if grant.status != row.status:
        grant = grant.model_copy(update={"status": row.status})
    return grant


class GrantRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, grant: ExecutionGrant) -> None:
        row = ExecutionGrantRow(
            grant_id=grant.grant_id,
            run_id=grant.run_id,
            status=grant.status,
            payload=grant.model_dump_json(),
        )
        self.session.add(row)
        await self.session.flush()

    async def list_for_run(self, run_id: str) -> list[ExecutionGrant]:
        stmt = select(ExecutionGrantRow).where(ExecutionGrantRow.run_id == run_id)
        rows = list((await self.session.execute(stmt)).scalars())
        grants = [_to_grant(row) for row in rows]
        return sorted(grants, key=lambda item: (item.created_at, item.grant_id))

    async def get(self, grant_id: str) -> ExecutionGrant | None:
        row = await self.session.get(ExecutionGrantRow, grant_id)
        return _to_grant(row) if row is not None else None

    async def latest_for_run(self, run_id: str) -> ExecutionGrant | None:
        grants = await self.list_for_run(run_id)
        return grants[-1] if grants else None

    async def update_status(self, grant_id: str, status: GrantStatus) -> ExecutionGrant:
        row = await self.session.get(ExecutionGrantRow, grant_id)
        if row is None:
            raise KeyError(f"grant_not_found: {grant_id}")
        grant = ExecutionGrant.model_validate_json(row.payload).model_copy(update={"status": status})
        row.status = status
        row.payload = grant.model_dump_json()
        await self.session.flush()
        return grant


__all__ = ["GrantRepo"]