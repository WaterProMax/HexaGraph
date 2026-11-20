"""P1-REV-09: the revision tests must stop asserting a local variable to itself."""

from __future__ import annotations

from pathlib import Path


def test_revision_tests_do_not_contain_tautologies() -> None:
    backend = Path(__file__).resolve().parents[2]
    for name in ("test_grant_policy.py", "test_grant_refresh.py"):
        source = (backend / "tests" / "unit" / name).read_text(encoding="utf-8")
        assert "run_revision = 5" not in source, f"{name} still contains a local revision tautology"
        assert "assert run_revision ==" not in source, f"{name} still asserts a local variable"