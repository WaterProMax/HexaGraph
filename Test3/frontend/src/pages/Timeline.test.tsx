import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { eventSummary, eventTaskCode, stepSummary, type TimelineEvent } from "./project/eventTimeline";
import { RunEventTimeline } from "./project/RunEventTimeline";

const EVENTS: TimelineEvent[] = [
  {
    seq: 1,
    kind: "task.tool_step",
    subject: "T-01",
    payload: { name: "read_file", duration_ms: 12, input_summary: "读取 src/login.ts" },
  },
  {
    seq: 2,
    kind: "task.llm_step",
    subject: "T-02",
    payload: { input_summary: "实现登录逻辑" },
  },
  {
    seq: 3,
    kind: "task.state_changed",
    subject: "T-01",
    payload: { state: "running" },
  },
  {
    seq: 4,
    kind: "task.tool_step",
    subject: "T-03",
    payload: { name: "write_file", duration_ms: 34 },
  },
];

function Harness({
  events = EVENTS,
  connection = "live" as const,
  connectionError = "",
  reconnect = vi.fn(),
}: {
  events?: TimelineEvent[];
  connection?: "idle" | "connecting" | "live" | "error";
  connectionError?: string;
  reconnect?: () => void;
}) {
  const [filter, setFilter] = useState("");
  return (
    <RunEventTimeline
      events={events}
      connection={connection}
      connectionError={connectionError}
      reconnect={reconnect}
      taskFilter={filter}
      onTaskFilterChange={setFilter}
    />
  );
}

function renderTimeline(overrides: Parameters<typeof Harness>[0] = {}) {
  return render(<Harness {...overrides} />);
}

afterEach(cleanup);

describe("RunEventTimeline", () => {
  it("renders step events with Chinese labels and a payload summary", () => {
    renderTimeline();

    const labels = screen.getAllByTestId("timeline-event-label").map((node) => node.textContent);
    expect(labels).toContain("工具步骤");
    expect(labels).toContain("模型步骤");
    // Non-step events keep their existing Chinese label.
    expect(labels).toContain("任务状态");

    const summaries = screen.getAllByTestId("timeline-event-summary").map((node) => node.textContent);
    expect(summaries).toContain("读取 src/login.ts");
    expect(summaries).toContain("实现登录逻辑");
    // Without input_summary the summary falls back to name + duration_ms.
    expect(summaries).toContain("write_file · 34ms");
  });

  it("filters events by task code derived from the event subject", () => {
    renderTimeline();

    expect(screen.getAllByTestId("timeline-event")).toHaveLength(4);
    fireEvent.change(screen.getByLabelText("按任务代码过滤"), { target: { value: "T-01" } });

    const rows = screen.getAllByTestId("timeline-event");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.getAttribute("data-task-code")).toBe("T-01");
      expect(within(row).queryByText("T-02")).toBeNull();
    }
    expect(screen.queryByText("实现登录逻辑")).toBeNull();
    expect(screen.getByTestId("timeline-count").textContent).toContain("T-01");
  });

  it("shows an empty filter result instead of a blank panel", () => {
    renderTimeline();
    fireEvent.change(screen.getByLabelText("按任务代码过滤"), { target: { value: "T-99" } });
    expect(screen.getByTestId("timeline-empty").textContent).toContain("没有匹配该任务代码的事件");
  });

  it("keeps the disconnect notice and reconnect action", () => {
    const reconnect = vi.fn();
    renderTimeline({ connection: "error", connectionError: "事件连接已断开，可重新连接并同步当前状态", reconnect });

    expect(screen.getByTestId("timeline-connection-error").textContent).toContain("事件连接已断开");
    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(reconnect).toHaveBeenCalledTimes(1);
  });

  it("keeps every event instead of capping the list at 20 rows", () => {
    const many: TimelineEvent[] = Array.from({ length: 25 }, (_, index) => ({
      seq: index + 1,
      kind: "task.state_changed",
      subject: "T-01",
      payload: { state: "running" },
    }));
    renderTimeline({ events: many });

    expect(screen.getAllByTestId("timeline-event")).toHaveLength(25);
    expect(screen.getByTestId("timeline-count").textContent).toContain("共 25 条");
    // The earliest event is still rendered (the old activity feed kept only the last 20).
    expect(screen.getByText("#1")).toBeTruthy();
  });

  it("keeps control/rejection reasons in the summary instead of dropping them", () => {
    const rejected: TimelineEvent = {
      seq: 9,
      kind: "task.schedule_rejected",
      subject: "T-02",
      payload: { category: "profile_not_granted_v1", detail: "缺少执行授权" },
    };
    renderTimeline({ events: [rejected] });

    expect(screen.getByTestId("timeline-event-summary").textContent).toContain(
      "profile_not_granted_v1 · 缺少执行授权",
    );
  });

  it("computes task codes, step summaries and the richer event summary defensively", () => {
    expect(eventTaskCode({ subject: " T-01 " })).toBe("T-01");
    expect(eventTaskCode({ payload: { task_code: "T-02" } })).toBe("T-02");
    expect(eventTaskCode({})).toBe("");
    expect(stepSummary("task.state_changed", { name: "x" })).toBe("");
    expect(stepSummary("task.llm_step", { input_summary: "a".repeat(200) })).toHaveLength(121);
    expect(stepSummary("task.llm_step", null)).toBe("");
    expect(eventSummary("task.schedule_rejected", { category: "c", detail: "d" })).toBe("c · d");
    expect(eventSummary("task.llm_step", { input_summary: "步骤" })).toBe("步骤");
    expect(eventSummary("task.state_changed", {})).toBe("");
  });
});