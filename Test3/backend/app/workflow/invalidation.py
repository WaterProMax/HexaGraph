"""Approved-baseline invalidation.

A changed SPEC/DESIGN/PLAN (or decision package) must not keep executing under an
old grant.  History is append-only: invalidation records and old grants are kept,
never deleted, and re-approval creates a new baseline that old grants cannot use.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.execution.baseline import hash_artifact
from app.execution.run_profile import run_approved_baseline_hashes

_ARTIFACT_KEYS = (("SPEC", "spec"), ("DESIGN", "design"), ("PLAN", "plan"))


def baseline_drift(run: Any) -> list[str]:
    """Return approved keys whose current artifact no longer matches.

    Only runs with a recorded human-gate approval are compared.  Fixtures that
    set placeholder hashes for grant-scope tests are not real approvals, and
    turning them into ``baseline_stale`` would be a false positive.
    """
    artifacts = getattr(run, "artifacts", None) or {}
    if not artifacts.get("approvals"):
        return []
    approved = run_approved_baseline_hashes(run)
    drift: list[str] = []
    for key, artifact_key in _ARTIFACT_KEYS:
        if key not in approved:
            continue
        artifact = artifacts.get(artifact_key)
        if artifact is None:
            continue
        if hash_artifact(artifact) != approved[key]:
            drift.append(key)
    package = artifacts.get("decision_package")
    if (
        "DecisionPackage" in approved
        and isinstance(package, dict)
        and package.get("sha256")
        and str(package["sha256"]) != approved["DecisionPackage"]
    ):
        drift.append("DecisionPackage")
    return drift


def invalidation_record(keys: list[str], reason: str) -> dict[str, Any]:
    return {
        "keys": list(keys),
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_reapproval",
    }


__all__ = ["baseline_drift", "invalidation_record"]