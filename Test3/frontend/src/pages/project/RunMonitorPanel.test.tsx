import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ExecutionAttempt,
  ExecutionStep,
  ExecutionTrace,
  MonitorSnapshot,
  MonitorTask,
} from "../../api/types";
import { RunMonitorPanel } from "./RunMonitorPanel";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

function task(overrides: Partial<MonitorTask>): MonitorTask {
  return {
    code: "T-01",
    title: "任务",
    state: "running",
    status: "running",
    role: "coder",
    slot: "coder",
    model: "qwen-coder",
    module: "M1",
    parent: "",
    points: 1,
    tokens_used: 0,
    repair_rounds: 0,
    last_error: "",
    blocked_by: [],
    waiting_on: [],
    evidence_count: 0,
    review_issue_count: 0,
    revision: 1,
    paused: false,
    duration_seconds: null,
    execution_path: "legacy_tool_agent",
    context_injected: true,
    execution_step_count: 1,
    last_execution_step: null,
    assignee_bot_id: null,
    assignee_display_name: null,
    ...overrides,
  };
}

const TASKS: MonitorTask[] = [
  task({ code: "T-A1", title: "实现登录" }),
  task({ code: "T-B1", title: "实现登出" }),
];

function monitorSnapshot(): MonitorSnapshot {
  return {
    generated_at: "2026-11-24T10:00:00+00:00",
    run: {
      id: "r1",
      project_id: "p1",
      status: "active",
      stage: "7",
      paused: false,
      revision: 1,
      tokens_used: 100,
      event_count: 0,
      task_count: TASKS.length,
      state_counts: { running: TASKS.length },
      total: TASKS.length,
      done: 0,
      running: TASKS.length,
      failed: 0,
      blocked: 0,
      pending: 0,
      skipped: 0,
      progress: 0,
      repair_rounds: 0,
      fallback_count: 0,
      fallback_by_slot: {},
      first_event_at: "",
      last_event_at: "",
      elapsed_seconds: 10,
    },
    work_packages: [],
    tasks: TASKS,
    agents: [],
  };
}

function step(overrides: Partial<ExecutionStep>): ExecutionStep {
  return {
    step: 1,
    kind: "llm",
    name: "coder-gateway",
    status: "ok",
    started_at: "2026-11-24T09:00:00+00:00",
    ended_at: "2026-11-24T09:00:01+00:00",
    duration_ms: 500,
    model: "qwen-coder",
    slot: "coder",
    tokens_in: 10,
    tokens_out: 5,
    finish_reason: "tool_calls",
    input_summary: "user:10",
    output_summary: "tool_calls: write_file",
    error: null,
    truncated: false,
    ...overrides,
  };
}

