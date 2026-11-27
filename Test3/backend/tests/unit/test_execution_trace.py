"""Unit tests for the I0 execution-trace contract.

These lock the field names, the truncation/redaction rules and the fail-open
behaviour before any page renders "已注入" or "已计价".
"""

from __future__ import annotations

import json

import pytest

from app.execution.trace_log import (
    EVENT_FOR_KIND,
    EXECUTION_PATH_LEGACY,
    EXECUTION_PATH_SIMULATED,
    FIELD_LIMIT,
    ExecutionTraceRecorder,
    build_execution_trace,
    clip,
    last_step_summary,
    redact_text,
    sanitize_summary,
    step_count,
    summarize_tool_call,
    summarize_tool_result,
)


def _attempt(**overrides):
    attempt = {
        "attempt_id": "attempt-1",
        "status": "started",
        "started_at": "2026-11-26T00:00:00+00:00",
        "role": "coder",
        "context_hash": "ctx-hash",
        "memory_context_hash": "mem-hash",
        "manual_revision": 3,
        "skill_bundle_hash": "",
        "commit": "",
    }
    attempt.update(overrides)
    return attempt


def _recorder(attempt=None, path=EXECUTION_PATH_LEGACY, injected=True, events=None):
    attempt = _attempt() if attempt is None else attempt
    sink = events if events is not None else []
    recorder = ExecutionTraceRecorder(
        execution_path=path,
        context_injected=injected,
        attempt=attempt,
        emit=lambda kind, payload: sink.append((kind, payload)),
    )
    return recorder, attempt, sink


# --- redaction / truncation -------------------------------------------------


def test_write_file_content_never_enters_summary() -> None:
    body = "SECRET_FILE_BODY" * 40
    text, truncated = summarize_tool_call("write_file", {"path": "src/app.py", "content": body})
    assert "SECRET_FILE_BODY" not in text
    assert "path=src/app.py" in text
    assert "sha256=" in text
    assert "chars=" in text
    assert truncated is False


def test_write_file_result_never_echoes_content() -> None:
    text, _ = summarize_tool_result("write_file", {"ok": True, "path": "src/app.py"})
    assert text == "ok=true; path=src/app.py"


def test_sk_shaped_value_is_redacted_not_fatal() -> None:
    text, _ = summarize_tool_result("read_file", "token sk-abcdef1234567890 lives here")
    assert "sk-abcdef1234567890" not in text
    assert "***REDACTED***" in text


def test_environment_secret_value_is_redacted(monkeypatch) -> None:
    monkeypatch.setenv("HEXAGRAPH_TEST_API_KEY", "do-not-leak-this-value")
    assert "do-not-leak-this-value" not in redact_text("key=do-not-leak-this-value")


def test_overlong_field_is_truncated_and_capped() -> None:
    recorder, _attempt_row, _events = _recorder()
    step = recorder.observe(
        "tool",
        {"name": "run_command", "arguments": {"cmd": ["pytest", "-q"]}, "output": {"exit_code": 1, "output": "x" * 5000}},
    )
    assert step is not None
    assert step["truncated"] is True
    assert len(step["input_summary"]) <= FIELD_LIMIT
    assert len(step["output_summary"]) <= FIELD_LIMIT


def test_sanitize_summary_returns_pair_and_clip_redacts() -> None:
    text, truncated = sanitize_summary("y" * (FIELD_LIMIT + 10))
    assert truncated is True
    assert len(text) == FIELD_LIMIT
    assert clip("short") == ("short", False)


# --- recorder contract ------------------------------------------------------


def test_context_injected_defaults_false_and_path_is_frozen() -> None:
    recorder, attempt, _events = _recorder(path=EXECUTION_PATH_SIMULATED, injected=False)
    assert recorder.enabled is True
    assert attempt["execution_path"] == EXECUTION_PATH_SIMULATED
    assert attempt["context_injected"] is False
    assert attempt["execution_steps"] == []


def test_unknown_execution_path_is_not_recorded_as_a_real_path() -> None:
    _recorder_row, attempt, _events = _recorder(path="made_up_path")
    assert attempt["execution_path"] == ""


def test_llm_and_tool_steps_emit_expected_event_kinds() -> None:
    recorder, attempt, events = _recorder()
    recorder.observe(
        "llm",
        {
            "name": "coder",
            "duration_ms": 812,
            "model": "scripted",
            "slot": "coder",
            "tokens_in": 120,
            "tokens_out": 40,
            "finish_reason": "tool_calls",
            "messages": [{"role": "user", "content": "任务卡 T-01"}],
            "tool_names": ["read_file", "write_file"],
        },
    )
    recorder.observe(
        "tool",
        {"name": "read_file", "arguments": {"path": "src/app.py"}, "output": "abc", "duration_ms": 5},
    )

    assert [kind for kind, _payload in events] == [
        EVENT_FOR_KIND["llm"],
        EVENT_FOR_KIND["tool"],
    ]
    assert [step["step"] for step in attempt["execution_steps"]] == [1, 2]
    first = events[0][1]
    assert first["attempt_id"] == "attempt-1"
    assert first["kind"] == "llm"
    assert first["tokens_in"] == 120
    assert first["finish_reason"] == "tool_calls"
    assert first["output_summary"] == "tool_calls: read_file, write_file"


