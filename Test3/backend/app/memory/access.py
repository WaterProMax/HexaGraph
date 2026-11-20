"""Visibility rules for memory records.

Project membership is read from the P2 ``project_memberships`` table; there is
no second membership system here.  Removing a member deletes only that join row,
never the member's private memory history.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.store import MemoryStore
from app.schemas.memory import MemoryCreate, MemoryRecord
from app.storage.models import ProjectMembershipRow


class MemoryForbidden(Exception):
    pass


async def is_project_member(session: AsyncSession, project_id: str, bot_id: str) -> bool:
    return await session.get(ProjectMembershipRow, (project_id, bot_id)) is not None


def _allowed(actor_bot_id: str, record: MemoryCreate | MemoryRecord, *, is_project_member: bool) -> bool:
    if record.visibility in {"private", "run"}:
        return actor_bot_id == record.owner_bot_id
    if record.visibility == "project":
        return bool(is_project_member)
    return False


def assert_can_read(
    actor_bot_id: str,
    rec: MemoryRecord,
    *,
    is_project_member: bool,
) -> None:
    if not _allowed(actor_bot_id, rec, is_project_member=is_project_member):
        raise MemoryForbidden(f"bot {actor_bot_id} cannot read memory {rec.mem_id}")


def assert_can_write(
    actor_bot_id: str,
    rec: MemoryCreate | MemoryRecord,
    *,
    is_project_member: bool,
) -> None:
    if not _allowed(actor_bot_id, rec, is_project_member=is_project_member):
        raise MemoryForbidden(f"bot {actor_bot_id} cannot write memory")


class MemoryAccessService:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def _member(self, project_id: str | None, bot_id: str) -> bool:
        if not project_id:
            return False
        return await is_project_member(self.store.session, project_id, bot_id)

    async def create(self, actor_bot_id: str, data: MemoryCreate) -> MemoryRecord:
        member = await self._member(data.project_id, actor_bot_id)
        assert_can_write(actor_bot_id, data, is_project_member=member)
        return await self.store.create(data)

    async def get(
        self, actor_bot_id: str, mem_id: str, version: int | None = None
    ) -> MemoryRecord:
        record = await self.store.get(mem_id, version)
        member = await self._member(record.project_id, actor_bot_id)
        assert_can_read(actor_bot_id, record, is_project_member=member)
        return record

    async def list_visible(
        self,
        actor_bot_id: str,
        *,
        owner_bot_id: str | None = None,
        project_id: str | None = None,
        visibility: str | None = None,
    ) -> list[MemoryRecord]:
        records = await self.store.list(
            owner_bot_id=owner_bot_id,
            project_id=project_id,
            visibility=visibility,
            latest_only=True,
        )
        memberships: dict[str, bool] = {}
        visible: list[MemoryRecord] = []
        for record in records:
            member = False
            if record.visibility == "project" and record.project_id:
                if record.project_id not in memberships:
                    memberships[record.project_id] = await self._member(
                        record.project_id, actor_bot_id
                    )
                member = memberships[record.project_id]
            if _allowed(actor_bot_id, record, is_project_member=member):
                visible.append(record)
        return visible


__all__ = [
    "MemoryAccessService",
    "MemoryForbidden",
    "assert_can_read",
    "assert_can_write",
    "is_project_member",
]