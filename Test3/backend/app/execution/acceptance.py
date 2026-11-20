"""Human module acceptance and defect back-flow (P5, contracts C.4 / C.5.7).

Acceptance and defects are a new domain beside the legacy whole-run acceptance
path.  ``Workbench.accept()``, force-pass and takeover are untouched: a defect
never becomes ``resolved`` automatically and an acceptance never triggers
``schedule`` / ``execute_task``.

Evidence rules:

* ``accepted`` requires non-empty ``evidence_uris`` and every task code must be
  successful; the URIs must already exist on those tasks.
* ``rejected`` also requires evidence (a review without evidence is not a
  review) and produces one open defect per task code.
* ``pending`` is recorded without evidence requirements.
* ``model_self_review=true`` is never accepted as proof; the HTTP layer rejects
  it before this service is reached.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.dag import SUCCESS_STATES
from app.storage.models import DefectRow, ModuleAcceptanceRow

ModuleAcceptanceStatus = Literal["pending", "accepted", "rejected"]
DefectStatus = Literal["open", "reopened", "resolved"]


class ModuleAcceptance(BaseModel):
    acceptance_id: str
    run_id: str
    module_id: str
    task_codes: list[str]
    status: ModuleAcceptanceStatus
    evidence_uris: list[str]
    reviewer: str
    comment: str = ""


class DefectRecord(BaseModel):
    defect_id: str
    run_id: str
    task_code: str
    module_id: str
    related_requirement_id: str | None = None
    evidence_uris: list[str]
    status: DefectStatus
    detail: str


class ModuleAcceptanceCreate(BaseModel):
    module_id: str
    task_codes: list[str] = Field(default_factory=list)
    status: ModuleAcceptanceStatus
    evidence_uris: list[str] = Field(default_factory=list)
    reviewer: str = ""
    comment: str = ""


class DefectCreate(BaseModel):
    task_code: str
    module_id: str
    related_requirement_id: str | None = None
    evidence_uris: list[str] = Field(default_factory=list)
    detail: str


class AcceptanceValidation(Exception):
    """Bad request payload: HTTP 400 validation_error."""


class AcceptanceForbidden(Exception):
    """Caller may not act for this reviewer: HTTP 403 forbidden."""


def _evidence_paths(task: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for item in task.get("evidence") or []:
        if isinstance(item, dict):
            for key in ("path", "uri"):
                value = item.get(key)
                if value:
                    paths.add(str(value))
        elif item:
            paths.add(str(item))
    return paths


def _require_existing_evidence(run: Any, task_codes: list[str], evidence_uris: list[str]) -> None:
    if not task_codes:
        raise AcceptanceValidation("task_codes must not be empty")
    if not evidence_uris:
        raise AcceptanceValidation("evidence_uris is required")
    available: set[str] = set()
    for code in task_codes:
        task = run.tasks.get(code)
        if task is None:
            raise AcceptanceValidation(f"task not found: {code}")
        available |= _evidence_paths(task)
    missing = [uri for uri in evidence_uris if uri not in available]
    if missing:
        raise AcceptanceValidation(f"evidence not found on task: {', '.join(missing)}")


def _require_successful(run: Any, task_codes: list[str]) -> None:
    failing = [code for code in task_codes if (run.tasks.get(code) or {}).get("state") not in SUCCESS_STATES]
    if failing:
        raise AcceptanceValidation(f"task has no successful evidence: {', '.join(failing)}")


async def record_acceptance(
    session: AsyncSession,
    run: Any,
    data: ModuleAcceptanceCreate,
    *,
    actor: str,
) -> tuple[ModuleAcceptance, list[DefectRecord]]:
    if data.status == "accepted":
        _require_existing_evidence(run, data.task_codes, data.evidence_uris)
        _require_successful(run, data.task_codes)
    elif data.status == "rejected":
        _require_existing_evidence(run, data.task_codes, data.evidence_uris)

    acceptance = ModuleAcceptance(
        acceptance_id=str(uuid.uuid4()),
        run_id=str(run.id),
        module_id=data.module_id,
        task_codes=list(data.task_codes),
        status=data.status,
        evidence_uris=list(data.evidence_uris),
        reviewer=data.reviewer or actor,
        comment=data.comment,
    )
    session.add(
        ModuleAcceptanceRow(
            acceptance_id=acceptance.acceptance_id,
            run_id=acceptance.run_id,
            module_id=acceptance.module_id,
            payload=acceptance.model_dump(),
        )
    )
    defects: list[DefectRecord] = []
    if data.status == "rejected":
        for code in data.task_codes:
            defects.append(
                await _insert_defect(
                    session,
                    run,
                    task_code=code,
                    module_id=data.module_id,
                    related_requirement_id=None,
                    evidence_uris=data.evidence_uris,
                    detail=data.comment or "module acceptance rejected",
                )
            )
    await session.flush()
    return acceptance, defects


async def create_defect(session: AsyncSession, run: Any, data: DefectCreate, *, actor: str) -> DefectRecord:
    task = run.tasks.get(data.task_code)
    if task is None:
        raise AcceptanceValidation(f"task not found: {data.task_code}")
    if not data.evidence_uris:
        raise AcceptanceValidation("evidence_uris is required")
    available = _evidence_paths(task)
    missing = [uri for uri in data.evidence_uris if uri not in available]
    if missing:
        raise AcceptanceValidation(f"evidence not found on task: {', '.join(missing)}")
    defect = await _insert_defect(
        session,
        run,
        task_code=data.task_code,
        module_id=data.module_id,
        related_requirement_id=data.related_requirement_id,
        evidence_uris=data.evidence_uris,
        detail=data.detail,
    )
    await session.flush()
    return defect


async def _insert_defect(
    session: AsyncSession,
    run: Any,
    *,
    task_code: str,
    module_id: str,
    related_requirement_id: str | None,
    evidence_uris: list[str],
    detail: str,
) -> DefectRecord:
    defect = DefectRecord(
        defect_id=str(uuid.uuid4()),
        run_id=str(run.id),
        task_code=task_code,
        module_id=module_id,
        related_requirement_id=related_requirement_id,
        evidence_uris=list(evidence_uris),
        status="open",
        detail=detail,
    )
    session.add(
        DefectRow(
            defect_id=defect.defect_id,
            run_id=defect.run_id,
            task_code=defect.task_code,
            payload=defect.model_dump(),
        )
    )
    return defect


__all__ = [
    "AcceptanceForbidden",
    "AcceptanceValidation",
    "DefectCreate",
    "DefectRecord",
    "DefectStatus",
    "ModuleAcceptance",
    "ModuleAcceptanceCreate",
    "ModuleAcceptanceStatus",
    "create_defect",
    "record_acceptance",
]