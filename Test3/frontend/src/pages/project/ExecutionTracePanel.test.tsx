import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExecutionAttempt, ExecutionStep, ExecutionTrace } from "../../api/types";
import { ExecutionTracePanel } from "./ExecutionTracePanel";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const LLM_STEP: ExecutionStep = {
  step: 1,
  kind: "llm",
  name: "coder-gateway",
  status: "ok",
  started_at: "2026-11-24T09:00:00+00:00",
  ended_at: "2026-11-24T09:00:01+00:00",
  duration_ms: 850,
  model: "qwen-coder",
  slot: "coder",
  tokens_in: 1200,
  tokens_out: 340,
  finish_reason: "tool_calls",
  input_summary: "system:88 user:120 | last_user=实现登录",
  output_summary: "tool_calls: write_file",
  error: null,
  truncated: false,
};

const TOOL_STEP: ExecutionStep = {
  step: 2,
  kind: "tool",
  name: "write_file",
  status: "ok",
  started_at: "2026-11-24T09:00:01+00:00",
  ended_at: "2026-11-24T09:00:01+00:00",
  duration_ms: 120,
  model: "",
  slot: "",
  tokens_in: 0,
  tokens_out: 0,
  finish_reason: "",
  input_summary: "path=src/login.py; chars=42; sha256=abc123def456",
  output_summary: "ok=true; path=src/login.py",
  error: null,
  truncated: false,
};

const ATTEMPT: ExecutionAttempt = {
  attempt_id: "attempt-0001-aaaa",
  status: "finished_ok",
  started_at: "2026-11-24T09:00:00+00:00",
  ended_at: "2026-11-24T09:00:02+00:00",
  role: "coder",
  context_hash: "a".repeat(64),
  memory_context_hash: "b".repeat(64),
  manual_revision: 2,
  skill_bundle_hash: "c".repeat(64),
  commit: "d".repeat(40),
  context_injected: true,
  execution_path: "legacy_tool_agent",
  // Deliberately out of order: the panel must sort by `step` ascending.
  steps: [TOOL_STEP, LLM_STEP],
};

