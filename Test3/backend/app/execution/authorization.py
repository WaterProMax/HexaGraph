"""One execution-authorization decision for every execution entry point.

This is **not** a second grant store.  It calls the existing admission helpers
and reads the existing run profile / evidence dimensions, then tells the caller
whether the requested action may proceed.  Scope, baseline freshness, DAG and
tool checks stay in their existing implementations (``_granted_scope`` etc.).

Policy (enforced by tests):

* spec approval is not execution authorization; PLAN must be approved too;
* a real provider with a ``legacy`` run is denied (no silent legacy execution);
* ``granted_v1`` real execution also needs the server-owned safety gate;
* scripted/replay runs are a *simulated* exception with honest evidence labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.execution.run_profile import (
    PROFILE_CONFLICT,
    PROFILE_GRANTED,
    PROFILE_LEGACY,
    PROFILE_UNSPECIFIED,
    run_execution_profile,
)
from app.workflow.admission import WorkflowRejected, assert_phase_admission
from app.workflow.evidence import evidence_for_run


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    error_category: str = ""
    detail: str = ""
    status_code: int = 409
    blocked_reason: str = ""
    simulated: bool = False
    model_mode: str = "not_run"
    execution_mode: str = "not_run"
    evidence_level: str = "not_run"


def is_simulated(bench: Any) -> bool:
    """Side-effect-free executor injected by the host (never by provider type)."""
    return getattr(bench, "simulated_executor", None) is not None


def local_execution_test_authorized(bench: Any) -> bool:
    policy = getattr(bench, "execution_policy", None)
    return bool(getattr(policy, "local_execution_authorized", False))


def decide_execution(
    bench: Any,
    run: Any,
    action: str,
    *,
    task_codes: set[str] | None = None,
    discussion: Any | None = None,
) -> ExecutionDecision:
    evidence = evidence_for_run(bench, run)
    simulated = is_simulated(bench)
    from app.workflow.invalidation import baseline_drift

    drift = baseline_drift(run)
    if drift:
        return ExecutionDecision(
            allowed=False,
            error_category="baseline_stale",
            detail=f"approved baseline changed: {', '.join(drift)}; re-approval required",
            status_code=409,
            blocked_reason="baseline_stale",
            simulated=simulated,
            model_mode=evidence["model_mode"],
            execution_mode=evidence["execution_mode"],
            evidence_level=evidence["level"],
        )
    try:
        assert_phase_admission(action, discussion=discussion, run=run)
    except WorkflowRejected as exc:
        return ExecutionDecision(
            allowed=False,
            error_category=exc.category,
            detail=exc.message,
            status_code=exc.status_code,
            blocked_reason=exc.blocked_reason,
            simulated=simulated,
            model_mode=evidence["model_mode"],
            execution_mode=evidence["execution_mode"],
            evidence_level=evidence["level"],
        )

    profile = run_execution_profile(run)
    from app.workflow.invalidation import baseline_provenance

    provenance = baseline_provenance(run)
    if provenance == "unknown":
        return ExecutionDecision(
            allowed=False,
            error_category="baseline_unverifiable",
            detail="run has baseline hashes but no verifiable human approval; explicit re-approval required",
            status_code=409,
            blocked_reason="baseline_unverifiable",
            simulated=simulated,
            model_mode=evidence["model_mode"],
            execution_mode=evidence["execution_mode"],
            evidence_level=evidence["level"],
        )
    base = dict(
        simulated=simulated,
        model_mode=evidence["model_mode"],
        execution_mode=evidence["execution_mode"],
        evidence_level=evidence["level"],
    )
    if profile in (PROFILE_UNSPECIFIED, PROFILE_CONFLICT):
        category = "profile_conflict" if profile == PROFILE_CONFLICT else "profile_unspecified"
        return ExecutionDecision(
            allowed=False,
            error_category=category,
            detail="run execution profile is not usable",
            status_code=409,
            blocked_reason=category,
            **base,
        )
    if profile == PROFILE_GRANTED:
        if not simulated and not bool(getattr(bench, "execution_safety_ready", False)):
            return ExecutionDecision(
                allowed=False,
                error_category="execution_safety_not_ready",
                detail="granted execution isolation and authorization are not ready",
                status_code=409,
                blocked_reason="execution_safety_not_ready",
                **base,
            )
        return ExecutionDecision(allowed=True, **base)
    if profile == PROFILE_LEGACY:
        if simulated or local_execution_test_authorized(bench):
            return ExecutionDecision(allowed=True, **base)
        return ExecutionDecision(
            allowed=False,
            error_category="profile_not_granted_v1",
            detail=(
                "real execution requires granted_v1, an active grant, matching baselines "
                "and the server-owned safety gate; scripted model output alone does not "
                "authorize workspace writes, commands or merges"
            ),
            status_code=403,
            blocked_reason="profile_not_granted_v1",
            **base,
        )
    return ExecutionDecision(
        allowed=False,
        error_category="profile_unspecified",
        detail="run execution profile is not usable",
        status_code=409,
        blocked_reason="profile_unspecified",
        **base,
    )


__all__ = ["ExecutionDecision", "decide_execution", "is_simulated"]