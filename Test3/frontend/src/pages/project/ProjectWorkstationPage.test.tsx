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
    fireEvent.click(await screen.findByRole("button", { name: "开发任务" }));
    expect(await screen.findByRole("treeitem", { name: /实现登录/ })).toBeTruthy();
    expect(calls).toContain("/api/runs/run-1/tasks");
    expect(calls).not.toContain("/api/runs/run-0/tasks");
  });
});
describe("P6-T04 grant, review and defect wiring", () => {
  const defect = {
    defect_id: "d-1",
    run_id: "run-1",
    task_code: "T-02",
    module_id: "M1",
    related_requirement_id: null,
    evidence_uris: ["file://logs/t02.log"],
    status: "open" as const,
    detail: "缺边界用例",
  };
  const ballot = {
    reviewer_bot_id: "bot-2",
    proposal_id: "p-1",
    scores: { coverage: 3 },
    score_justification: { coverage: "覆盖主路径" },
    hard_gate_results: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: false },
    dissent_items: ["缺边界用例"],
  };

  it("shows the baseline_stale banner", () => {
    renderWorkstation({ grantErrorCategory: "baseline_stale" });
    expect(screen.getByTestId("grant-banner").textContent).toMatch(/基线/);
    expect(screen.getByTestId("grant-banner").textContent).not.toMatch(/请逐行确认/);
  });

  it("renders review ballots and dissent in the monitor tab", () => {
    renderWorkstation({ ballots: [ballot], dissentItems: ["风险 X"] });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    const panel = screen.getByTestId("discussion-review-panel");
    expect(panel.textContent).toContain("覆盖");
    expect(panel.textContent).toContain("风险 X");
  });

  it("locates the task behind a defect", () => {
    renderWorkstation({ defects: [defect] });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    fireEvent.click(screen.getByTestId("defect-T-02"));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });
});

describe("workstation title", () => {
  it("shows the project name instead of a generic title or the raw id", () => {
    renderWorkstation({ projectName: "自习室空位查询小程序" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("自习室空位查询小程序");
    expect(screen.queryByText("proj-1")).toBeNull();
  });

  it("falls back to a generic title while the name is unknown", () => {
    renderWorkstation();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("项目工作台");
  });
});

describe("P6-R03 team strip and shared memory", () => {
  const teamMembers = [
    { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active" as const, role_in_project: "lead", is_leader: true },
    { bot_id: "bot-b", display_name: "周明", role_template: "pm", status: "active" as const, role_in_project: "dev", is_leader: false },
  ];

  it("renders the team strip and opens management", () => {
    const onManage = vi.fn();
    renderWorkstation({
      team: { members: teamMembers, onInvite: vi.fn(), onManage },
    });
    expect(screen.getByTestId("team-strip")).toBeTruthy();
    fireEvent.click(screen.getByTestId("manage-members"));
    expect(onManage).toHaveBeenCalled();
  });

  it("shows the shared memory panel in the monitor tab", () => {
    renderWorkstation({ memoryPanel: <div data-testid="project-memory-panel">memory</div> });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    expect(screen.getByTestId("project-memory-panel")).toBeTruthy();
    expect(screen.getByTestId("panel-monitor")).toBeTruthy();
  });
});

describe("P6-R04 defect locate highlight", () => {
  const defect = {
    defect_id: "d-9",
    run_id: "run-1",
    task_code: "T-02",
    module_id: "M1",
    related_requirement_id: null,
    evidence_uris: ["file://logs/t02.log"],
    status: "open" as const,
    detail: "缺边界用例",
  };

  it("briefly highlights the located task in the tree", () => {
    renderWorkstation({ defects: [defect] });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    fireEvent.click(screen.getByTestId("defect-T-02"));
    const item = screen.getByRole("treeitem", { name: /T-02/ });
    expect(item.className).toContain("highlight");
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });
});

describe("discussion panel wiring", () => {
  function json(body: unknown) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("shows the discussion view when the project has no run yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/projects") return json([{ id: "proj-1", name: "自习室空位查询" }]);
        return json([]);
      }),
    );
    render(
      <MemoryRouter>
        <ProjectWorkstationPage projectId="proj-1" />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("disc-stage-bar")).toBeTruthy();
    expect(screen.getByText(/先邀请 Bot/)).toBeTruthy();
    expect(screen.queryByTestId("ws-empty")).toBeNull();
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.queryByTestId("tab-details")).toBeNull();
  });

  it("keeps discussion available alongside the tasks of an existing run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/runs") return json([{ id: "run-1", project_id: "proj-1" }]);
        if (url === "/api/runs/run-1/tasks") {
          return json([{ code: "T-01", state: "running", card: { title: "实现登录" } }]);
        }
        return json([]);
      }),
    );
    render(
      <MemoryRouter>
        <ProjectWorkstationPage projectId="proj-1" />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("disc-stage-bar")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "开发任务" }));
    expect(await screen.findByRole("treeitem", { name: /实现登录/ })).toBeTruthy();
    expect(screen.getByTestId("task-tree")).toBeTruthy();
    expect(screen.queryByTestId("disc-stage-bar")).toBeNull();
    expect(screen.queryByLabelText("一句话想法")).toBeNull();
  });

  it("replaces the empty notice and the task body with the discussion panel", () => {
    renderWorkstation({
      loadState: "empty",
      tasks: [],
      team: {
        members: [
          { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active" as const, role_in_project: "lead", is_leader: true },
        ],
        onInvite: vi.fn(),
        onManage: vi.fn(),
      },
      discussionPanel: <div data-testid="discussion-panel-stub">讨论视图</div>,
    });

    expect(screen.getByTestId("discussion-panel-stub")).toBeTruthy();
    expect(screen.getByTestId("team-strip")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
    expect(screen.queryByTestId("ws-empty")).toBeNull();
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.queryByTestId("project-workstation")).toBeNull();
  });

  it("still shows the empty notice when no discussion panel is passed", () => {
    renderWorkstation({ loadState: "empty", tasks: [] });
    expect(screen.getByTestId("ws-empty")).toBeTruthy();
    expect(screen.queryByTestId("discussion-panel-stub")).toBeNull();
  });
});