function traceOf(overrides: Partial<ExecutionTrace> = {}): ExecutionTrace {
  return {
    run_id: "r1",
    task_code: "T1",
    role: "coder",
    execution_path: "legacy_tool_agent",
    context_injected: true,
    current_attempt_id: ATTEMPT.attempt_id,
    attempts: [ATTEMPT],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ExecutionTracePanel", () => {
  it("loads the dedicated trace endpoint and renders llm + tool steps in ascending order", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return json(traceOf());
      }),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" role="coder" />);

    expect(await screen.findByText(/#1 模型调用/)).toBeTruthy();
    expect(urls).toContain("/api/runs/r1/tasks/T1/execution-trace");

    const items = screen.getAllByTestId(/^execution-step-\d+$/);
    expect(items.map((item) => item.getAttribute("data-testid"))).toEqual([
      "execution-step-1",
      "execution-step-2",
    ]);

    const llm = screen.getByTestId("execution-step-1");
    expect(llm.textContent).toContain("模型 qwen-coder");
    expect(llm.textContent).toContain("槽位 coder");
    expect(llm.textContent).toContain("Token 1200/340");
    expect(llm.textContent).toContain("finish_reason tool_calls");
    expect(llm.textContent).toContain("850ms");
    expect(screen.getByTestId("execution-step-input-1").textContent).toContain("last_user=实现登录");
    expect(screen.getByTestId("execution-step-output-1").textContent).toContain("tool_calls: write_file");

    const tool = screen.getByTestId("execution-step-2");
    expect(tool.textContent).toContain("工具调用");
    expect(tool.textContent).toContain("write_file");
    expect(tool.textContent).toContain("120ms");
    expect(screen.getByTestId("execution-step-input-2").textContent).toContain("path=src/login.py");
    expect(screen.getByTestId("execution-step-output-2").textContent).toContain("ok=true");
  });

  it("marks truncated summaries with 已截断", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          traceOf({
            attempts: [{ ...ATTEMPT, steps: [{ ...LLM_STEP, truncated: true }] }],
          }),
        ),
      ),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    expect(await screen.findByTestId("execution-step-truncated-1")).toBeTruthy();
    expect(screen.getByTestId("execution-step-truncated-1").textContent).toContain("已截断");
  });

  it("shows denied steps in the error tone and never swallows the error text", async () => {
    const denied: ExecutionStep = {
      ...TOOL_STEP,
      step: 1,
      status: "denied",
      error: "write_set 外路径 src/secret.py",
    };
    const failed: ExecutionStep = {
      ...TOOL_STEP,
      step: 2,
      name: "run_command",
      status: "error",
      error: "pytest failed",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(traceOf({ attempts: [{ ...ATTEMPT, steps: [denied, failed] }] }))),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const step = await screen.findByTestId("execution-step-1");
    expect(step.getAttribute("data-status")).toBe("denied");
    expect(screen.getByTestId("execution-step-status-1").textContent).toBe("被拒绝");
    expect(screen.getByTestId("execution-step-error-1").textContent).toContain(
      "write_set 外路径 src/secret.py",
    );

    // `error` (not only `denied`) is an error tone and its text stays visible too.
    expect(screen.getByTestId("execution-step-2").getAttribute("data-status")).toBe("error");
    expect(screen.getByTestId("execution-step-status-2").textContent).toBe("错误");
    expect(screen.getByTestId("execution-step-error-2").textContent).toContain("pytest failed");
  });

  it("renders granted command argv and exit output honestly", async () => {
    const command: ExecutionStep = {
      ...TOOL_STEP,
      step: 1,
      kind: "granted_command",
      name: "python -m pytest",
      status: "error",
      duration_ms: 2400,
      input_summary: "argv=python -m pytest -q",
      output_summary: "exit=1; output=FAILED tests/test_seats.py",
      error: "",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(traceOf({ attempts: [{ ...ATTEMPT, steps: [command] }] }))),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const panel = await screen.findByTestId("execution-step-1");
    expect(panel.textContent).toContain("授权命令");
    expect(panel.textContent).toContain("命令 / argv");
    expect(panel.textContent).toContain("退出码 / 输出");
    expect(screen.getByTestId("execution-step-input-1").textContent).toBe("argv=python -m pytest -q");
    expect(screen.getByTestId("execution-step-output-1").textContent).toContain("exit=1");
    expect(panel.textContent).toContain("2.4s");
  });

  it("always reports 费用：当前未计价 without inventing a cost", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(traceOf({ attempts: [], current_attempt_id: "", context_injected: false })),
      ),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    expect(await screen.findByTestId("execution-trace-cost")).toBeTruthy();
    expect(screen.getByTestId("execution-trace-cost").textContent).toBe("费用：当前未计价");
    expect(screen.getByTestId("execution-trace").textContent).not.toMatch(/费用[:：]\s*[¥￥$\d]/);
  });

  it("renders the exact empty state when the task never ran", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(traceOf({ attempts: [], current_attempt_id: "", context_injected: false }))),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const empty = await screen.findByTestId("execution-trace-empty");
    expect(empty.textContent).toBe(
      "该任务还没有执行步骤。scripted/开发任务开始执行后会显示模型与工具调用。",
    );
  });

  it("shows the last attempt that has steps when a new retry attempt has none yet", async () => {
    const liveAttempt: ExecutionAttempt = {
      ...ATTEMPT,
      attempt_id: "attempt-0002-live",
      status: "started",
      ended_at: null,
      steps: [],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          traceOf({
            current_attempt_id: liveAttempt.attempt_id,
            attempts: [ATTEMPT, liveAttempt],
          }),
        ),
      ),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    expect(await screen.findByText(/#1 模型调用 · coder-gateway/)).toBeTruthy();
    expect(screen.getByTestId("execution-trace").textContent).toContain(
      "当前尝试尚无步骤，显示最近一次有步骤的尝试",
    );
    expect(screen.queryByTestId("execution-trace-empty")).toBeNull();
  });

  it("states that context was only hashed (not injected) when context_injected is false, and shows no 已注入 badge", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          traceOf({
            context_injected: false,
            attempts: [{ ...ATTEMPT, context_injected: false, skill_bundle_hash: "" }],
          }),
        ),
      ),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const notice = await screen.findByTestId("execution-context-not-injected");
    expect(notice.textContent).toBe(
      "本尝试仅冻结上下文哈希，未向模型提示词注入任务上下文（路径：simulated / granted_v1）",
    );
    expect(screen.getByTestId("execution-trace").textContent).not.toContain("已注入");
    expect(screen.queryByTestId("execution-context-injected")).toBeNull();
  });

  it("warns that the public skill bundle is missing when injected but skill_bundle_hash is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          traceOf({
            attempts: [{ ...ATTEMPT, context_injected: true, skill_bundle_hash: "" }],
          }),
        ),
      ),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const notice = await screen.findByTestId("execution-context-injected");
    expect(notice.textContent).toBe("已注入角色/手动段；公共 skill 包未导入或加载失败");
  });

  it("reports a 404 with a short Chinese message but keeps the panel (and cost line) rendered", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "task not found" }, 404)),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    const error = await screen.findByTestId("execution-trace-error");
    expect(error.textContent).toContain("任务或运行不存在");
    expect(error.textContent).not.toContain("task not found");
    expect(screen.getByTestId("execution-trace-cost").textContent).toBe("费用：当前未计价");
  });

  it("reports a network failure in Chinese", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    expect(await screen.findByTestId("execution-trace-error")).toHaveProperty("textContent");
    expect(screen.getByTestId("execution-trace-error").textContent).toContain(
      "执行轨迹加载失败，请检查网络或后端是否可用。",
    );
  });

  it("keeps the last successful steps when a refresh fails", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) return json(traceOf());
        throw new TypeError("Failed to fetch");
      }),
    );

    const view = render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    await screen.findByText(/#1 模型调用/);

    view.rerender(<ExecutionTracePanel runId="r1" taskCode="T1" refreshToken={1} />);
    const error = await screen.findByTestId("execution-trace-error");
    expect(error.textContent).toContain("执行轨迹加载失败");
    expect(error.textContent).toContain("已保留上一次成功加载的步骤");
    // Old steps are still there: the panel does not go blank on a failed refresh.
    expect(screen.getByText(/#1 模型调用/)).toBeTruthy();
    expect(screen.getByText(/#2 工具调用/)).toBeTruthy();
  });

  it("ignores a stale response when the run changes before it resolves", async () => {
    const stale = deferred<Response>();
    const fresh = deferred<Response>();
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        return url.includes("/runs/r-old/") ? stale.promise : fresh.promise;
      }),
    );

    const view = render(<ExecutionTracePanel runId="r-old" taskCode="T1" />);
    view.rerender(<ExecutionTracePanel runId="r-new" taskCode="T1" />);
    await waitFor(() => expect(urls).toContain("/api/runs/r-new/tasks/T1/execution-trace"));

    await act(async () => {
      fresh.resolve(
        json(
          traceOf({
            run_id: "r-new",
            attempts: [{ ...ATTEMPT, steps: [{ ...LLM_STEP, name: "新 run 模型" }] }],
          }),
        ),
      );
      await fresh.promise;
    });
    expect(await screen.findByText(/#1 模型调用 · 新 run 模型/)).toBeTruthy();

    // The old run's response resolves last: it must not overwrite the new run.
    await act(async () => {
      stale.resolve(
        json(
          traceOf({
            run_id: "r-old",
            attempts: [{ ...ATTEMPT, steps: [{ ...LLM_STEP, name: "旧 run 模型" }] }],
          }),
        ),
      );
      await stale.promise;
    });

    expect(screen.getByText(/#1 模型调用 · 新 run 模型/)).toBeTruthy();
    expect(screen.queryByText(/#1 模型调用 · 旧 run 模型/)).toBeNull();
  });
});

/** Capture object-URL downloads without a real browser (same idea as downloadCsv). */
function stubDownloads() {
  const blobs: Blob[] = [];
  const contents: string[] = [];
  const clicks: Array<{ download: string; href: string }> = [];
  // jsdom's Blob has no .text(); capture the constructor payload instead.
  class CapturingBlob extends Blob {
    constructor(parts: BlobPart[], options?: BlobPropertyBag) {
      super(parts, options);
      contents.push(parts.map(String).join(""));
    }
  }
  vi.stubGlobal("Blob", CapturingBlob);
  const createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    return `blob:mock-${blobs.length}`;
  });
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push({ download: this.download, href: this.href });
  });
  return { blobs, contents, clicks, createObjectURL, revokeObjectURL };
}

