"""Leader-owned discussion session creation and grouping."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.discussion.models import DiscussionBudget, DiscussionSession
from app.discussion.session_store import (
    DiscussionSessionStore,
    Forbidden,
    InvalidStatus,
    SessionNotFound,
    retry_locked,
)
from app.execution.baseline import hash_artifact
from app.storage.models import ProjectMembershipRow


class ProjectNotFound(Exception):
    pass


class LeaderNotInProject(Exception):
    pass


class InvalidParticipant(Exception):
    pass


class DiscussionSteward:
    def __init__(self, session: AsyncSession, project_exists=None) -> None:
        self.session = session
        self.project_exists = project_exists
        self.store = DiscussionSessionStore(session)

    async def _validated_participants(
        self, project_id: str, participant_bot_ids: list[str]
    ) -> list[str]:
        unique = list(dict.fromkeys(participant_bot_ids))
        if not unique:
            raise InvalidParticipant("participant list is empty")
        for bot_id in unique:
            row = await self.session.get(ProjectMembershipRow, (project_id, bot_id))
            if row is None:
                raise InvalidParticipant(f"bot {bot_id} is not a project member")
        return unique

    async def create_session(
        self,
        project_id: str,
        leader_bot_id: str,
        participant_bot_ids: list[str],
        requirement_snapshot: Any,
        budget: DiscussionBudget | dict | None = None,
    ) -> DiscussionSession:
        if self.project_exists is not None and not self.project_exists(project_id):
            raise ProjectNotFound(project_id)
        leader = await self.session.get(ProjectMembershipRow, (project_id, leader_bot_id))
        if leader is None or int(leader.is_leader) != 1:
            raise LeaderNotInProject(leader_bot_id)
        participants = await self._validated_participants(project_id, participant_bot_ids)
        if budget is None:
            budget_obj = DiscussionBudget()
        elif isinstance(budget, DiscussionBudget):
            budget_obj = budget
        else:
            budget_obj = DiscussionBudget.model_validate(budget)
        record = DiscussionSession(
            session_id=str(uuid.uuid4()),
            project_id=project_id,
            leader_bot_id=leader_bot_id,
            participant_bot_ids=participants,
            status="draft",
            current_round=0,
            budget=budget_obj,
            requirement_snapshot_hash=hash_artifact(requirement_snapshot),
            decision_package=None,
        )
        await self.store.create(record)
        return record

    async def group(
        self,
        session_id: str,
        *,
        actor_bot_id: str,
        participant_bot_ids: list[str] | None = None,
    ) -> DiscussionSession:
        return await retry_locked(
            self.session,
            lambda: self._group_once(session_id, actor_bot_id, participant_bot_ids),
        )

    async def _group_once(
        self,
        session_id: str,
        actor_bot_id: str,
        participant_bot_ids: list[str] | None,
    ) -> DiscussionSession:
        record = await self.store.get_locked(session_id)
        if actor_bot_id != record.leader_bot_id:
            raise Forbidden("only the session leader can group participants")
        if record.status not in {"draft", "grouping"}:
            raise InvalidStatus(record.status)
        if participant_bot_ids is not None:
            participants = await self._validated_participants(
                record.project_id, participant_bot_ids
            )
            record = record.model_copy(update={"participant_bot_ids": participants})
        record = record.model_copy(update={"status": "grouping"})
        await self.store.save(record)
        return record


__all__ = [
    "DiscussionSteward",
    "Forbidden",
    "InvalidParticipant",
    "InvalidStatus",
    "LeaderNotInProject",
    "ProjectNotFound",
    "SessionNotFound",
]