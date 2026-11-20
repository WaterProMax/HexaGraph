"""Versioned skill definitions.

``(skill_id, version)`` is immutable once written.  An insert that collides on
the composite primary key raises ``SkillVersionExists`` and leaves the stored
payload untouched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.skill_definition import SkillCreate, SkillDefinition
from app.storage.models import SkillDefinitionRow


class SkillNotFound(Exception):
    pass


class SkillVersionExists(Exception):
    pass


class SkillRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: SkillCreate) -> SkillDefinition:
        row = SkillDefinitionRow(
            skill_id=data.skill_id,
            version=data.version,
            payload=data.model_dump(),
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise SkillVersionExists(f"{data.skill_id}@{data.version}") from exc
        return SkillDefinition.model_validate(row.payload)

    async def list_all(self) -> list[SkillDefinition]:
        stmt = select(SkillDefinitionRow).order_by(
            SkillDefinitionRow.skill_id, SkillDefinitionRow.version
        )
        rows = list((await self.session.execute(stmt)).scalars())
        return [SkillDefinition.model_validate(row.payload) for row in rows]

    async def list_versions(self, skill_id: str) -> list[SkillDefinition]:
        stmt = (
            select(SkillDefinitionRow)
            .where(SkillDefinitionRow.skill_id == skill_id)
            .order_by(SkillDefinitionRow.version)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        if not rows:
            raise SkillNotFound(skill_id)
        return [SkillDefinition.model_validate(row.payload) for row in rows]


__all__ = ["SkillNotFound", "SkillRegistry", "SkillVersionExists"]