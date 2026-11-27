import { describe, expect, it } from "vitest";
import type { MonitorAgent, MonitorSnapshot, MonitorTask } from "../../api/types";
import { agentsToCsv, buildMonitorGroups, eventLabel, fallbackMonitorTasks, formatDuration } from "./runMonitor";

function task(overrides: Partial<MonitorTask>): MonitorTask {
  return {
    code: "T-01",
    title: "任务",
    state: "pending",
    status: "pending",
    role: "coder",
    slot: "coder",
    model: "qwen-coder",
    module: "M1",
    parent: "W1",
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
    execution_path: "",
    context_injected: false,
    execution_step_count: 0,
    last_execution_step: null,
    assignee_bot_id: null,
    assignee_display_name: null,
    ...overrides,
  };
}

const snapshot: MonitorSnapshot = {
  generated_at: "2026-11-24T10:00:00+00:00",
  run: {
    id: "run-1",
    project_id: "p-1",
    status: "active",
    stage: "7",
    paused: false,
    revision: 1,
    tokens_used: 100,
    event_count: 3,
    task_count: 3,
    state_counts: { ready: 1, running: 1, done: 1 },
    total: 3,
    done: 1,
    running: 1,
    failed: 0,
    blocked: 0,
    pending: 1,
    skipped: 0,
    progress: 33,
    repair_rounds: 0,
    fallback_count: 0,
    fallback_by_slot: {},
    first_event_at: "",
    last_event_at: "",
    elapsed_seconds: 10,
  },
  work_packages: [
    { code: "W1", title: "登录", module: "M1", total: 2, done: 1, running: 1, failed: 0, blocked: 0, pending: 0, skipped: 0, progress: 50 },
    { code: "W2", title: "验收", module: "M2", total: 1, done: 0, running: 0, failed: 0, blocked: 0, pending: 1, skipped: 0, progress: 0 },
  ],
  tasks: [
    task({ code: "W1-01", status: "done", state: "done" }),
    task({ code: "W1-02", status: "running", state: "running" }),
    task({ code: "W2-01", status: "pending", state: "ready", parent: "W2" }),
  ],
  agents: [],
};

describe("monitor grouping", () => {
  it("groups by work package and filters running tasks", () => {
    const groups = buildMonitorGroups(snapshot, [], "running");
    expect(groups).toHaveLength(1);
    expect(groups[0].code).toBe("W1");
    expect(groups[0].tasks.map((item) => item.code)).toEqual(["W1-02"]);
  });

  it("keeps all package groups when no filter is active", () => {
    const groups = buildMonitorGroups(snapshot, [], "all");
    expect(groups.map((item) => item.code)).toEqual(["W1", "W2"]);
    expect(groups[0].progress).toBe(50);
  });

  it("maps fallback task states to monitor statuses", () => {
    const rows = fallbackMonitorTasks([{ code: "T-1", title: "x", progress: 40, status: "needs_human" }]);
    expect(rows[0].status).toBe("failed");
  });

  it("keeps fallback rows honestly unassigned (A4)", () => {
    const rows = fallbackMonitorTasks([{ code: "T-1", title: "x", progress: 0, status: "ready" }]);
    expect(rows[0].assignee_bot_id).toBeNull();
    expect(rows[0].assignee_display_name).toBeNull();
  });

  it("labels the assignment events in Chinese (A4)", () => {
    expect(eventLabel("task.assigned")).toBe("任务已派发");
    expect(eventLabel("task.assignment_cleared")).toBe("已取消派发");
  });

  it("formats durations", () => {
    expect(formatDuration(8)).toBe("8s");
    expect(formatDuration(65)).toBe("1m 5s");
    expect(formatDuration(null)).toBe("—");
  });
});

describe("agent CSV export", () => {
  it("escapes commas, quotes and joins failure reasons", () => {
    const agents: MonitorAgent[] = [
      {
        role: "coder",
        slot: "coder",
        model: "qwen,coder",
        total: 2,
        done: 1,
        failed: 1,
        running: 0,
        blocked: 0,
        pending: 0,
        success_rate: 50,
        completion_rate: 50,
        tokens_used: 1200,
        avg_repair_rounds: 1.5,
        avg_task_seconds: 12,
        fallback_count: 1,
        failure_reasons: [{ reason: '测试"失败"', count: 1 }],
      },
    ];
    const csv = agentsToCsv(agents);
    expect(csv.split("\r\n")[0]).toContain("成功率(%)");
    expect(csv).toContain('"qwen,coder"');
    expect(csv).toContain('"测试""失败""×1"');
  });
});