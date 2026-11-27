"""Human promotion and supersede for project memories.

Only project-scoped memories can be published.  Membership is checked against
the P2 ``project_memberships`` table via ``app.memory.access``; no second
membership store is introduced.
"""

from __future__ import annotations

from app.memory.access import MemoryForbidden, is_project_member
from app.memory.store import MemoryStore, MemoryVersionConflict
from app.schemas.memory import MemoryRecord, MemorySource


class VisibilityNotProject(Exception):
    pass


class MemoryPromotionService:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def _project_record(self, mem_id: str, expected_version: int) -> MemoryRecord:
        latest = await self.store.get(mem_id)
        if latest.version != expected_version:
            raise MemoryVersionConflict(
                f"expected version {expected_version}, latest is {latest.version}"
            )
        if latest.visibility != "project":
            raise VisibilityNotProject(
                f"memory {mem_id} is {latest.visibility}, not project"
            )
        return latest

    async def _require_member(self, record: MemoryRecord, actor: str) -> None:
        if not record.project_id or not await is_project_member(
            self.store.session, record.project_id, actor
        ):
            raise MemoryForbidden(
                f"bot {actor} is not a member of project {record.project_id}"
            )

    async def publish(
        self, mem_id: str, expected_version: int, *, actor: str
    ) -> MemoryRecord:
        record = await self._project_record(mem_id, expected_version)
        await self._require_member(record, actor)
        return await self.store.publish_version(mem_id, expected_version, actor=actor)

    async def supersede(
        self,
        mem_id: str,
        expected_version: int,
        *,
        body: dict,
        sources: list[MemorySource],
        actor: str,
    ) -> MemoryRecord:
        record = await self._project_record(mem_id, expected_version)
        await self._require_member(record, actor)
        return await self.store.supersede_version(
            mem_id,
            expected_version,
            body=body,
            sources=sources,
            actor=actor,
        )


__all__ = ["MemoryPromotionService", "VisibilityNotProject"]