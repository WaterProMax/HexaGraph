import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { message } from "antd";
import Workstation from "./Workstation";

const api = vi.hoisted(() => ({
  runs: vi.fn(),
  run: vi.fn(),
  artifacts: vi.fn(),
  tasks: vi.fn(),
  budget: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  resolveGate: vi.fn(),
  schedule: vi.fn(),
  createProject: vi.fn(),
  createDesignRun: vi.fn(),
  terminate: vi.fn(),
  health: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api,
  controlEnabled: () => true,
}));

vi.mock("../hooks/useRunEvents", () => ({
  useRunEvents: () => ({
    events: [],
    connection: "live",
    connectionError: "",
    reconnect: vi.fn(),
  }),
}));

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: ReactNode }) => <div data-testid="flow">{children}</div>,
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Left: "left", Right: "right" },
  useReactFlow: () => ({ fitView: vi.fn() }),
}));

const DEFAULT_IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";

function designRun(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    project_id: "proj-1",
    origin: "design_spec",
    status: "waiting",
    stage: "5",
    paused: false,
    idea: "自习室规格",
    gates: [{ id: "gate-1", kind: "DESIGN基线确认", status: "pending", payload: {} }],
    ...overrides,
  };
}

function designArtifacts(overrides: Record<string, unknown> = {}) {
  return {
    design_input_status: "awaiting_confirmation",
    design_input: {
      title: "自习室规格",
      text: "目标：学生查看空闲座位。",
      source: { kind: "file", name: "study.md" },
    },
    ...overrides,
  };
}

