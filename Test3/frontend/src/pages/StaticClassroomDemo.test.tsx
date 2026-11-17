import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import StaticClassroomDemo from "./StaticClassroomDemo";
import {
  createStaticDemoState,
  loadStaticDemoState,
  saveStaticDemoState,
  staticDemoReducer,
  STATIC_DEMO_AUTOPLAY_MS,
  type StaticDemoState,
} from "../demo/staticClassroom";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, children }: { nodes: any[]; children?: ReactNode }) => (
    <div data-testid="static-flow">
      {nodes.map((node) => <div data-testid={`flow-${node.id}`} key={node.id}>{node.data.rawState}</div>)}
      {children}
    </div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Left: "left", Right: "right" },
  useReactFlow: () => ({ fitView: vi.fn() }),
}));

function renderDemo() {
  return render(<MemoryRouter><StaticClassroomDemo /></MemoryRouter>);
}

function next(state: StaticDemoState) {
  return staticDemoReducer(state, { type: "NEXT" });
}

function completedState() {
  let state = createStaticDemoState();
  for (let index = 0; index < 10; index += 1) state = next(state);
  for (const gate of ["DISCUSSION", "SPEC", "DESIGN", "PLAN"] as const) {
    state = staticDemoReducer(state, { type: "APPROVE", gate });
  }
  for (let index = 0; index < 9; index += 1) state = next(state);
  return state;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("StaticClassroomDemo", () => {
  it("starts without model configuration or fetch and keeps honest labels visible", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderDemo();
    expect(screen.getAllByText("静态课堂演示 · 预置数据 · 不调用真实模型").length).toBeGreaterThan(0);
    expect(screen.getByText(/不创建真实项目、不读取密钥、不执行开发任务/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "开始静态演示" }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "讨论 1" }));
    expect(screen.getByText("人工编写的角色讨论示例 · 不代表真实模型发言或思考过程")).toBeTruthy();
    expect(screen.getByTestId("utterance-1").textContent).toContain("产品 Agent");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("pauses autoplay at the discussion gate and never auto-approves", () => {
    vi.useFakeTimers();
    let state = createStaticDemoState();
    for (let index = 0; index < 9; index += 1) state = next(state);
    saveStaticDemoState(window.localStorage, state);
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    act(() => vi.advanceTimersByTime(STATIC_DEMO_AUTOPLAY_MS + 10));
    expect(screen.getByTestId("static-gate").textContent).toContain("讨论结论确认");
    expect(screen.getByRole("button", { name: "批准并推进" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "自动播放" }) as HTMLButtonElement).disabled).toBe(true);
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(10);
    act(() => vi.advanceTimersByTime(STATIC_DEMO_AUTOPLAY_MS * 4));
    expect(loadStaticDemoState(window.localStorage).approvedGates).toEqual([]);
    expect(loadStaticDemoState(window.localStorage).stage).toBe("discussion");
  });

  it("locks rapid NEXT clicks so a double click cannot skip a discussion event", () => {
    vi.useFakeTimers();
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: "开始静态演示" }));
    const nextButton = screen.getByRole("button", { name: "下一步" });
    fireEvent.click(nextButton);
    fireEvent.click(nextButton);
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(1);
    expect(loadStaticDemoState(window.localStorage).activities.filter((event) => event.kind === "角色讨论（预置）")).toHaveLength(1);
    act(() => vi.advanceTimersByTime(330));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(2);
  });

  it("stops the timeline on pause and resumes without replaying an old event", () => {
    vi.useFakeTimers();
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: "开始静态演示" }));
    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    act(() => vi.advanceTimersByTime(500));
    fireEvent.click(screen.getByRole("button", { name: "暂停播放" }));
    act(() => vi.advanceTimersByTime(STATIC_DEMO_AUTOPLAY_MS * 3));
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    act(() => vi.advanceTimersByTime(STATIC_DEMO_AUTOPLAY_MS + 10));
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(1);
    expect(loadStaticDemoState(window.localStorage).activities.filter((event) => event.kind === "角色讨论（预置）")).toHaveLength(1);
  });

  it("does not double-advance when manual NEXT races the autoplay timer", () => {
    vi.useFakeTimers();
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: "开始静态演示" }));
    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    act(() => vi.advanceTimersByTime(STATIC_DEMO_AUTOPLAY_MS - 100));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    act(() => vi.advanceTimersByTime(200));
    expect(loadStaticDemoState(window.localStorage).discussionCount).toBe(1);
    expect(loadStaticDemoState(window.localStorage).activities.filter((event) => event.kind === "角色讨论（预置）")).toHaveLength(1);
  });

  it("restores the same parallel-running frame after unmount and refresh", async () => {
    let state = createStaticDemoState();
    for (let index = 0; index < 10; index += 1) state = next(state);
    for (const gate of ["DISCUSSION", "SPEC", "DESIGN", "PLAN"] as const) {
      state = staticDemoReducer(state, { type: "APPROVE", gate });
    }
    state = next(next(next(state)));
    saveStaticDemoState(window.localStorage, state);
    const first = renderDemo();
    await waitFor(() => expect(screen.getByTestId("flow-T-02").textContent).toBe("running"));
    expect(screen.getByTestId("flow-T-03").textContent).toBe("running");
    expect(screen.getByTestId("flow-T-04").textContent).toBe("pending");
    first.unmount();
    renderDemo();
    await waitFor(() => expect(screen.getByTestId("flow-T-02").textContent).toBe("running"));
    expect(loadStaticDemoState(window.localStorage).runId).toBe(state.runId);
    expect(loadStaticDemoState(window.localStorage).executionStep).toBe(3);
  });

  it("shows preset acceptance without presenting it as repository test evidence", async () => {
    saveStaticDemoState(window.localStorage, completedState());
    renderDemo();
    await waitFor(() => expect(screen.getByTestId("static-acceptance-panel").textContent).toContain("静态课堂演示，非真实模型生成或执行证明"));
    expect(screen.getByTestId("static-acceptance-panel").textContent).toContain("不计入仓库真实测试统计");
    expect(screen.getByTestId("static-acceptance-panel").textContent).toContain("预置通过／未真实执行");
    expect(screen.getByTestId("static-acceptance-panel").textContent).toContain("T-02 与 T-03 曾同时处于 running");
  });
});