describe("ExecutionTracePanel observation styles", () => {
  it("defaults to the timeline and switches views without any new network request", async () => {
    const fetchMock = vi.fn(async () => json(traceOf()));
    vi.stubGlobal("fetch", fetchMock);

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    expect(await screen.findByTestId("execution-step-1")).toBeTruthy();
    expect(screen.getByTestId("observation-style-switch")).toBeTruthy();
    expect(screen.getByTestId("observation-style-option-timeline").getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByTestId("observation-table")).toBeNull();

    fireEvent.click(screen.getByTestId("observation-style-option-table"));
    const table = screen.getByTestId("observation-table");
    for (const column of ["step", "kind", "name", "status", "duration_ms", "input_summary", "output_summary", "error"]) {
      expect(table.textContent).toContain(column);
    }
    expect(table.textContent).toContain("coder-gateway");
    expect(screen.queryByTestId("execution-step-1")).toBeNull();
    // The honest context banner stays visible in every style.
    expect(screen.getByTestId("execution-context-state")).toBeTruthy();

    fireEvent.click(screen.getByTestId("observation-style-option-json"));
    const jsonText = screen.getByTestId("observation-json").textContent || "";
    expect(JSON.parse(jsonText)).toEqual(traceOf());
    expect(screen.queryByTestId("observation-table")).toBeNull();

    fireEvent.click(screen.getByTestId("observation-style-option-markdown"));
    const mdText = screen.getByTestId("observation-markdown").textContent || "";
    expect(mdText).toContain("execution_path");
    expect(mdText).toContain("coder-gateway");
    expect(screen.queryByTestId("observation-json")).toBeNull();

    fireEvent.click(screen.getByTestId("observation-style-option-timeline"));
    expect(screen.getByTestId("execution-step-1")).toBeTruthy();
    expect(screen.getByTestId("execution-step-2")).toBeTruthy();

    // Style switching is pure front-end state: exactly one trace request.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("exports the current style with runId/taskCode/style in the filename", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(traceOf())));
    const { blobs, contents, clicks } = stubDownloads();

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    await screen.findByTestId("execution-step-1");

    const exportButton = screen.getByTestId("observation-export");
    expect(exportButton.hasAttribute("disabled")).toBe(false);

    fireEvent.click(exportButton);
    expect(clicks[0].download).toBe("trace-r1-T1-timeline.md");

    fireEvent.click(screen.getByTestId("observation-style-option-table"));
    fireEvent.click(exportButton);
    expect(clicks[1].download).toBe("trace-r1-T1-table.csv");
    expect(contents[1]).toContain("duration_ms");
    expect(blobs[1].type).toContain("text/csv");

    fireEvent.click(screen.getByTestId("observation-style-option-json"));
    fireEvent.click(exportButton);
    expect(clicks[2].download).toBe("trace-r1-T1-json.json");
    expect(JSON.parse(contents[2])).toEqual(traceOf());
    expect(blobs[2].type).toContain("application/json");

    fireEvent.click(screen.getByTestId("observation-style-option-markdown"));
    fireEvent.click(exportButton);
    expect(clicks[3].download).toBe("trace-r1-T1-markdown.md");
    expect(blobs[3].type).toContain("text/markdown");
  });

  it("keeps the export disabled and shows only the empty state when the trace has no steps", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(traceOf({ attempts: [], current_attempt_id: "", context_injected: false }))),
    );
    const { clicks } = stubDownloads();

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    await screen.findByTestId("execution-trace-empty");
    expect(screen.getByTestId("observation-export").hasAttribute("disabled")).toBe(true);

    for (const style of ["table", "json", "markdown", "timeline"] as const) {
      fireEvent.click(screen.getByTestId(`observation-style-option-${style}`));
      expect(screen.getByTestId("execution-trace-empty")).toBeTruthy();
      expect(screen.getByTestId("observation-export").hasAttribute("disabled")).toBe(true);
      expect(screen.queryByTestId("observation-table")).toBeNull();
      expect(screen.queryByTestId("observation-json")).toBeNull();
      expect(screen.queryByTestId("observation-markdown")).toBeNull();
    }
    expect(clicks.length).toBe(0);
  });

  it("never restores redacted secrets in any rendered style", async () => {
    const redacted: ExecutionStep = {
      ...LLM_STEP,
      input_summary: "api_key=***REDACTED***; last_user=实现登录",
      output_summary: "key=sk-***REDACTED***",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(traceOf({ attempts: [{ ...ATTEMPT, steps: [redacted] }] }))),
    );

    render(<ExecutionTracePanel runId="r1" taskCode="T1" />);
    await screen.findByTestId("execution-step-1");

    for (const style of ["timeline", "table", "json", "markdown"] as const) {
      fireEvent.click(screen.getByTestId(`observation-style-option-${style}`));
      const text = screen.getByTestId("execution-trace").textContent || "";
      expect(text).toContain("***REDACTED***");
      expect(text).not.toMatch(/sk-[A-Za-z0-9_-]{8,}/);
    }
  });
});