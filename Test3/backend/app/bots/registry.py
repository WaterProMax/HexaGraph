"""SQLite authority for bot instances and append-only pin revisions.

The bot row carries the current payload.  Every change to ``model``,
``provider_ref`` or ``skill_bindings`` appends a new ``bot_pin_revisions`` row
with ``revision = max(revision) + 1`` computed atomically inside SQLite, so
concurrent writers cannot reuse a revision number.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.bot import BotCreate, BotInstance, BotPatch, BotSkillBinding
from app.storage.models import BotPinRevisionRow, BotRow

_PIN_FIELDS = ("model", "provider_ref", "skill_bindings")


class BotNotFound(Exception):
    pass


class BotNameConflict(Exception):
    pass


class BotArchived(Exception):
    pass


class BotAlreadyArchived(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _binding_values(bindings: list[BotSkillBinding] | list[dict[str, Any]] | None) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for binding in bindings or []:
        if isinstance(binding, BotSkillBinding):
            values.append(binding.model_dump())
        else:
            values.append({"skill_id": binding["skill_id"], "pinned_version": binding["pinned_version"]})
    return values


def _pin_dict(row: BotPinRevisionRow) -> dict[str, Any]:
    return {
        "revision": row.revision,
        "model": row.model,
        "provider_ref": row.provider_ref,
        "skill_bindings": list(row.skill_bindings or []),
    }


def _is_locked(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


class BotRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: BotCreate) -> BotInstance:
        bot_id = str(uuid.uuid4())
        instance = BotInstance(bot_id=bot_id, status="active", **data.model_dump())
        row = BotRow(
            bot_id=bot_id,
            display_name=instance.display_name,
            status=instance.status,
            payload=instance.model_dump(),
            created_at=_now(),
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise BotNameConflict(instance.display_name) from exc
        await self._append_pin(
            bot_id,
            instance.model,
            instance.provider_ref,
            instance.skill_bindings,
        )
        return instance

    async def get(self, bot_id: str) -> BotInstance:
        row = await self.session.get(BotRow, bot_id)
        if row is None:
            raise BotNotFound(bot_id)
        return BotInstance.model_validate(row.payload)

    async def list_all(self, status: str | None = None) -> list[BotInstance]:
        rows = list(
            (
                await self.session.execute(
                    select(BotRow).order_by(BotRow.created_at, BotRow.bot_id)
                )
            ).scalars()
        )
        items = [BotInstance.model_validate(row.payload) for row in rows]
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    async def update(self, bot_id: str, patch: BotPatch) -> BotInstance:
        return await self._retry(lambda: self._update_once(bot_id, patch))

    async def _update_once(self, bot_id: str, patch: BotPatch) -> BotInstance:
        row = await self._locked_row(bot_id)
        instance = BotInstance.model_validate(row.payload)
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if "skill_bindings" in updates and patch.skill_bindings is not None:
            updates["skill_bindings"] = patch.skill_bindings
        pin_changed = any(
            field in updates
            and self._canonical(field, updates[field]) != self._canonical(field, getattr(instance, field))
            for field in _PIN_FIELDS
        )
        if instance.status == "archived" and pin_changed:
            raise BotArchived(bot_id)
        merged = BotInstance.model_validate({**instance.model_dump(), **updates})
        row.display_name = merged.display_name
        row.payload = merged.model_dump()
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "display_name" in str(exc) or "uq_bots_display_name_ci" in str(exc):
                raise BotNameConflict(merged.display_name) from exc
            raise
        if pin_changed:
            await self._append_pin(
                bot_id,
                merged.model,
                merged.provider_ref,
                merged.skill_bindings,
            )
        return merged

    async def archive(self, bot_id: str) -> BotInstance:
        return await self._retry(lambda: self._archive_once(bot_id))

    async def _archive_once(self, bot_id: str) -> BotInstance:
        row = await self._locked_row(bot_id)
        instance = BotInstance.model_validate(row.payload)
        if instance.status == "archived":
            raise BotAlreadyArchived(bot_id)
        archived = instance.model_copy(update={"status": "archived"})
        row.status = archived.status
        row.payload = archived.model_dump()
        await self.session.flush()
        return archived

    async def latest_pin(self, bot_id: str) -> dict[str, Any]:
        if await self.session.get(BotRow, bot_id) is None:
            raise BotNotFound(bot_id)
        stmt = (
            select(BotPinRevisionRow)
            .where(BotPinRevisionRow.bot_id == bot_id)
            .order_by(BotPinRevisionRow.revision.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            raise KeyError(f"bot has no pin: {bot_id}")
        return _pin_dict(row)

    async def pin_at(self, bot_id: str, revision: int) -> dict[str, Any]:
        row = await self.session.get(BotPinRevisionRow, (bot_id, revision))
        if row is None:
            raise KeyError(f"pin not found: {bot_id}@{revision}")
        return _pin_dict(row)

    async def _locked_row(self, bot_id: str) -> BotRow:
        """Take SQLite's write lock before reading so concurrent updates serialize."""
        result = await self.session.execute(
            sa_update(BotRow).where(BotRow.bot_id == bot_id).values(bot_id=bot_id)
        )
        if result.rowcount == 0:
            raise BotNotFound(bot_id)
        row = await self.session.get(BotRow, bot_id)
        assert row is not None
        return row

    async def _append_pin(
        self,
        bot_id: str,
        model: str,
        provider_ref: str,
        skill_bindings: list[BotSkillBinding] | list[dict[str, Any]],
    ) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO bot_pin_revisions
                    (bot_id, revision, model, provider_ref, skill_bindings, created_at)
                SELECT :bot_id, COALESCE(MAX(revision), 0) + 1, :model,
                       :provider_ref, :skill_bindings, :created_at
                FROM bot_pin_revisions
                WHERE bot_id = :bot_id
                """
            ),
            {
                "bot_id": bot_id,
                "model": model,
                "provider_ref": provider_ref,
                "skill_bindings": json.dumps(_binding_values(skill_bindings)),
                "created_at": _now(),
            },
        )

    async def _retry(self, operation):
        for attempt in range(4):
            try:
                return await operation()
            except OperationalError as exc:
                await self.session.rollback()
                if not _is_locked(exc) or attempt == 3:
                    raise
                await asyncio.sleep(0.02 * (attempt + 1))

    @staticmethod
    def _canonical(field: str, value: Any) -> Any:
        if field == "skill_bindings":
            return _binding_values(value)
        return value


__all__ = [
    "BotAlreadyArchived",
    "BotArchived",
    "BotNameConflict",
    "BotNotFound",
    "BotRegistry",
]