def test_llm_input_summary_records_roles_and_one_clipped_preview() -> None:
    recorder, _attempt_row, _events = _recorder()
    messages = [
        {"role": "system", "content": "S" * 100},
        {"role": "user", "content": "USER_MARKER" + "y" * 2000},
    ]
    step = recorder.observe("llm", {"name": "coder", "messages": messages})
    assert step is not None
    assert step["input_summary"].startswith("system:100 user:")
    assert len(step["input_summary"]) <= FIELD_LIMIT
    assert step["truncated"] is True
    # The preview is retained; the full prompt is not.
    assert "USER_MARKER" in step["input_summary"]
    assert "y" * 1500 not in step["input_summary"]


def test_denied_tool_step_keeps_status_and_error() -> None:
    recorder, _attempt_row, events = _recorder()
    step = recorder.observe(
        "tool",
        {
            "name": "write_file",
            "arguments": {"path": "outside.py", "content": "x"},
            "output": {"ok": False, "error": "写集外: outside.py"},
            "status": "denied",
            "error": "写集外: outside.py",
        },
    )
    assert step is not None
    assert step["status"] == "denied"
    assert step["error"] == "写集外: outside.py"
    assert events[0][1]["status"] == "denied"


def test_recorded_steps_stay_json_serialisable() -> None:
    recorder, attempt, _events = _recorder()
    recorder.observe("tool", {"name": "list_dir", "arguments": {"path": "."}, "output": ["a.py", "b.py"]})
    json.dumps(attempt)  # the run snapshot writer must not choke


def test_observability_failures_are_fail_open() -> None:
    def broken_sink(_kind, _payload):
        raise RuntimeError("event bus down")

    attempt = _attempt()
    recorder = ExecutionTraceRecorder(
        execution_path=EXECUTION_PATH_LEGACY,
        context_injected=True,
        attempt=attempt,
        emit=broken_sink,
    )
    step = recorder.observe("tool", {"name": "read_file", "arguments": {"path": "a"}, "output": "ok"})
    assert step is not None
    assert len(attempt["execution_steps"]) == 1

    unbound = ExecutionTraceRecorder(execution_path=EXECUTION_PATH_LEGACY, context_injected=True)
    assert unbound.observe("tool", {"name": "read_file"}) is None


# --- response shape ---------------------------------------------------------


def test_build_execution_trace_empty_state_is_not_an_error() -> None:
    trace = build_execution_trace("run-1", "T-01", {"card": {"role": "coder"}})
    assert trace["run_id"] == "run-1"
    assert trace["task_code"] == "T-01"
    assert trace["role"] == "coder"
    assert trace["attempts"] == []
    assert trace["context_injected"] is False
    assert trace["execution_path"] == ""


def test_build_execution_trace_includes_frozen_history_and_current_attempt() -> None:
    finished = _attempt(attempt_id="attempt-0", status="finished_ok", commit="abc123")
    finished["execution_steps"] = [
        {
            "step": 1,
            "kind": "tool",
            "name": "read_file",
            "status": "ok",
            "duration_ms": 5,
            "input_summary": "path=a",
            "output_summary": "chars=1",
            "truncated": False,
            "error": None,
        }
    ]
    current = _attempt(attempt_id="attempt-1", status="started", context_injected=True, execution_path=EXECUTION_PATH_LEGACY)
    current["execution_steps"] = []
    task = {
        "card": {"role": "coder"},
        "attempt": current,
        "attempt_history": [finished],
    }

    trace = build_execution_trace("run-1", "T-01", task)

    assert [item["attempt_id"] for item in trace["attempts"]] == ["attempt-0", "attempt-1"]
    assert trace["attempts"][0]["steps"][0]["name"] == "read_file"
    assert trace["attempts"][1]["status"] == "started"
    assert trace["attempts"][1]["context_injected"] is True
    assert trace["current_attempt_id"] == "attempt-1"
    assert trace["context_injected"] is True
    assert trace["execution_path"] == EXECUTION_PATH_LEGACY


def test_current_attempt_wins_over_stale_history_copy() -> None:
    attempt_id = "attempt-1"
    stale = _attempt(attempt_id=attempt_id, status="started")
    stale["execution_steps"] = []
    fresh = _attempt(attempt_id=attempt_id, status="started")
    fresh["execution_steps"] = [
        {
            "step": 1,
            "kind": "tool",
            "name": "write_file",
            "status": "ok",
            "duration_ms": 1,
            "input_summary": "path=a",
            "output_summary": "ok=true",
            "truncated": False,
            "error": None,
        }
    ]
    trace = build_execution_trace("run-1", "T-01", {"attempt": fresh, "attempt_history": [stale]})
    assert len(trace["attempts"]) == 1
    assert trace["attempts"][0]["steps"][0]["name"] == "write_file"


def test_last_step_summary_and_count_are_lightweight() -> None:
    attempt = _attempt()
    attempt["execution_steps"] = [
        {
            "step": 1,
            "kind": "tool",
            "name": "read_file",
            "status": "ok",
            "duration_ms": 7,
            "input_summary": "path=a",
            "output_summary": "chars=1",
        }
    ]
    assert step_count(attempt) == 1
    assert last_step_summary(attempt) == {
        "kind": "tool",
        "name": "read_file",
        "status": "ok",
        "duration_ms": 7,
    }
    assert last_step_summary({}) is None


@pytest.mark.parametrize("kind", ["llm", "tool", "granted_command"])
def test_every_step_kind_has_an_event_name(kind: str) -> None:
    assert EVENT_FOR_KIND[kind].startswith("task.")