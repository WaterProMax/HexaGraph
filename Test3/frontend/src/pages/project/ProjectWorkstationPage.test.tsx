import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectWorkstationPage, { ProjectWorkstation, mapTasks } from "./ProjectWorkstationPage";

const tasks = [
  { code: "T-01", title: "实现登录", progress: 40, status: "running" },
  { code: "T-02", title: "接通验收", progress: 100, status: "done" },
];

function renderWorkstation(overrides: Partial<Parameters<typeof ProjectWorkstation>[0]> = {}) {
  const dirtyRef = { current: false };
  const utils = render(
    <MemoryRouter>
      <ProjectWorkstation projectId="proj-1" loadState="ready" tasks={tasks} dirtyRef={dirtyRef} {...overrides} />
    </MemoryRouter>,
  );
  return { ...utils, dirtyRef };
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("ProjectWorkstation tree and tabs", () => {
  it("shows the task tree with visible progress", () => {
    renderWorkstation();
    const tree = screen.getByTestId("task-tree");
    expect(tree.textContent).toContain("T-01");
    const bar = screen.getByRole("progressbar", { name: "T-01 进度" });
    expect(bar.getAttribute("aria-valuenow")).toBe("40");
    expect(bar.textContent).toContain("40");
  });

  it("switches panels for all four tabs", () => {
    renderWorkstation();
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-monitor"));
    expect(screen.getByTestId("panel-monitor")).toBeTruthy();
    expect(screen.queryByTestId("panel-details")).toBeNull();
    fireEvent.click(screen.getByTestId("tab-activity"));
    expect(screen.getByTestId("panel-activity")).toBeTruthy();
    expect(screen.queryByTestId("panel-monitor")).toBeNull();
    fireEvent.click(screen.getByTestId("tab-graph"));
    expect(screen.getByTestId("panel-graph")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-details"));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
  });

  it("shows the clicked task code in the details tab", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-monitor"));
    fireEvent.click(screen.getByRole("treeitem", { name: /T-02/ }));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });

  it("marks the shared dirtyRef when editing a note", () => {
    const { dirtyRef } = renderWorkstation();
    expect(dirtyRef.current).toBe(false);
    fireEvent.change(screen.getByLabelText("任务备注"), { target: { value: "补一条回归" } });
    expect(dirtyRef.current).toBe(true);
  });

  it("reuses the existing splitter handle", () => {
    renderWorkstation();
    expect(screen.getByTestId("ws-splitter")).toBeTruthy();
    expect(screen.getByRole("separator", { name: "调整信息栏宽度" })).toBeTruthy();
  });

  it("renders empty state without crashing", () => {
    renderWorkstation({ loadState: "empty", tasks: [] });
    expect(screen.getByTestId("ws-empty")).toBeTruthy();
    expect(screen.getByTestId("task-tree").textContent).toContain("没有任务");
  });

  it("renders loading, error and forbidden states", () => {
    renderWorkstation({ loadState: "loading" });
    expect(screen.getByTestId("ws-loading")).toBeTruthy();
    cleanup();
    renderWorkstation({ loadState: "error", errorText: "network down" });
    expect(screen.getByTestId("ws-error").textContent).toContain("network down");
    cleanup();
    renderWorkstation({ loadState: "forbidden" });
    expect(screen.getByTestId("ws-forbidden")).toBeTruthy();
  });
});

describe("task mapping", () => {
  it("maps backend task states without inventing succeeded", () => {
    expect(mapTasks([{ code: "T-1", state: "done", card: { title: "完成" } } as any])).toEqual([
      { code: "T-1", title: "完成", progress: 100, status: "done" },
    ]);
    expect(mapTasks([{ code: "T-2", state: "running", card: {} } as any])[0].progress).toBe(40);
    expect(mapTasks([{ code: "T-3", state: "pending", card: {} } as any])[0].progress).toBe(0);
  });
});

describe("ProjectWorkstationPage container", () => {
  it("loads the project's latest run tasks from real endpoints", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        if (url === "/api/runs") {
          return new Response(
            JSON.stringify([
              { id: "run-0", project_id: "other" },
              { id: "run-1", project_id: "proj-1" },
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url === "/api/runs/run-1/tasks") {
          return new Response(JSON.stringify([{ code: "T-01", state: "running", card: { title: "实现登录" } }]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    render(
      <MemoryRouter>
        <ProjectWorkstationPage projectId="proj-1" />
      </MemoryRouter>,
    );
    expect(await screen.findByText("实现登录")).toBeTruthy();
    expect(calls).toContain("/api/runs/run-1/tasks");
    expect(calls).not.toContain("/api/runs/run-0/tasks");
  });
});