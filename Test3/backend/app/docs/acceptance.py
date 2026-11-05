from __future__ import annotations

from app.schemas.docs import AcceptanceReport


def acceptance_pass(report: AcceptanceReport, thresholds: dict[str, float] | None = None) -> bool:
    thresholds = thresholds or {"p1_pass_ratio": 0.9}
    p0 = [item for item in report.features if item.priority == "P0"]
    if any(item.result != "通过" for item in p0):
        return False
    if any(item.manual and item.priority == "P0" and not item.reason for item in report.features):
        return False
    p1 = [item for item in report.features if item.priority == "P1"]
    if p1:
        passed = sum(1 for item in p1 if item.result == "通过")
        if passed / len(p1) < float(thresholds.get("p1_pass_ratio", 0.9)):
            return False
    return True