function renderWorkstation(path = "/workstation/run-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/workstation/:id?" element={<Workstation />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function hiddenOrDisabled(name: string) {
  const el = screen.queryByRole("button", { name, hidden: true });
  return el == null || (el as HTMLButtonElement).disabled;
}

function runPauseResume() {
  return screen.queryByTestId("run-pause-resume");
}

beforeEach(() => {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  api.runs.mockReset().mockResolvedValue([]);
  api.run.mockReset().mockResolvedValue(designRun());
  api.artifacts.mockReset().mockResolvedValue(designArtifacts());
  api.tasks.mockReset().mockResolvedValue([]);
  api.budget.mockReset().mockResolvedValue({ used: 0, limit: 1 });
  api.pauseRun.mockReset().mockResolvedValue({ paused: true });
  api.resumeRun.mockReset().mockResolvedValue({ paused: false });
  api.resolveGate.mockReset().mockResolvedValue({ ok: true });
  api.schedule.mockReset().mockResolvedValue({ started: [] });
  api.createProject.mockReset().mockResolvedValue({ id: "proj-new" });
  api.createDesignRun.mockReset().mockResolvedValue({ run_id: "run-2", status: "importing", project_id: "proj-1" });
  api.health.mockReset().mockResolvedValue({ status: "ok", schedule_mode: "manual" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Workstation design-spec entry", () => {
  it("opens a design_spec run on 从设计规格开始 without the idea-composer default", async () => {
    renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("design-spec-input")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "设计规格输入" })).toBeTruthy();
    expect(screen.queryByLabelText("产品想法")).toBeNull();
    expect(screen.queryByDisplayValue(DEFAULT_IDEA)).toBeNull();
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("目标：学生查看空闲座位。");
    expect((screen.getByLabelText("设计规格标题") as HTMLInputElement).value).toBe("自习室规格");
  });

  it("does not flash the idea composer while a design_spec run is still loading", async () => {
    let resolveRun: ((value: unknown) => void) | undefined;
    api.run.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      }),
    );
    renderWorkstation();
    expect(screen.queryByLabelText("产品想法")).toBeNull();
    expect(screen.queryByDisplayValue(DEFAULT_IDEA)).toBeNull();
    await act(async () => {
      resolveRun?.(designRun());
    });
    await waitFor(() => expect(screen.getByTestId("design-spec-input")).toBeTruthy());
    expect(screen.queryByDisplayValue(DEFAULT_IDEA)).toBeNull();
  });

  it("reuses the current project when resubmitting a failed design-spec run", async () => {
    api.artifacts.mockResolvedValue(
      designArtifacts({ design_input_status: "failed", design_input_error_category: "timeout" }),
    );
    api.run.mockResolvedValue(designRun({ status: "stopped", gates: [] }));
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("button", { name: "修改原文后重新提交" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "修改原文后重新提交" }));
    await waitFor(() => expect(api.createDesignRun).toHaveBeenCalled());
    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.createDesignRun.mock.calls[0][0]).toBe("proj-1");
  });

  it("keeps 整理并检查 disabled after navigate while the new run is still importing", async () => {
    let resolveArtifacts: ((value: unknown) => void) | undefined;
    api.artifacts.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveArtifacts = resolve;
        }),
    );
    api.run.mockImplementation(async (id?: string) => {
      if (id === "run-2") return designRun({ id: "run-2", idea: "新导入规格", gates: [] });
      return designRun();
    });

    renderWorkstation("/workstation");
    fireEvent.click(screen.getByText("从设计规格开始"));
    await waitFor(() => expect(screen.getByTestId("design-spec-input")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("设计规格原文"), {
      target: { value: "目标：学生查看空闲座位。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "整理并检查" }));

    await waitFor(() => expect(api.createDesignRun).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("新导入规格")).toBeTruthy());
    expect(resolveArtifacts).toBeDefined();
    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Workstation buttons follow backend status", () => {
  it.each(["stopped", "terminated", "done"])("does not offer pause or resume when the run is %s", async (status) => {
    api.run.mockResolvedValue(designRun({ status, gates: [], paused: false }));
    renderWorkstation();
    await waitFor(() => expect(document.querySelector(".topbar-right")).toBeTruthy());
    expect(document.querySelector(".topbar-right")?.textContent).toMatch(
      status === "done" ? /已完成/ : status === "stopped" ? /已停止/ : /已终止/,
    );
    expect(runPauseResume()).toBeNull();
    expect(hiddenOrDisabled("暂停")).toBe(true);
    expect(hiddenOrDisabled("恢复")).toBe(true);
  });

  it("shows resume and keeps schedule disabled while paused", async () => {
    api.run.mockResolvedValue(designRun({ paused: true, stage: "7", gates: [] }));
    api.tasks.mockResolvedValue([{ code: "T-01", state: "ready", revision: 1 }]);
    renderWorkstation();
    await waitFor(() => expect(runPauseResume()).toBeTruthy());
    expect(runPauseResume()?.getAttribute("aria-label")).toBe("恢复");
    expect((runPauseResume() as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("run-pause-resume")?.textContent).toContain("恢复");
    const schedule = screen.getByRole("button", { name: "调度执行" });
    expect((schedule as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "立即调度" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("locks approve and reject together while a gate request is pending", async () => {
    let finish: ((value: unknown) => void) | undefined;
    api.resolveGate.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("button", { name: "批准并推进" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "批准并推进" }));
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "批准并推进" }) as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByRole("button", { name: /驳回/ }) as HTMLButtonElement).disabled).toBe(true);
    });
    await act(async () => {
      finish?.({ ok: true });
    });
  });

  it("does not auto-approve while gates are locked for import", async () => {
    api.artifacts.mockResolvedValue(designArtifacts({ design_input_status: "importing" }));
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("switch", { name: "自动过关" })).toBeTruthy());
    fireEvent.click(screen.getByRole("switch", { name: "自动过关" }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 800));
    });
    expect(api.resolveGate).not.toHaveBeenCalled();
  });

  it("does not allow approve or schedule while importing", async () => {
    api.run.mockResolvedValue(designRun({ stage: "7" }));
    api.artifacts.mockResolvedValue(designArtifacts({ design_input_status: "importing" }));
    api.tasks.mockResolvedValue([{ code: "T-01", state: "ready", revision: 1 }]);
    renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("design-spec-input")).toBeTruthy());
    expect((screen.getByRole("button", { name: "批准并推进" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /驳回/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /调度执行/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "整理并检查" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns when the run status query fails and does not offer pause or approve", async () => {
    api.run.mockRejectedValue(new Error("状态不可用"));
    renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("run-status-error")).toBeTruthy());
    expect(screen.getByTestId("run-status-error").textContent).toMatch(/状态查询失败/);
    expect(runPauseResume()).toBeNull();
    expect(hiddenOrDisabled("暂停")).toBe(true);
    expect(hiddenOrDisabled("恢复")).toBe(true);
    expect(screen.queryByRole("button", { name: "批准并推进" })).toBeNull();
  });

  it("shows failure feedback for pause and does not pretend the run paused", async () => {
    const errorSpy = vi.spyOn(message, "error");
    const successSpy = vi.spyOn(message, "success");
    api.pauseRun.mockRejectedValue(new Error("暂停被拒绝"));
    renderWorkstation();
    await waitFor(() => expect(runPauseResume()).toBeTruthy());
    fireEvent.click(runPauseResume()!);
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(String(errorSpy.mock.calls[0][0])).toMatch(/暂停失败|暂停被拒绝/);
    expect(successSpy).not.toHaveBeenCalled();
    expect(screen.queryByText("已暂停")).toBeNull();
  });

  it("shows success feedback for pause, resume, approve, and reject", async () => {
    const successSpy = vi.spyOn(message, "success");
    renderWorkstation();
    await waitFor(() => expect(runPauseResume()).toBeTruthy());
    fireEvent.click(runPauseResume()!);
    await waitFor(() => expect(successSpy.mock.calls.some((call) => String(call[0]).includes("已暂停"))).toBe(true));

    api.run.mockResolvedValue(designRun({ paused: true }));
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(runPauseResume()?.getAttribute("aria-label")).toBe("恢复"));
    fireEvent.click(runPauseResume()!);
    await waitFor(() => expect(successSpy.mock.calls.some((call) => String(call[0]).includes("已恢复"))).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "批准并推进" }));
    await waitFor(() => expect(successSpy.mock.calls.some((call) => String(call[0]).includes("已批准"))).toBe(true));

    successSpy.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /驳回/ }));
    await waitFor(() => expect(successSpy.mock.calls.some((call) => String(call[0]).includes("已驳回"))).toBe(true));
  });

  it("shows click-to-schedule copy in manual mode even when provenance is preset", async () => {
    api.run.mockResolvedValue(
      designRun({
        stage: "7",
        gates: [],
        provenance: {
          generation: "preset",
          generation_label: "预置测试输出（scripted）",
          execution: "simulated",
          execution_label: "模拟执行（预置工具调用）",
        },
      }),
    );
    api.artifacts.mockResolvedValue(
      designArtifacts({
        provenance: {
          generation: "preset",
          generation_label: "预置测试输出（scripted）",
          execution: "simulated",
          execution_label: "模拟执行（预置工具调用）",
        },
      }),
    );
    api.tasks.mockResolvedValue([{ code: "T-01", state: "ready", revision: 1 }]);
    api.health.mockResolvedValue({ status: "ok", schedule_mode: "manual" });
    renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("schedule-notice")).toBeTruthy());
    expect(screen.getByTestId("schedule-notice").textContent).toContain("请点击调度执行");
    expect(screen.getByTestId("schedule-notice").textContent).not.toContain("每 5 秒自动调度");
    expect(screen.getByTestId("run-provenance").textContent).toContain("预置测试输出");
    expect(screen.getByTestId("run-provenance").textContent).toContain("模拟执行");
  });

  it("keeps preset labels after remount and still follows auto schedule_mode", async () => {
    const provenance = {
      generation: "preset",
      generation_label: "预置测试输出（scripted）",
      execution: "simulated",
      execution_label: "模拟执行（预置工具调用）",
    };
    api.health.mockResolvedValue({ status: "ok", schedule_mode: "auto" });
    api.run.mockResolvedValue(designRun({ stage: "7", gates: [], provenance }));
    api.artifacts.mockResolvedValue(designArtifacts({ provenance }));
    api.tasks.mockResolvedValue([{ code: "T-01", state: "ready", revision: 1 }]);
    const { unmount } = renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("schedule-notice").textContent).toContain("每 5 秒自动调度"));
    expect(screen.getByTestId("run-provenance").textContent).toContain("预置测试输出");
    unmount();
    renderWorkstation();
    await waitFor(() => expect(screen.getByTestId("run-provenance").textContent).toContain("模拟执行"));
    expect(screen.getByTestId("schedule-notice").textContent).toContain("每 5 秒自动调度");
    expect(screen.queryByText("请点击调度执行")).toBeNull();
  });

  it("shows failure feedback for resume and does not pretend the run resumed", async () => {
    const errorSpy = vi.spyOn(message, "error");
    const successSpy = vi.spyOn(message, "success");
    api.run.mockResolvedValue(designRun({ paused: true }));
    api.resumeRun.mockRejectedValue(new Error("恢复被拒绝"));
    renderWorkstation();
    await waitFor(() => expect(runPauseResume()?.getAttribute("aria-label")).toBe("恢复"));
    fireEvent.click(runPauseResume()!);
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(String(errorSpy.mock.calls[0][0])).toMatch(/恢复失败|恢复被拒绝/);
    expect(successSpy).not.toHaveBeenCalled();
    expect(runPauseResume()?.getAttribute("aria-label")).toBe("恢复");
    expect(screen.getByText("已暂停")).toBeTruthy();
  });

  it("rejects DESIGN with success feedback and keeps the original text for resubmit", async () => {
    const successSpy = vi.spyOn(message, "success");
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("button", { name: "驳回（需改原文重提）" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "驳回（需改原文重提）" }));
    await waitFor(() => expect(api.resolveGate).toHaveBeenCalledWith("gate-1", "reject", {}));
    expect(successSpy.mock.calls.some((call) => String(call[0]).includes("已驳回"))).toBe(true);
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("目标：学生查看空闲座位。");
  });

  it("opens plan, specs, and activity tabs with content from the current run", async () => {
    api.artifacts.mockResolvedValue(
      designArtifacts({
        spec: { features: [{ code: "F1", title: "查看空闲座位" }] },
        design: { modules: [{ code: "M1", name: "座位查询" }] },
        plan: { tasks: [{ code: "T-01", title: "实现座位查询", depends_on: [] }] },
      }),
    );
    api.tasks.mockResolvedValue([{ code: "T-01", state: "ready", revision: 1, card: { depends_on: [] } }]);
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("button", { name: /任务计划/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /任务计划/ }));
    await waitFor(() => expect(screen.getByTestId("task-plan-preview").textContent).toMatch(/T-01|实现座位查询/));
    fireEvent.click(screen.getByRole("button", { name: /规格产物/ }));
    await waitFor(() => expect(screen.getByText("查看空闲座位")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /活动/ }));
    await waitFor(() => expect(screen.getByText("暂无事件")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /节点详情/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /节点详情/ }).getAttribute("aria-pressed")).toBe("true"));
    expect(document.body.textContent).toMatch(/选择一个节点|节点详情/);
  }, 15000);

  it("uses compact single-line progress rows without duplicated raw-state metadata", async () => {
    renderWorkstation();
    await waitFor(() => expect(document.querySelector(".ws-left .phase-items .row")).toBeTruthy());

    const firstRow = document.querySelector(".ws-left .phase-items .row")!;
    expect(firstRow.querySelector(".row-meta")).toBeNull();
    expect(firstRow.querySelector(".row-title .code")?.textContent).toBe("STAGE-0");
    expect(firstRow.querySelector(".row-title .text")?.textContent).toBe("想法解析与初步做法");
  });

  it("shows failure feedback for approve and keeps the gate actionable", async () => {
    const errorSpy = vi.spyOn(message, "error");
    const successSpy = vi.spyOn(message, "success");
    api.resolveGate.mockRejectedValue(new Error("关卡冲突"));
    renderWorkstation();
    await waitFor(() => expect(screen.getByRole("button", { name: "批准并推进" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "批准并推进" }));
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(String(errorSpy.mock.calls[0][0])).toMatch(/关卡处理失败|关卡冲突/);
    expect(successSpy).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "批准并推进" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
