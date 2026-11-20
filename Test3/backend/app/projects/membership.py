"""Project membership is a many-to-many join of projects and bots.

``project`` is the in-memory Workbench identity for now, so this table has no
foreign key to it.  ``bot_id`` does reference ``bots``; removing a membership
only deletes this join row and never the bot or its pin history.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bots.registry import BotArchived, BotNotFound
from app.schemas.bot import BotInstance
from app.storage.models import BotRow, ProjectMembershipRow


class ProjectMembership(BaseModel):
    project_id: str
    bot_id: str
    role_in_project: str
    is_leader: bool = False


class MembershipCreate(BaseModel):
    bot_id: str
    role_in_project: str
    is_leader: bool = False


class ProjectNotFound(Exception):
    pass


class MembershipExists(Exception):
    pass


class LeaderAlreadySet(Exception):
    pass


class MembershipNotFound(Exception):
    pass


def _is_locked(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _integrity_error(exc: IntegrityError) -> Exception:
    message = str(exc)
    if "uq_project_one_leader" in message:
        return LeaderAlreadySet("project already has a leader")
    if "project_memberships.bot_id" in message:
        return MembershipExists("bot is already a member of the project")
    if "project_memberships.project_id" in message:
        return LeaderAlreadySet("project already has a leader")
    return MembershipExists("membership conflict")


class MembershipService:
    def __init__(self, session: AsyncSession, project_exists=None) -> None:
        self.session = session
        self.project_exists = project_exists

    def _require_project(self, project_id: str) -> None:
        if self.project_exists is not None and not self.project_exists(project_id):
            raise ProjectNotFound(project_id)

    async def add(self, project_id: str, data: MembershipCreate) -> ProjectMembership:
        return await self._retry(lambda: self._add_once(project_id, data))

    async def _add_once(self, project_id: str, data: MembershipCreate) -> ProjectMembership:
        self._require_project(project_id)
        # Take SQLite's write lock before the reads so concurrent leader claims
        # are serialized; an UPDATE matching zero rows still starts a write tx.
        await self.session.execute(
            text(
                "UPDATE project_memberships SET is_leader = is_leader "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        bot_row = await self.session.get(BotRow, data.bot_id)
        if bot_row is None:
            raise BotNotFound(data.bot_id)
        if BotInstance.model_validate(bot_row.payload).status == "archived":
            raise BotArchived(data.bot_id)
        if await self.session.get(ProjectMembershipRow, (project_id, data.bot_id)) is not None:
            raise MembershipExists(data.bot_id)
        if data.is_leader:
            stmt = select(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == project_id,
                ProjectMembershipRow.is_leader == 1,
            )
            if (await self.session.execute(stmt)).scalars().first() is not None:
                raise LeaderAlreadySet(project_id)
        membership = ProjectMembership(
            project_id=project_id,
            bot_id=data.bot_id,
            role_in_project=data.role_in_project,
            is_leader=data.is_leader,
        )
        self.session.add(
            ProjectMembershipRow(
                project_id=project_id,
                bot_id=data.bot_id,
                role_in_project=data.role_in_project,
                is_leader=1 if data.is_leader else 0,
                payload=membership.model_dump(),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc
        return membership

    async def list(self, project_id: str) -> list[ProjectMembership]:
        self._require_project(project_id)
        stmt = (
            select(ProjectMembershipRow)
            .where(ProjectMembershipRow.project_id == project_id)
            .order_by(ProjectMembershipRow.bot_id)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        return [ProjectMembership.model_validate(row.payload) for row in rows]

    async def remove(self, project_id: str, bot_id: str) -> None:
        await self._retry(lambda: self._remove_once(project_id, bot_id))

    async def _remove_once(self, project_id: str, bot_id: str) -> None:
        result = await self.session.execute(
            delete(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == project_id,
                ProjectMembershipRow.bot_id == bot_id,
            )
        )
        if result.rowcount == 0:
            raise MembershipNotFound(f"{project_id}/{bot_id}")

    async def _retry(self, operation):
        for attempt in range(4):
            try:
                return await operation()
            except OperationalError as exc:
                await self.session.rollback()
                if not _is_locked(exc) or attempt == 3:
                    raise
                await asyncio.sleep(0.02 * (attempt + 1))


__all__ = [
    "LeaderAlreadySet",
    "MembershipCreate",
    "MembershipExists",
    "MembershipNotFound",
    "MembershipService",
    "ProjectMembership",
    "ProjectNotFound",
]