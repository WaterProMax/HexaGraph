from __future__ import annotations

import os

import pytest

from app.execution.github_auth import parse_github_write_auth


@pytest.mark.live
def test_live_pr_optional() -> None:
    """Only meaningful when a human pastes the C.7 authorization sentence.

    Default ``pytest -m 'not live'`` never selects this test. It deliberately
    performs no network write on its own; the authorized run is a manual step
    recorded in ``p1-pr-record.json``.
    """
    auth = parse_github_write_auth(os.environ.get("TEST3_GITHUB_WRITE_AUTH"))
    if auth is None:
        pytest.skip("missing github_write authorization")
    assert auth.feature_branch != auth.base_branch
    assert auth.remote and auth.owner and auth.repo