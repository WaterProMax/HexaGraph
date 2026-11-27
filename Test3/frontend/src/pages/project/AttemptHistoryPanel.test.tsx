import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExecutionAttempt, ExecutionStep, ExecutionTrace } from "../../api/types";
import { AttemptHistoryPanel } from "./AttemptHistoryPanel";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function step(overrides: Partial<ExecutionStep>): ExecutionStep {
  return {
    step: 1,
    kind: "llm",
    name: "coder-gateway",
    status: "ok",
    started_at: "2026-11-24T09:00:00+00:00",
    ended_at: "2026-11-24T09:00:01+00:00",
    duration_ms: 800,
    model: "qwen-coder",
    slot: "coder",
    tokens_in: 1,
    tokens_out: 1,
    finish_reason: "stop",
    input_summary: "user:10",
    output_summary: "text: ok",
    error: null,
    truncated: false,
    ...overrides,
  };
}

const ATTEMPT_ONE: ExecutionAttempt = {
  attempt_id: "attempt-0001-aaaa",
  status: "finished_failed",
  started_at: "2026-11-24T09:00:00+00:00",
  ended_at: "2026-11-24T09:05:00+00:00",
  role: "coder",
  context_hash: "a".repeat(64),
  memory_context_hash: "b".repeat(64),
  manual_revision: 3,
  skill_bundle_hash: "",
  commit: "1".repeat(40),
  context_injected: false,
  execution_path: "granted_v1",
  steps: [step({ step: 1, status: "denied", error: "权限不足" })],
};

const ATTEMPT_TWO: ExecutionAttempt = {
  attempt_id: "attempt-0002-bbbb",
  status: "started",
  started_at: "2026-11-24T10:00:00+00:00",
  ended_at: null,
  role: "coder",
  context_hash: "c".repeat(64),
  memory_context_hash: "d".repeat(64),
  manual_revision: 4,
  skill_bundle_hash: "e".repeat(64),
  commit: "",
  context_injected: true,
  execution_path: "legacy_tool_agent",
  steps: [step({ step: 1 }), step({ step: 2, kind: "tool", name: "write_file" })],
};

const ATTEMPT_THREE: ExecutionAttempt = {
  attempt_id: "attempt-0003-cccc",
  status: "started",
  started_at: "2026-11-24T11:00:00+00:00",
  ended_at: null,
  role: "coder",
  context_hash: "f".repeat(64),
  memory_context_hash: "0".repeat(64),
  manual_revision: 5,
  skill_bundle_hash: "e".repeat(64),
  commit: "",
  context_injected: true,
  execution_path: "legacy_tool_agent",
  steps: [],
};

