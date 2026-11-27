"""Run execution-profile helpers.

The authoritative copy for granted runs lives in SQLite
(``run_execution_state``).  ``run.artifacts`` remains a compatibility snapshot
only: a missing key is *unspecified* and must fail closed, never silently become
``legacy``.  Ordinary runs created by ``Workbench.create_run`` are explicitly
legacy server-side.
"""

from __future__ import annotations

from typing import Any

from app.execution.run_state_store import (
    PROFILE_CONFLICT,
    PROFILE_GRANTED,
    PROFILE_LEGACY,
    PROFILE_UNSPECIFIED,
)
from app.schemas.execution_grant import ExecutionProfile

PROFILE_KEY = "execution_profile"
BASELINE_HASHES_KEY = "approved_baseline_hashes"


def run_execution_profile(run: Any) -> str:
    """Resolve the in-memory profile: explicit value, then snapshot evidence.

    Missing evidence is ``unspecified`` (fail closed), not legacy.  Only a
    server-side create/enable path may write ``legacy`` / ``granted_v1``.
    """
    value = str(getattr(run, "execution_profile", "") or "")
    if value:
        return value
    raw = (getattr(run, "artifacts", None) or {}).get(PROFILE_KEY)
    if raw == PROFILE_GRANTED:
        return PROFILE_GRANTED
    if raw == PROFILE_LEGACY:
        return PROFILE_LEGACY
    if raw is None:
        return PROFILE_UNSPECIFIED
    return PROFILE_CONFLICT


def run_approved_baseline_hashes(run: Any) -> dict[str, str]:
    current = getattr(run, "approved_baseline_hashes", None)
    if isinstance(current, dict) and current:
        return {str(key): str(value) for key, value in current.items()}
    raw = (getattr(run, "artifacts", None) or {}).get(BASELINE_HASHES_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def set_run_execution_profile(run: Any, profile: ExecutionProfile) -> None:
    if profile not in (PROFILE_LEGACY, PROFILE_GRANTED):
        raise ValueError(f"unknown execution profile: {profile}")
    run.execution_profile = profile
    run.artifacts[PROFILE_KEY] = profile


def set_approved_baseline_hashes(run: Any, hashes: dict[str, str]) -> None:
    normalized = {str(key): str(value) for key, value in hashes.items()}
    run.approved_baseline_hashes = normalized
    run.artifacts[BASELINE_HASHES_KEY] = normalized
    # Direct hash writes are the internal/test fixture path; the gate path
    # records "approved" explicitly in Workbench._record_approved_baseline.
    run.artifacts.setdefault("baseline_provenance", "fixture")


def store_approved_baseline_hash(run: Any, key: str, value: str) -> dict[str, str]:
    hashes = run_approved_baseline_hashes(run)
    hashes[key] = value
    run.approved_baseline_hashes = hashes
    run.artifacts[BASELINE_HASHES_KEY] = hashes
    return hashes


__all__ = [
    "BASELINE_HASHES_KEY",
    "PROFILE_CONFLICT",
    "PROFILE_GRANTED",
    "PROFILE_LEGACY",
    "PROFILE_KEY",
    "PROFILE_UNSPECIFIED",
    "run_approved_baseline_hashes",
    "run_execution_profile",
    "set_approved_baseline_hashes",
    "set_run_execution_profile",
    "store_approved_baseline_hash",
]