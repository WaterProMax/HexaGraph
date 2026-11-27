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


def baseline_provenance(run: Any) -> str:
    artifacts = getattr(run, "artifacts", None) or {}
    marked = artifacts.get("baseline_provenance")
    if marked == "approved":
        return "approved"
    if marked == "fixture":
        return "fixture"
    if artifacts.get("approvals"):
        return "approved"
    for gate in getattr(run, "gates", None) or []:
        if gate.get("kind") in {"SPEC基线确认", "DESIGN基线确认", "PLAN基线确认"} and gate.get("status") == "approved":
            return "approved"
    return "unknown" if run_approved_baseline_hashes(run) else "none"


def baseline_drift(run: Any) -> list[str]:
    """Return approved keys whose current artifact no longer matches.

    Only a verifiable human approval is used.  Fixture placeholders never drive
    drift, and hash-only runs without any provenance become ``unknown`` (blocked
    by authorization) rather than being silently trusted.
    """
    if baseline_provenance(run) != "approved":
        return []
    artifacts = getattr(run, "artifacts", None) or {}
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


__all__ = ["baseline_drift", "baseline_provenance", "invalidation_record"]