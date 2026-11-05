from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import (
    ArtifactRow,
    BaselineRow,
    EventRow,
    GateRow,
    ProjectRow,
    RunRow,
    TaskRow,
)


class ProjectRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str, profile: str = "python-pytest") -> ProjectRow:
        row = ProjectRow(id=str(uuid.uuid4()), name=name, profile=profile)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self) -> list[ProjectRow]:
        return list((await self.session.execute(select(ProjectRow))).scalars())

    async def get(self, project_id: str) -> ProjectRow | None:
        return await self.session.get(ProjectRow, project_id)


class RunRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, project_id: str, idea: str, limits: dict[str, Any]) -> RunRow:
        row = RunRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            idea=idea,
            limits_json=json.dumps(limits, ensure_ascii=False),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, run_id: str) -> RunRow | None:
        return await self.session.get(RunRow, run_id)

    async def bump(self, run: RunRow) -> RunRow:
        run.revision += 1
        await self.session.flush()
        return run


class ArtifactRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run_id: str, typ: str, content: dict[str, Any], version: str, created_by: str = "system") -> ArtifactRow:
        row = ArtifactRow(
            run_id=run_id,
            type=typ,
            version=version,
            content_json=json.dumps(content, ensure_ascii=False),
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest(self, run_id: str, typ: str) -> ArtifactRow | None:
        stmt = select(ArtifactRow).where(ArtifactRow.run_id == run_id, ArtifactRow.type == typ).order_by(ArtifactRow.id.desc())
        return (await self.session.execute(stmt)).scalars().first()

    async def list(self, run_id: str) -> list[ArtifactRow]:
        stmt = select(ArtifactRow).where(ArtifactRow.run_id == run_id).order_by(ArtifactRow.id)
        return list((await self.session.execute(stmt)).scalars())


class TaskRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: str) -> TaskRow | None:
        return await self.session.get(TaskRow, task_id)

    async def by_run(self, run_id: str) -> list[TaskRow]:
        stmt = select(TaskRow).where(TaskRow.run_id == run_id)
        return list((await self.session.execute(stmt)).scalars())

    # no direct state setter — orchestrator.transition owns task.state


class EventRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_seq(self, run_id: str) -> int:
        stmt = select(func.max(EventRow.seq)).where(EventRow.run_id == run_id)
        current = (await self.session.execute(stmt)).scalar() or 0
        return current + 1

    async def add(self, run_id: str, kind: str, subject: str, payload: dict[str, Any], actor: str = "system") -> EventRow:
        seq = await self.next_seq(run_id)
        row = EventRow(
            run_id=run_id,
            seq=seq,
            kind=kind,
            subject=subject,
            actor=actor,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def after(self, run_id: str, after: int = 0) -> list[EventRow]:
        stmt = select(EventRow).where(EventRow.run_id == run_id, EventRow.seq > after).order_by(EventRow.seq)
        return list((await self.session.execute(stmt)).scalars())


class GateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, gate: GateRow) -> GateRow:
        self.session.add(gate)
        await self.session.flush()
        return gate

    async def get(self, gate_id: str) -> GateRow | None:
        return await self.session.get(GateRow, gate_id)

    async def pending(self, run_id: str) -> list[GateRow]:
        stmt = select(GateRow).where(GateRow.run_id == run_id, GateRow.status == "pending")
        return list((await self.session.execute(stmt)).scalars())


class BaselineRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run_id: str, kind: str, version: str, artifact_id: int, note: str = "") -> BaselineRow:
        row = BaselineRow(run_id=run_id, kind=kind, version=version, artifact_id=artifact_id, note=note)
        self.session.add(row)
        await self.session.flush()
        return row
