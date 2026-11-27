#!/usr/bin/env python3
"""Capture a read-only static snapshot of one project for the classroom demo project.

Fetches the live backend payloads for the source project/run, rewrites every
UUID with an ``st-`` prefix and every ``W<n>-<nn>`` task code with an ``S``
prefix (so static ids/codes can never collide with live entities), and writes
``frontend/src/static/staticSnapshot.json``.

Usage: python3 scripts/capture_static_snapshot.py [base_url]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765") + "/api"
PROJECT_ID = "1958d688-c67e-4ad1-a667-5e6314ab7efd"
RUN_ID = "09182750-4271-5e8f-8228-7db27ffb26fd"
LEADER_BOT = "66f699a1-c487-4ffb-9538-a0e480249fe4"
OUT = Path(__file__).resolve().parent.parent / "frontend/src/static/staticSnapshot.json"

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
CODE_RE = re.compile(r"\bW(\d+)-(\d+)\b")


def get(path: str, bot: str | None = None):
    req = urllib.request.Request(BASE + path, headers={"X-Bot-Id": bot} if bot else {})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"null")


def rewrite(value):
    text = json.dumps(value, ensure_ascii=False)
    text = UUID_RE.sub(lambda m: "st-" + m.group(0), text)
    text = CODE_RE.sub(lambda m: f"SW{m.group(1)}-{m.group(2)}", text)
    return json.loads(text)


def main() -> None:
    run = get(f"/runs/{RUN_ID}")
    tasks = get(f"/runs/{RUN_ID}/tasks")
    responses: dict[str, object] = {}
    simple_paths = [
        f"/runs/{RUN_ID}",
        f"/runs/{RUN_ID}/tasks",
        f"/runs/{RUN_ID}/monitor",
        f"/runs/{RUN_ID}/trace",
        f"/runs/{RUN_ID}/artifacts",
        f"/runs/{RUN_ID}/stages",
        f"/runs/{RUN_ID}/budget",
        f"/runs/{RUN_ID}/todos",
        f"/runs/{RUN_ID}/discussion",
        f"/runs/{RUN_ID}/execution-grants",
        f"/runs/{RUN_ID}/execution-profile",
        f"/projects/{PROJECT_ID}/memberships",
        "/config/models",
    ]
    for path in simple_paths:
        responses[path] = get(path)
    for path in (f"/runs/{RUN_ID}/defects", f"/runs/{RUN_ID}/module-acceptances"):
        responses[path] = get(path, LEADER_BOT)

    sessions = get(f"/projects/{PROJECT_ID}/discussion-sessions", LEADER_BOT)
    responses[f"/projects/{PROJECT_ID}/discussion-sessions"] = sessions
    session_messages: dict[str, object] = {}
    for session in sessions.get("items", []):
        sid = session["session_id"]
        responses[f"/discussion-sessions/{sid}"] = get(f"/discussion-sessions/{sid}", LEADER_BOT)
        responses[f"/discussion-sessions/{sid}/proposals?include_history=true"] = get(
            f"/discussion-sessions/{sid}/proposals?include_history=true", LEADER_BOT
        )
        responses[f"/discussion-sessions/{sid}/reviews"] = get(
            f"/discussion-sessions/{sid}/reviews", LEADER_BOT
        )
        session_messages[sid] = get(f"/discussion-sessions/{sid}/messages?after=0", LEADER_BOT).get("items", [])

    responses[f"/memory/records?project_id={PROJECT_ID}&visibility=project"] = get(
        f"/memory/records?project_id={PROJECT_ID}&visibility=project", LEADER_BOT
    )
    events = get(f"/runs/{RUN_ID}/events/history?after=0")
    bots = get("/bots")

    # Role memory per task (role comes from the task card; default coder).
    def fetch_role_memory(task: dict):
        code = task["code"]
        role = (task.get("card") or {}).get("role") or "coder"
        try:
            return f"{code}:{role}", get(f"/runs/{RUN_ID}/tasks/{code}/role-memory/{role}", LEADER_BOT)
        except Exception as exc:  # noqa: BLE001 - snapshot capture is best-effort per task
            return f"{code}:{role}", {"__error__": str(exc)}

    role_memory: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, value in pool.map(fetch_role_memory, tasks):
            role_memory[key] = value

    run_summary = {
        "id": RUN_ID,
        "project_id": PROJECT_ID,
        "status": run.get("status"),
        "stage": run.get("stage"),
        "revision": run.get("revision"),
        "paused": run.get("paused"),
        "idea": run.get("idea"),
    }
    snapshot = rewrite(
        {
            "project": {"id": PROJECT_ID, "name": "小红书项目搭建（静态）", "profile": "python-pytest"},
            "runSummary": run_summary,
            "responses": responses,
            "events": events,
            "sessionMessages": session_messages,
            "roleMemory": role_memory,
            "bots": bots,
        }
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    print("tasks:", len(tasks), "events:", len(events), "role_memory:", len(role_memory))


if __name__ == "__main__":
    main()