function traceFor(code: string, marker: string): ExecutionTrace {
  const attempt: ExecutionAttempt = {
    attempt_id: `attempt-${code}`,
    status: "started",
    started_at: "2026-11-24T09:00:00+00:00",
    ended_at: null,
    role: "coder",
    context_hash: "a".repeat(64),
    memory_context_hash: "b".repeat(64),
    manual_revision: 1,
    skill_bundle_hash: "c".repeat(64),
    commit: "",
    context_injected: true,
    execution_path: "legacy_tool_agent",
    steps: [step({ name: marker })],
  };
  return {
    run_id: "r1",
    task_code: code,
    role: "coder",
    execution_path: "legacy_tool_agent",
    context_injected: true,
    current_attempt_id: attempt.attempt_id,
    attempts: [attempt],
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RunMonitorPanel execution trace wiring", () => {
  it("requests the execution trace for the selected task and renders the panels without moving the controls", async () => {
    const traceCalls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/monitor")) return json(monitorSnapshot());
        if (url.includes("/events/history")) return json([]);
        if (url.includes("/execution-trace")) {
          traceCalls.push(url);
          const code = url.includes("T-A1") ? "T-A1" : "T-B1";
          return json(traceFor(code, `${code}-llm`));
        }
        return json({});
      }),
    );

    render(<RunMonitorPanel runId="r1" tasks={[]} />);
    fireEvent.click(await screen.findByText("T-A1"));

    // Exactly one trace GET per task selection: the step timeline and the
    // attempt history share the same in-flight response.
    await waitFor(() => expect(traceCalls).toEqual(["/api/runs/r1/tasks/T-A1/execution-trace"]));
    expect(await screen.findByTestId("execution-trace")).toBeTruthy();
    expect(await screen.findByTestId("attempt-history")).toBeTruthy();
    expect(await screen.findByText(/#1 模型调用 · T-A1-llm/)).toBeTruthy();

    // Existing run/task controls stay where they were. antd inserts a space
    // between two Chinese characters, so match the control names with regexes.
    expect(screen.getByRole("button", { name: "调度执行" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /终\s*止/ })).toBeTruthy();
    expect(screen.getAllByText(/暂\s*停/).length).toBeGreaterThan(0);
    expect(screen.getByText(/重\s*试/)).toBeTruthy();
    expect(screen.getByTestId("monitor-events")).toBeTruthy();

    // A step event on the run bus only triggers a refresh of the panels; the
    // step data itself still comes from the dedicated trace endpoint.
    const source = FakeEventSource.instances[0];
    act(() => {
      source.onmessage?.({ data: JSON.stringify({ seq: 1, kind: "task.llm_step", subject: "T-A1" }) });
    });
    await waitFor(() => expect(traceCalls).toHaveLength(2));
    expect(traceCalls[1]).toBe("/api/runs/r1/tasks/T-A1/execution-trace");
  });

  it("does not let a stale trace response overwrite the newly selected task", async () => {
    const traces = new Map<string, ReturnType<typeof deferred<Response>>>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/monitor")) return Promise.resolve(json(monitorSnapshot()));
        if (url.includes("/events/history")) return Promise.resolve(json([]));
        if (url.includes("/execution-trace")) {
          const code = url.includes("T-A1") ? "T-A1" : "T-B1";
          if (!traces.has(code)) traces.set(code, deferred<Response>());
          return traces.get(code)!.promise;
        }
        return Promise.resolve(json({}));
      }),
    );

    render(<RunMonitorPanel runId="r1" tasks={[]} />);
    fireEvent.click(await screen.findByText("T-A1"));
    await waitFor(() => expect(traces.has("T-A1")).toBe(true));

    fireEvent.click(screen.getByText("T-B1"));
    await waitFor(() => expect(traces.has("T-B1")).toBe(true));

    // The new task resolves first…
    await act(async () => {
      traces.get("T-B1")!.resolve(json(traceFor("T-B1", "T-B1-llm")));
      await traces.get("T-B1")!.promise;
    });
    expect(await screen.findByText(/#1 模型调用 · T-B1-llm/)).toBeTruthy();

    // …then the old task's delayed response arrives and must be ignored.
    await act(async () => {
      traces.get("T-A1")!.resolve(json(traceFor("T-A1", "T-A1-llm")));
      await traces.get("T-A1")!.promise;
    });

    expect(screen.getByText(/#1 模型调用 · T-B1-llm/)).toBeTruthy();
    expect(screen.queryByText(/#1 模型调用 · T-A1-llm/)).toBeNull();
    expect(screen.getByTestId("execution-trace").textContent).not.toContain("T-A1-llm");
    expect(screen.getByTestId("attempt-history").textContent).toContain("attempt-T-B1");
  });
});

describe("RunMonitorPanel assignment visibility (A4)", () => {
  function assignedSnapshot(): MonitorSnapshot {
    const base = monitorSnapshot();
    return {
      ...base,
      tasks: [
        task({ code: "T-A1", title: "实现登录", assignee_bot_id: "bot-a", assignee_display_name: "Member A" }),
        task({ code: "T-B1", title: "实现登出" }),
      ],
    };
  }

  function stubFetch(snapshot: MonitorSnapshot) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/monitor")) return json(snapshot);
        if (url.includes("/events/history")) return json([]);
        if (url.includes("/execution-trace")) return json({ run_id: "r1", task_code: "T-A1", role: "coder", execution_path: "", context_injected: false, current_attempt_id: "", attempts: [] });
        return json({});
      }),
    );
  }

  it("shows the assignee next to the role in task rows and the detail header", async () => {
    stubFetch(assignedSnapshot());
    render(<RunMonitorPanel runId="r1" tasks={[]} />);

    expect(await screen.findByTestId("monitor-task-assignee-T-A1")).toBeTruthy();
    expect(screen.getByTestId("monitor-task-assignee-T-A1").textContent).toContain("Member A");
    expect(screen.getByTestId("monitor-task-assignee-T-B1").textContent).toContain("未派发");

    fireEvent.click(screen.getByText("T-A1"));
    expect(await screen.findByTestId("monitor-detail-assignee")).toBeTruthy();
    expect(screen.getByTestId("monitor-detail-assignee").textContent).toContain("Member A");
    expect(screen.getByTestId("monitor-detail-role").textContent).toContain("coder");
    expect(screen.getByTestId("run-monitor").textContent).not.toContain("undefined");
  });

  it("adds an assigned-count KPI without replacing the completion KPI", async () => {
    stubFetch(assignedSnapshot());
    render(<RunMonitorPanel runId="r1" tasks={[]} />);
    const kpi = await screen.findByTestId("monitor-assigned-kpi");
    expect(kpi.textContent).toContain("1/2");
    expect(screen.getByTestId("monitor-kpis").textContent).toContain("任务进度");
  });

  it("labels task.assigned events in Chinese in the live feed", async () => {
    stubFetch(assignedSnapshot());
    render(<RunMonitorPanel runId="r1" tasks={[]} />);
    await screen.findByTestId("monitor-task-assignee-T-A1");
    const source = FakeEventSource.instances[0];
    act(() => {
      source.onmessage?.({ data: JSON.stringify({ seq: 1, kind: "task.assigned", subject: "T-A1", ts: "2026-11-26T10:00:00+00:00" }) });
    });
    expect(await screen.findByText("任务已派发")).toBeTruthy();
  });
});