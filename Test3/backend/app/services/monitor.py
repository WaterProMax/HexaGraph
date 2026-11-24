from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

RUNNING_STATES = {"running", "verifying"}
FAILED_STATES = {"failed", "needs_human"}
BLOCKED_STATES = {"blocked"}
PENDING_STATES = {"pending", "ready"}
SKIPPED_STATES = {"skipped", "cancelled", "stale"}


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _status(state: str) -> str:
    if state == "done":
        return "done"
    if state in RUNNING_STATES:
        return "running"
    if state in FAILED_STATES:
        return "failed"
    if state in BLOCKED_STATES:
        return "blocked"
    if state in PENDING_STATES:
        return "pending"
    if state in SKIPPED_STATES:
        return "skipped"
    return state or "pending"


def _model_for(role: str, roles: Any, models: Any) -> tuple[str, str]:
    role_cfg = getattr(roles, "roles", {}).get(role) if roles is not None else None
    slot = str(getattr(role_cfg, "slot", "") or "")
    slot_cfg = getattr(models, "slots", {}).get(slot) if slot and models is not None else None
    return slot, str(getattr(slot_cfg, "model", "") or "")


def _task_durations(events: list[dict[str, Any]]) -> dict[str, float]:
    starts: dict[str, datetime] = {}
    finished: dict[str, float] = {}
    for event in events:
        if event.get("kind") != "task.state_changed":
            continue
        payload = event.get("payload") or {}
        code = str(payload.get("code") or event.get("subject") or "")
        to = str(payload.get("to") or "")
        ts = _parse_ts(event.get("ts"))
        if not code or ts is None:
            continue
        if to == "running":
            starts[code] = ts
        elif to in {"done", "failed", "needs_human", "skipped", "cancelled"} and code in starts:
            finished[code] = max(0.0, (ts - starts[code]).total_seconds())
    return finished


def _fallback_counts(events: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for event in events:
        if event.get("kind") != "llm.fallback":
            continue
        payload = event.get("payload") or {}
        slot = str(payload.get("slot") or event.get("subject") or "unknown")
        counts[slot] += 1
    return counts


def _rollup(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(task.get("status") or "pending") for task in tasks)
    total = len(tasks)
    done = counts.get("done", 0)
    return {
        "total": total,
        "done": done,
        "running": counts.get("running", 0),
        "failed": counts.get("failed", 0),
        "blocked": counts.get("blocked", 0),
        "pending": counts.get("pending", 0),
        "skipped": counts.get("skipped", 0),
        "progress": round(done * 100 / total) if total else 0,
    }


def build_monitor_snapshot(run: Any, models: Any, roles: Any) -> dict[str, Any]:
    events = list(run.events or [])
    durations = _task_durations(events)
    fallbacks = _fallback_counts(events)
    task_rows: list[dict[str, Any]] = []
    for code in sorted((run.tasks or {}).keys()):
        task = run.tasks[code] or {}
        card = task.get("card") or {}
        state = str(task.get("state") or "pending")
        role = str(card.get("role") or "")
        slot, model = _model_for(role, roles, models)
        evidence = task.get("evidence") or []
        issues = task.get("review_issues") or []
        task_rows.append(
            {
                "code": str(code),
                "title": str(card.get("title") or code),
                "state": state,
                "status": _status(state),
                "role": role,
                "slot": slot,
                "model": model,
                "module": str(card.get("module") or ""),
                "parent": str(card.get("parent") or ""),
                "points": int(card.get("points") or 0),
                "tokens_used": int(task.get("tokens_used") or 0),
                "repair_rounds": int(task.get("repair_rounds") or 0),
                "last_error": str(task.get("last_error") or "")[:300],
                "blocked_by": list(task.get("blocked_by") or []),
                "waiting_on": list(task.get("waiting_on") or []),
                "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
                "review_issue_count": len(issues) if isinstance(issues, list) else 0,
                "revision": int(task.get("revision") or 0),
                "paused": bool(task.get("paused")),
                "duration_seconds": round(durations[code], 1) if code in durations else None,
            }
        )

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for task in task_rows:
        by_parent.setdefault(task["parent"], []).append(task)

    plan = run.artifacts.get("plan") or {}
    package_rows: list[dict[str, Any]] = []
    known: set[str] = set()
    for package in plan.get("work_packages") or []:
        code = str(package.get("code") or "")
        if not code:
            continue
        known.add(code)
        package_rows.append(
            {
                "code": code,
                "title": str(package.get("title") or code),
                "module": str(package.get("module") or ""),
                **_rollup(by_parent.get(code, [])),
            }
        )
    loose = [task for task in task_rows if task["parent"] not in known]
    if loose:
        package_rows.append(
            {
                "code": "",
                "title": "未归入工作包",
                "module": "",
                **_rollup(loose),
            }
        )

    state_counts = Counter(str(task.get("state") or "pending") for task in task_rows)
    summary = {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "stage": run.engine.current,
        "paused": bool(run.paused),
        "revision": int(run.revision or 0),
        "tokens_used": int(run.tokens_used or 0),
        "event_count": len(events),
        "task_count": len(task_rows),
        "state_counts": dict(sorted(state_counts.items())),
        **_rollup(task_rows),
        "repair_rounds": sum(task["repair_rounds"] for task in task_rows),
        "fallback_count": sum(fallbacks.values()),
        "fallback_by_slot": dict(sorted(fallbacks.items())),
        "first_event_at": next((str(e.get("ts")) for e in events if e.get("ts")), ""),
        "last_event_at": next((str(e.get("ts")) for e in reversed(events) if e.get("ts")), ""),
    }
    first = _parse_ts(summary["first_event_at"])
    last = _parse_ts(summary["last_event_at"])
    if first is not None:
        summary["elapsed_seconds"] = round(((last or datetime.now(timezone.utc)) - first).total_seconds(), 1)
    else:
        summary["elapsed_seconds"] = None

    agents: list[dict[str, Any]] = []
    for role in sorted({task["role"] for task in task_rows}):
        subset = [task for task in task_rows if task["role"] == role]
        slot, model = _model_for(role, roles, models)
        rollup = _rollup(subset)
        attempted = rollup["done"] + rollup["failed"]
        reasons = Counter(
            (task["last_error"] or "未记录") for task in subset if task["status"] == "failed"
        )
        timed = [task["duration_seconds"] for task in subset if task["duration_seconds"] is not None]
        agents.append(
            {
                "role": role or "未标注",
                "slot": slot,
                "model": model,
                "total": rollup["total"],
                "done": rollup["done"],
                "failed": rollup["failed"],
                "running": rollup["running"],
                "blocked": rollup["blocked"],
                "pending": rollup["pending"],
                "success_rate": round(rollup["done"] * 100 / attempted) if attempted else 0,
                "completion_rate": rollup["progress"],
                "tokens_used": sum(task["tokens_used"] for task in subset),
                "avg_repair_rounds": (
                    round(sum(task["repair_rounds"] for task in subset) / len(subset), 2) if subset else 0
                ),
                "avg_task_seconds": round(sum(timed) / len(timed), 1) if timed else None,
                "fallback_count": fallbacks.get(slot, 0) if slot else 0,
                "failure_reasons": [
                    {"reason": reason, "count": count} for reason, count in reasons.most_common()
                ],
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": summary,
        "work_packages": package_rows,
        "tasks": task_rows,
        "agents": agents,
    }