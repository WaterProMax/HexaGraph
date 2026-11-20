"""P7-T03: the close gate must fail honestly while no real PR exists.

The fixture cases prove the validator's shape.  The final case runs against the
real ``Test3/docs/plans/p1-pr-record.json``; with ``status=BLOCKED`` and
``github_pr_url=null`` it MUST fail.  It is marked ``closeout`` so the regular
non-live regression (``-m 'not live and not closeout'``) stays green while the
dedicated close command shows the real gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REAL_RECORD = BACKEND_ROOT.parent / "docs" / "plans" / "p1-pr-record.json"


def assert_pr_record_complete(record: dict[str, Any] | str | Path) -> None:
    """Raise AssertionError unless the record proves an open, unmerged PR."""
    if isinstance(record, (str, Path)):
        path = Path(record)
        record = json.loads(path.read_text(encoding="utf-8"))
    status = str(record.get("status") or "")
    if status == "BLOCKED":
        raise AssertionError(
            "p1 PR record is BLOCKED: no C.7 github_write authorization, no real PR"
        )
    url = record.get("github_pr_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise AssertionError(f"p1 PR record status={status or '<empty>'} has no real https github_pr_url")
    if status not in {"PR_OPEN", "OK"}:
        raise AssertionError(f"p1 PR record status={status} is not PR_OPEN/OK")
    if record.get("merged") is not False:
        raise AssertionError("p1 PR record must state merged=false")
    if record.get("deployed") is not False:
        raise AssertionError("p1 PR record must state deployed=false")


def test_blocked_record_fails(tmp_path: Path) -> None:
    path = tmp_path / "blocked.json"
    path.write_text(
        json.dumps({"status": "BLOCKED", "github_pr_url": None, "authorization_present": False}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="BLOCKED"):
        assert_pr_record_complete(path)


def test_pr_open_without_url_fails() -> None:
    with pytest.raises(AssertionError, match="github_pr_url"):
        assert_pr_record_complete({"status": "PR_OPEN", "github_pr_url": "", "merged": False, "deployed": False})


def test_valid_open_pr_passes() -> None:
    assert_pr_record_complete(
        {
            "status": "PR_OPEN",
            "github_pr_url": "https://github.com/example/hexagraph/pull/1",
            "feature_branch": "feat/test3-agent-team-v1",
            "base_branch": "teamwork-001",
            "merged": False,
            "deployed": False,
        }
    )


def test_blocked_with_accepted_flag_still_fails() -> None:
    with pytest.raises(AssertionError, match="BLOCKED"):
        assert_pr_record_complete(
            {"status": "BLOCKED", "accepted": True, "github_pr_url": None, "merged": False, "deployed": False}
        )


@pytest.mark.closeout
def test_real_p1_pr_record_is_complete() -> None:
    """Close gate for the real repository record. Currently expected to FAIL."""
    assert_pr_record_complete(REAL_RECORD)