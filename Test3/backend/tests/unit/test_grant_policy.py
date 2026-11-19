from __future__ import annotations

import inspect
from dataclasses import dataclass, field

from app.execution.grant_policy import grant_stale_reason


@dataclass
class GrantView:
    task_codes: list[str] = field(default_factory=list)
    approved_baseline_hashes: dict[str, str] = field(default_factory=dict)
    status: str = "active"


def _grant(**overrides) -> GrantView:
    base = GrantView(task_codes=["T-01", "T-02"], approved_baseline_hashes={"PLAN": "aaa"})
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_active_subset_is_allowed() -> None:
    grant = _grant()
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes={"T-01"}) is None


def test_full_set_is_allowed() -> None:
    grant = _grant()
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes={"T-01", "T-02"}) is None


def test_empty_request_is_rejected_even_with_active_grant() -> None:
    grant = _grant()
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes=set()) == "empty_request"


def test_superset_is_scope_mismatch() -> None:
    grant = _grant()
    reason = grant_stale_reason(
        grant,
        approved_baseline_hashes={"PLAN": "aaa"},
        requested_task_codes={"T-01", "T-02", "T-99"},
    )
    assert reason == "scope_mismatch"


def test_changed_baseline_names_the_key() -> None:
    grant = _grant()
    reason = grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "bbb"}, requested_task_codes={"T-01"})
    assert reason == "baseline_changed:PLAN"


def test_missing_baseline_key_is_stale() -> None:
    grant = _grant(approved_baseline_hashes={"PLAN": "aaa", "SPEC": "sss"})
    reason = grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes={"T-01"})
    assert reason == "baseline_changed:SPEC"


def test_consumed_grant_wins_over_valid_scope() -> None:
    grant = _grant(status="consumed")
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes={"T-01"}) == "grant_consumed"


def test_revoked_grant_wins_over_empty_request() -> None:
    grant = _grant(status="revoked")
    assert grant_stale_reason(grant, approved_baseline_hashes={"PLAN": "aaa"}, requested_task_codes=set()) == "grant_revoked"


def test_signature_has_no_revision_parameter() -> None:
    params = set(inspect.signature(grant_stale_reason).parameters)
    assert params == {"grant", "approved_baseline_hashes", "requested_task_codes"}
    assert not any("revision" in name for name in params)