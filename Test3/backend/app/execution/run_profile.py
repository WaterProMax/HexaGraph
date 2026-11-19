"""Read/write execution-profile state stored on a legacy ``RunState``.

P0 found no SQLite column for ``run.execution_profile`` / baseline hashes, so
contracts C.3.1 allows keeping them in ``run.artifacts`` until a dedicated run
column exists. Only server-side helpers write these keys; no HTTP endpoint
accepts a client-supplied downgrade to ``legacy``.
"""

from __future__ import annotations

from typing import Any

from app.schemas.execution_grant import ExecutionProfile

PROFILE_KEY = "execution_profile"
BASELINE_HASHES_KEY = "approved_baseline_hashes"


def run_execution_profile(run: Any) -> ExecutionProfile:
    value = (getattr(run, "artifacts", None) or {}).get(PROFILE_KEY)
    return "granted_v1" if value == "granted_v1" else "legacy"


def run_approved_baseline_hashes(run: Any) -> dict[str, str]:
    raw = (getattr(run, "artifacts", None) or {}).get(BASELINE_HASHES_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def set_run_execution_profile(run: Any, profile: ExecutionProfile) -> None:
    if profile not in ("legacy", "granted_v1"):
        raise ValueError(f"unknown execution profile: {profile}")
    run.artifacts[PROFILE_KEY] = profile


def set_approved_baseline_hashes(run: Any, hashes: dict[str, str]) -> None:
    run.artifacts[BASELINE_HASHES_KEY] = {str(key): str(value) for key, value in hashes.items()}


def store_approved_baseline_hash(run: Any, key: str, value: str) -> dict[str, str]:
    hashes = run_approved_baseline_hashes(run)
    hashes[key] = value
    run.artifacts[BASELINE_HASHES_KEY] = hashes
    return hashes


__all__ = [
    "BASELINE_HASHES_KEY",
    "PROFILE_KEY",
    "run_approved_baseline_hashes",
    "run_execution_profile",
    "set_approved_baseline_hashes",
    "set_run_execution_profile",
    "store_approved_baseline_hash",
]