function traceOf(overrides: Partial<ExecutionTrace> = {}): ExecutionTrace {
  return {
    run_id: "r1",
    task_code: "T1",
    role: "coder",
    execution_path: "legacy_tool_agent",
    context_injected: true,
    current_attempt_id: ATTEMPT_TWO.attempt_id,
    attempts: [ATTEMPT_ONE, ATTEMPT_TWO],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AttemptHistoryPanel", () => {
  it("loads the trace endpoint and shows both attempts with status, time range and step count", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return json(traceOf());
      }),
    );

    render(<AttemptHistoryPanel runId="r1" taskCode="T1" role="coder" />);

    expect(await screen.findByText(/2 次尝试/)).toBeTruthy();
    expect(urls).toContain("/api/runs/r1/tasks/T1/execution-trace");

    const oldToggle = screen.getByTestId(`attempt-toggle-${ATTEMPT_ONE.attempt_id}`);
    const currentToggle = screen.getByTestId(`attempt-toggle-${ATTEMPT_TWO.attempt_id}`);
    expect(oldToggle.textContent).toContain("失败");
    expect(oldToggle.textContent).toContain("2026-11-24 09:00:00 → 2026-11-24 09:05:00");
    expect(oldToggle.textContent).toContain("1 步");
    expect(currentToggle.textContent).toContain("执行中");
    expect(currentToggle.textContent).toContain("当前尝试");
    expect(currentToggle.textContent).toContain("2026-11-24 10:00:00 → 进行中");
    expect(currentToggle.textContent).toContain("2 步");
  });

  it("collapses old attempts by default and expands them with the frozen hashes on demand", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(traceOf())));
    render(<AttemptHistoryPanel runId="r1" taskCode="T1" />);

    // Current attempt is open by default: its frozen hashes are visible.
    expect(await screen.findByTestId(`attempt-detail-${ATTEMPT_TWO.attempt_id}`)).toBeTruthy();
    expect(screen.getByTestId(`attempt-detail-${ATTEMPT_TWO.attempt_id}`).textContent).toContain(
      "cccccccccccc",
    );
    // Old attempt is collapsed: it has no visible detail yet.
    expect(screen.queryByTestId(`attempt-detail-${ATTEMPT_ONE.attempt_id}`)).toBeNull();
    expect(screen.queryByText("aaaaaaaaaaaa")).toBeNull();

    fireEvent.click(screen.getByTestId(`attempt-toggle-${ATTEMPT_ONE.attempt_id}`));
    const oldDetail = screen.getByTestId(`attempt-detail-${ATTEMPT_ONE.attempt_id}`);
    expect(oldDetail.textContent).toContain("aaaaaaaaaaaa");
    expect(oldDetail.textContent).toContain("bbbbbbbbbbbb");
    expect(oldDetail.textContent).toContain("111111111111");
    expect(oldDetail.textContent).toContain("manual_revision");
    expect(oldDetail.textContent).toContain("3");
    expect(oldDetail.textContent).toContain("未注入（仅冻结哈希）");
    expect(oldDetail.textContent).toContain("granted_v1");
  });

  it("shows the same field rows for two attempts so their frozen values can be compared", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(traceOf())));
    render(<AttemptHistoryPanel runId="r1" taskCode="T1" />);
    await screen.findByTestId(`attempt-detail-${ATTEMPT_TWO.attempt_id}`);
    fireEvent.click(screen.getByTestId(`attempt-toggle-${ATTEMPT_ONE.attempt_id}`));

    const oldDetail = within(screen.getByTestId(`attempt-detail-${ATTEMPT_ONE.attempt_id}`));
    const currentDetail = within(screen.getByTestId(`attempt-detail-${ATTEMPT_TWO.attempt_id}`));
    for (const label of ["context_hash", "memory_context_hash", "manual_revision", "context_injected", "step 数"]) {
      expect(oldDetail.getByText(label)).toBeTruthy();
      expect(currentDetail.getByText(label)).toBeTruthy();
    }
    // Step counts differ and are shown as recorded.
    expect(oldDetail.getByText("1 步")).toBeTruthy();
    expect(currentDetail.getByText("2 步")).toBeTruthy();
    // Distinct frozen hashes prove the two attempts are not showing a shared live value.
    expect(oldDetail.getByText("aaaaaaaaaaaa")).toBeTruthy();
    expect(currentDetail.getByText("cccccccccccc")).toBeTruthy();
  });

  it("keeps old attempt values frozen when the selection moves on (never labelled as being edited)", async () => {
    const { rerender } = render(
      <AttemptHistoryPanel
        runId="r1"
        taskCode="T1"
        attempts={[ATTEMPT_ONE, ATTEMPT_TWO]}
        currentAttemptId={ATTEMPT_TWO.attempt_id}
      />,
    );
    // The old attempt is collapsed; expand it to read its frozen values.
    fireEvent.click(screen.getByTestId(`attempt-toggle-${ATTEMPT_ONE.attempt_id}`));
    expect(screen.getByTestId(`attempt-detail-${ATTEMPT_ONE.attempt_id}`).textContent).toContain(
      "aaaaaaaaaaaa",
    );

    // A newer attempt arrives (selection moves on); the old attempt keeps the
    // values frozen when it ended, including its own manual revision.
    rerender(
      <AttemptHistoryPanel
        runId="r1"
        taskCode="T1"
        attempts={[ATTEMPT_ONE, ATTEMPT_TWO, ATTEMPT_THREE]}
        currentAttemptId={ATTEMPT_THREE.attempt_id}
      />,
    );
    const oldDetail = screen.getByTestId(`attempt-detail-${ATTEMPT_ONE.attempt_id}`);
    expect(oldDetail.textContent).toContain("aaaaaaaaaaaa");
    expect(oldDetail.textContent).toContain("未注入（仅冻结哈希）");
    expect(oldDetail.textContent).toContain("冻结值");
    // The old attempt still reports revision 3, not the newer revision 5.
    expect(oldDetail.textContent).toContain("3");
    expect(screen.getByTestId("attempt-history").textContent).toContain("不是正在编辑的记忆");
    expect(screen.getByTestId("attempt-history").textContent).not.toContain("编辑中");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("reports a load failure in Chinese while keeping the panel rendered", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "task not found" }, 404)),
    );
    render(<AttemptHistoryPanel runId="r1" taskCode="T1" />);
    const error = await screen.findByTestId("attempt-history-error");
    expect(error.textContent).toContain("任务或运行不存在");
    expect(error.textContent).not.toContain("task not found");
    expect(screen.getByTestId("attempt-history")).toBeTruthy();
  });
});