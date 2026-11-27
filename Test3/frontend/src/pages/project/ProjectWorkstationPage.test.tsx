import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DecisionPackage, DiscussionSession } from "../../api/types";
import ProjectWorkstationPage, { ProjectWorkstation, mapTasks } from "./ProjectWorkstationPage";


/**
 * React Flow is mocked for jsdom. The dependency graph's own accessible edge
 * text is rendered by TaskDependencyGraph, while node clicks are wired here so
 * the graph-selection sync can still be asserted. Node cards render through
 * the real nodeTypes so the A2 assignee badge is covered on the main path.
 */
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    children,
    nodes = [],
    edges = [],
    onNodeClick,
    nodesDraggable,
    nodesConnectable,
    nodeTypes = {},
  }: {
    children?: ReactNode;
    nodes?: Array<{ id: string; type?: string; data?: any }>;
    edges?: Array<{ id: string; source: string; target: string }>;
    onNodeClick?: (event: unknown, node: any) => void;
    nodesDraggable?: boolean;
    nodesConnectable?: boolean;
    nodeTypes?: Record<string, (props: { data: any }) => ReactNode>;
  }) => (
    <div data-testid="flow" data-draggable={String(nodesDraggable)} data-connectable={String(nodesConnectable)}>
      {nodes.map((node) => (
        <button
          type="button"
          key={node.id}
          data-testid="flow-node"
          data-node-id={node.id}
          data-status={node.data?.status}
          data-selected={String(Boolean(node.data?.selected))}
          onClick={() => onNodeClick?.(null, node)}
        >
          {node.type && nodeTypes[node.type]
            ? createElement(nodeTypes[node.type], { data: node.data })
            : node.data?.code}
        </button>
      ))}
      {edges.map((edge) => (
        <div key={edge.id} data-testid="flow-edge" data-source={edge.source} data-target={edge.target} />
      ))}
      {children}
    </div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Left: "left", Right: "right" },
  useReactFlow: () => ({ fitView: vi.fn(), setViewport: vi.fn() }),
}));

const tasks = [
  {
    code: "T-01",
    title: "实现登录",
    progress: 40,
    status: "running",
    role: "coder",
    dependsOn: [],
    writeSet: ["src/login.ts"],
    acceptance: [{ cmd: ["python", "-m", "pytest", "-q"], passCriteria: "全部通过" }],
  },
  {
    code: "T-02",
    title: "接通验收",
    progress: 100,
    status: "done",
    role: "tester",
    dependsOn: ["T-01"],
    writeSet: ["tests/test_login.py"],
    acceptance: [{ cmd: ["python", "-m", "pytest", "-q"], passCriteria: "全部通过" }],
  },
];

function renderWorkstation(overrides: Partial<Parameters<typeof ProjectWorkstation>[0]> = {}) {
  const dirtyRef = { current: false };
  const utils = render(
    <MemoryRouter>
      <ProjectWorkstation
        projectId="proj-1"
        loadState="ready"
        tasks={tasks}
        dirtyRef={dirtyRef}
        {...overrides}
      />
    </MemoryRouter>,
  );
  return { ...utils, dirtyRef };
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  window.localStorage.clear();
  // The activity timeline and monitor subscribe to the run event stream; jsdom has no EventSource.
  class FakeEventSource {
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor(public url: string) {}
  }
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("ProjectWorkstation tree and tabs", () => {
  it("shows the task tree with visible progress on the activity tab", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-activity"));
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
    // 任务图不再是不带关系的纯文本 <ul>；它渲染共享的依赖图组件与可访问依赖描述。
    expect(document.querySelector(".task-graph-list")).toBeNull();
    expect(screen.getByTestId("task-dependency-graph")).toBeTruthy();
    expect(screen.getByText("T-02 依赖 T-01")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-details"));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
  });

  it("syncs the dependency graph node click with the header picker and details", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-graph"));
    // 任务图 is full width: no side tree, the header picker carries the selection instead.
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.getByTestId("project-workstation").className).toContain("ws-body-solo");
    const node = screen
      .getAllByTestId("flow-node")
      .find((el) => el.getAttribute("data-node-id") === "T-02");
    expect(node).toBeTruthy();
    expect((screen.getByLabelText("定位任务") as HTMLSelectElement).value).toBe("T-01");
    fireEvent.click(node!);
    expect(screen.getByTestId("tab-details").getAttribute("aria-selected")).toBe("false");
    expect((screen.getByLabelText("定位任务") as HTMLSelectElement).value).toBe("T-02");
    // The same selection feeds the full-width details tab.
    fireEvent.click(screen.getByTestId("tab-details"));
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });

  it("makes the persisted input panel the details content and keeps the note secondary", () => {
    renderWorkstation();
    const panel = screen.getByTestId("panel-details");
    const constraints = within(panel).getByTestId("input-constraints");
    expect(constraints.textContent).toContain("coder");
    expect(constraints.textContent).toContain("src/login.ts");
    expect(within(panel).getByTestId("detail-task-code").textContent).toBe("T-01");
    expect(within(panel).getByLabelText("切换任务")).toBeTruthy();
    const note = screen.getByTestId("task-note-secondary");
    expect(note.getAttribute("data-secondary")).toBe("true");
    expect(note.textContent).toContain("未持久化");
    // The persisted input panel is the primary content and precedes the in-memory note.
    expect(constraints.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("embeds the full run event timeline in the activity tab and fixes the timeline deep link", async () => {
    class FakeEventSource {
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      close = vi.fn();
      constructor(public url: string) {}
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    const eventRows = Array.from({ length: 21 }, (_, index) => ({
      seq: index + 1,
      kind: index === 0 ? "task.tool_step" : "task.state_changed",
      subject: "T-01",
      payload: index === 0 ? { input_summary: "读取 src/login.ts", ok: true } : { state: "running" },
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/runs/run-1/events/history")) {
          return new Response(JSON.stringify(eventRows), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    renderWorkstation({ runId: "run-1", initialTab: "activity" });

    // The activity tab renders the full timeline, not the 20-row feed.
    expect(await screen.findByTestId("timeline-events")).toBeTruthy();
    expect(await screen.findAllByTestId("timeline-event")).toHaveLength(21);
    expect(screen.getByTestId("timeline-count").textContent).toContain("共 21 条");
    expect(screen.getByText("#1")).toBeTruthy();
    const first = screen.getAllByTestId("timeline-event")[0];
    expect(first.textContent).toContain("工具步骤");
    expect(first.textContent).toContain("T-01");
    expect(first.textContent).toContain("读取 src/login.ts");
    expect(first.textContent).not.toContain('"ok"');
    expect(screen.queryByTestId("activity-feed")).toBeNull();

    // The requirement trace stays in the activity area, and the timeline keeps a
    // single observation system (no second style switch on run events).
    expect(await screen.findByTestId("requirement-trace-panel")).toBeTruthy();
    expect(await screen.findByTestId("requirement-trace-empty")).toBeTruthy();
    expect(screen.getByTestId("panel-activity").textContent).not.toContain("没有事件流");
    expect(screen.queryByTestId("observation-style-switch")).toBeNull();

    // The old link pointed at the run overview; it must now deep-link the timeline.
    const timelineLink = screen.getByRole("link", { name: /在运行详情打开时间线/ });
    expect(timelineLink.getAttribute("href")).toBe("/runs/run-1/timeline");
    expect(screen.getByRole("link", { name: /完整工作台/ })).toBeTruthy();
  });

  it("switches the details view through the header task picker", () => {
    renderWorkstation();
    fireEvent.change(screen.getByLabelText("切换任务"), { target: { value: "T-02" } });
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });

  it("keeps the details tab full width without the task tree", () => {
    renderWorkstation();
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.getByTestId("project-workstation").className).toContain("ws-body-solo");
  });

  it("uses the full width for monitor and evaluation panels", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-monitor"));
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.getByTestId("project-workstation").className).toContain("ws-body-solo");
    fireEvent.click(screen.getByTestId("tab-evaluation"));
    expect(screen.queryByTestId("task-tree")).toBeNull();
  });

  it("renders monitor KPIs and fallback tasks", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-monitor"));
    expect(screen.getByTestId("run-monitor")).toBeTruthy();
    expect(screen.getByTestId("monitor-kpis").textContent).toContain("任务进度");
    expect(screen.getByTestId("monitor-package-loose").textContent).toContain("T-01");
  });

  it("renders the Agent evaluation tab", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-evaluation"));
    expect(screen.getByTestId("panel-evaluation")).toBeTruthy();
    expect(screen.getByTestId("agent-evaluation")).toBeTruthy();
  });

  it("marks the shared dirtyRef when editing a note", () => {
    const { dirtyRef } = renderWorkstation();
    expect(dirtyRef.current).toBe(false);
    fireEvent.change(screen.getByLabelText("任务备注"), { target: { value: "补一条回归" } });
    expect(dirtyRef.current).toBe(true);
  });

  it("reuses the existing splitter handle on the activity tab", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-activity"));
    expect(screen.getByTestId("ws-splitter")).toBeTruthy();
    expect(screen.getByRole("separator", { name: "调整信息栏宽度" })).toBeTruthy();
  });

  it("renders empty state without crashing", () => {
    renderWorkstation({ loadState: "empty", tasks: [] });
    expect(screen.getByTestId("ws-empty")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-activity"));
    expect(screen.getByTestId("task-tree").textContent).toContain("没有任务");
    fireEvent.click(screen.getByTestId("tab-graph"));
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect(screen.getByTestId("task-dependency-empty")).toBeTruthy();
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
        if (url.includes("/execution-trace")) {
          return new Response(JSON.stringify({ attempts: [] }), {
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
    // 开发任务 directly opens the split tabs; the classroom grid is gone.
    expect(await screen.findByRole("option", { name: /实现登录/ })).toBeTruthy();
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

  it("puts project actions behind the title menu and keeps avatars outside", () => {
    const onManage = vi.fn();
    const onInvite = vi.fn();
    renderWorkstation({
      team: { members: teamMembers, onInvite, onManage },
    });
    expect(screen.getByTestId("team-strip")).toBeTruthy();
    expect(screen.queryByTestId("manage-members")).toBeNull();
    expect(screen.queryByTestId("invite-bots")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /项目操作/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "管理项目成员" }));
    expect(onManage).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /项目操作/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "邀请更多 Bot" }));
    expect(onInvite).toHaveBeenCalled();
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

  it("opens the located task in the full-width details tab", () => {
    renderWorkstation({ defects: [defect] });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    fireEvent.click(screen.getByTestId("defect-T-02"));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
    // 详情 is full width now, so the highlight-only tree affordance is gone.
    expect(screen.queryByTestId("task-tree")).toBeNull();
  });

  it("still selects the located task on the full-width 任务图", () => {
    renderWorkstation({ defects: [defect] });
    fireEvent.click(screen.getByTestId("tab-monitor"));
    fireEvent.click(screen.getByTestId("defect-T-02"));
    fireEvent.click(screen.getByTestId("tab-graph"));
    expect(screen.queryByTestId("task-tree")).toBeNull();
    expect((screen.getByLabelText("定位任务") as HTMLSelectElement).value).toBe("T-02");
    const node = screen
      .getAllByTestId("flow-node")
      .find((el) => el.getAttribute("data-node-id") === "T-02");
    expect(node?.getAttribute("data-selected")).toBe("true");
  });

  it("locates a task from the graph header picker without leaving the graph", () => {
    renderWorkstation();
    fireEvent.click(screen.getByTestId("tab-graph"));
    fireEvent.change(screen.getByLabelText("定位任务"), { target: { value: "T-02" } });
    expect(screen.getByTestId("panel-graph")).toBeTruthy();
    expect(screen.getByTestId("tab-graph").getAttribute("aria-selected")).toBe("true");
    expect((screen.getByLabelText("定位任务") as HTMLSelectElement).value).toBe("T-02");
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
        if (url.includes("/execution-trace")) return json({ attempts: [] });
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
    // 开发任务 directly opens the split tabs; the classroom grid is gone.
    expect(await screen.findByRole("option", { name: /实现登录/ })).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-graph"));
    // 任务图 is full width: the dependency graph + header picker replace the side tree.
    expect(await screen.findByTestId("task-dependency-graph")).toBeTruthy();
    expect(screen.getByLabelText("定位任务")).toBeTruthy();
    expect(screen.queryByTestId("task-tree")).toBeNull();
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

describe("assignment board on the project main path (A2/A3)", () => {
  const team = {
    members: [
      { bot_id: "bot-leader", display_name: "Alice Leader", role_template: "developer", status: "active" as const, role_in_project: "dev", is_leader: true },
      { bot_id: "bot-a", display_name: "Member A", role_template: "developer", status: "active" as const, role_in_project: "dev", is_leader: false },
    ],
    onInvite: vi.fn(),
    onManage: vi.fn(),
  };

  it("exposes a 任务派发 tab next to 任务图/执行监控 without needing /workstation", () => {
    renderWorkstation({
      runId: "run-1",
      team,
      actorBotId: "bot-leader",
      actorIsLeader: true,
      onShowDiscussion: vi.fn(),
    });
    fireEvent.click(screen.getByTestId("tab-assignment"));
    expect(screen.getByTestId("panel-assignment")).toBeTruthy();
    expect(screen.getByTestId("assignment-board")).toBeTruthy();
    expect(screen.getByTestId("assignment-select-T-01")).toBeTruthy();
    // The group chat and its Leader stay visible next to the dispatch board.
    expect(screen.getByTestId("assignment-team").textContent).toContain("Alice Leader");
    expect(screen.getByTestId("assignment-back-to-discussion")).toBeTruthy();
  });

  it("keeps the board read-only for a non-Leader actor", () => {
    renderWorkstation({ runId: "run-1", team, actorBotId: "bot-a", actorIsLeader: false });
    fireEvent.click(screen.getByTestId("tab-assignment"));
    expect((screen.getByTestId("assignment-select-T-01") as HTMLSelectElement).disabled).toBe(true);
  });

  it("maps assignment and revision from the backend task list", () => {
    const mapped = mapTasks([
      {
        code: "T-01",
        state: "ready",
        revision: 3,
        card: { title: "实现登录", role: "coder" },
        assignment: {
          assignee_bot_id: "bot-a",
          assignee_display_name: "Member A",
          assigned_by_bot_id: "bot-leader",
          assigned_at: "2026-11-26T10:00:00+00:00",
          revision: 1,
        },
      },
      { code: "T-02", state: "pending", card: { title: "接通验收" }, assignment: null },
    ] as any);
    expect(mapped[0].revision).toBe(3);
    expect(mapped[0].assignment?.assignee_display_name).toBe("Member A");
    expect(mapped[1].assignment).toBeNull();
  });

  it("shows the assignee badge on the shared task graph", () => {
    renderWorkstation({
      runId: "run-1",
      tasks: [
        { ...tasks[0], assignment: { assignee_bot_id: "bot-a", assignee_display_name: "Member A", assigned_by_bot_id: "bot-leader", assigned_at: "2026-11-26T10:00:00+00:00", revision: 1 } },
        { ...tasks[1], assignment: null },
      ],
    });
    fireEvent.click(screen.getByTestId("tab-graph"));
    expect(screen.getByTestId("graph-assignee-T-01").textContent).toContain("Member A");
    expect(screen.getByTestId("graph-assignee-T-02").textContent).toContain("未派发");
  });
});

describe("V1 approved spec beside task constraints", () => {
  const decisionPackage: DecisionPackage = {
    decision_id: "decision-1",
    session_id: "s1",
    requirement_snapshot_hash: "snap-hash",
    proposal_ids: ["p1"],
    dissent_items: [],
    hard_gate_summary: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: true },
    body_md: "# 需求规格\n\n学生可按空闲时段筛选座位。",
    sha256: "a".repeat(64),
  };
  const approvedSession: DiscussionSession = {
    session_id: "s1",
    project_id: "proj-1",
    leader_bot_id: "bot-leader",
    participant_bot_ids: ["bot-leader", "bot-a"],
    status: "approved",
    current_round: 1,
    budget: { max_rounds: 3, max_tokens: null, max_wallclock_seconds: null, score_gap_threshold: null },
    requirement_snapshot_hash: "snap-hash",
    decision_package: decisionPackage,
    requirement_text: "做一个自习室空位查询小程序。",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-19T10:00:00Z",
  };

  function jsonResponse(body: unknown) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("shows the approved discussion markdown inline while the constraints stay mounted", () => {
    renderWorkstation({ runId: "run-1", sessions: [approvedSession] });

    const panel = screen.getByTestId("panel-details");
    expect(within(panel).getByTestId("approved-spec-panel")).toBeTruthy();
    expect(within(panel).getByText("学生可按空闲时段筛选座位。")).toBeTruthy();
    expect(within(panel).getByTestId("input-constraints")).toBeTruthy();
    expect(within(panel).getByTestId("detail-task-code").textContent).toBe("T-01");
    // The discussion view is not mounted into the task page, but its spec body no longer
    // requires switching to it first.
    expect(screen.queryByTestId("ws-discussion")).toBeNull();
    expect(screen.getByTestId("approved-spec-requirement").textContent).toContain("自习室空位查询");
  });

  it("falls back to the complete SPEC artifact when the scripted path has no discussion markdown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/execution-trace")) {
          return jsonResponse({ attempts: [] });
        }
        if (url.includes("/role-memory/")) {
          return jsonResponse({
            run_id: "run-1",
            project_id: "proj-1",
            task_code: "T-01",
            role: "coder",
            revision: 0,
            manual_text: "",
            manual_updated_by: null,
            manual_updated_at: null,
            role_snapshot: { text: "任务上下文", sources: [], matcher_version: "v1" },
            manual_section: null,
            role_section: { kind: "task_role", source_id: "T-01:coder", source_version: "task-role-v1", text: "任务上下文", sha256: "", summary: "" },
            context_hash: "",
            frozen: false,
            frozen_context: {},
            effective: "current",
          });
        }
        if (url.startsWith("/api/runs/run-1/artifacts")) {
          return jsonResponse({
            baseline_SPEC: "1.4",
            spec: {
              scenarios: [{ code: "S1" }],
              features: [
                { code: "F1", title: "座位查询" },
                { code: "F2", title: "上报表单" },
                { code: "F3", title: "限频" },
                { code: "F4", title: "告警" },
              ],
              nonfunc: [],
              out_of_scope: [],
              open_questions: [],
            },
          });
        }
        return jsonResponse([]);
      }),
    );

    renderWorkstation({ runId: "run-1", sessions: [] });

    const artifact = await screen.findByTestId("approved-spec-artifact");
    expect(artifact.textContent).toContain("已批准 SPEC 工件");
    expect(artifact.textContent).toContain("基线 v1.4");
    // Every feature is listed, not just the first three plus "还有 1 项".
    expect(screen.getAllByTestId("approved-spec-feature")).toHaveLength(4);
    expect(artifact.textContent).toContain("告警");
    expect(within(screen.getByTestId("panel-details")).getByTestId("input-constraints")).toBeTruthy();
    // The summary keeps its compressed view but links to the full body already on screen.
    expect(screen.getByTestId("input-spec-full-link").textContent).toContain("在规格栏查看全文");
  });

  it("shows an honest empty state when neither discussion markdown nor SPEC exists", async () => {
    renderWorkstation({ sessions: [] });
    expect(await screen.findByTestId("approved-spec-empty")).toBeTruthy();
    expect(screen.getByTestId("approved-spec-empty").textContent).toContain("尚未生成已批准规格");
    expect(screen.queryByTestId("approved-spec-feature")).toBeNull();
  });
});

describe("split task view (classroom grid retired)", () => {
  const team = {
    members: [
      { bot_id: "bot-leader", display_name: "Alice Leader", role_template: "leader", status: "active" as const, role_in_project: "lead", is_leader: true },
      { bot_id: "bot-a", display_name: "Member A", role_template: "developer", status: "active" as const, role_in_project: "dev", is_leader: false },
    ],
    onInvite: vi.fn(),
    onManage: vi.fn(),
  };

  class FakeEventSource {
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor(public url: string) {}
  }

  function jsonResponse(body: unknown) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  function stubRunFetch() {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/runs/run-1/events/history")) {
          return jsonResponse([
            { seq: 1, kind: "task.tool_step", subject: "T-01", payload: { input_summary: "读取 src/login.ts" } },
            { seq: 2, kind: "task.state_changed", subject: "T-02", payload: { state: "done" } },
          ]);
        }
        if (url.includes("/execution-trace")) {
          return jsonResponse({ attempts: [] });
        }
        if (url.includes("/role-memory/")) {
          return jsonResponse({
            run_id: "run-1",
            project_id: "proj-1",
            task_code: "T-01",
            role: "coder",
            revision: 0,
            manual_text: "",
            manual_updated_by: null,
            manual_updated_at: null,
            role_snapshot: { text: "任务上下文", sources: [], matcher_version: "v1" },
            manual_section: null,
            role_section: { kind: "task_role", source_id: "T-01:coder", source_version: "task-role-v1", text: "任务上下文", sha256: "", summary: "" },
            context_hash: "",
            frozen: false,
            frozen_context: {},
            effective: "current",
          });
        }
        if (url.startsWith("/api/runs/run-1/artifacts")) {
          return jsonResponse({
            baseline_SPEC: "1.1",
            spec: {
              features: [
                { code: "F1", title: "座位查询" },
                { code: "F2", title: "上报表单" },
                { code: "F3", title: "限频" },
                { code: "F4", title: "告警" },
              ],
              scenarios: [],
              nonfunc: [],
              out_of_scope: [],
              open_questions: [],
            },
          });
        }
        return jsonResponse([]);
      }),
    );
  }

  it("opens the split tabs directly, without a classroom grid or layout switch", async () => {
    stubRunFetch();
    renderWorkstation({ runId: "run-1", team, sessions: [] });

    expect(await screen.findByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("approved-spec-panel")).toBeTruthy();
    // The retired demo grid and its switch must never come back on this page.
    expect(screen.queryByTestId("demo-workbench")).toBeNull();
    expect(screen.queryByTestId("layout-mode-switch")).toBeNull();
    expect(screen.queryByText("课上演示")).toBeNull();
    expect(screen.queryByText("单项查看")).toBeNull();
    // All six split views stay reachable as tabs.
    for (const key of ["details", "assignment", "monitor", "evaluation", "activity", "graph"]) {
      expect(screen.getByTestId(`tab-${key}`)).toBeTruthy();
    }
    fireEvent.click(screen.getByTestId("tab-evaluation"));
    expect(screen.getByTestId("agent-evaluation")).toBeTruthy();
  });

  it("locates a task from the dispatch board into the details tab", async () => {
    stubRunFetch();
    renderWorkstation({ runId: "run-1", team, sessions: [] });
    await screen.findByTestId("panel-details");

    fireEvent.click(screen.getByTestId("tab-assignment"));
    expect(screen.getByTestId("assignment-board")).toBeTruthy();
    fireEvent.click(within(screen.getByTestId("assignment-row-T-02")).getByRole("button", { name: "T-02" }));
    expect(screen.getByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("detail-task-code").textContent).toBe("T-02");
  });

  it("keeps the Leader and spec context when going back to discussion and returning", async () => {
    stubRunFetch();

    function Harness() {
      const [showDiscussion, setShowDiscussion] = useState(true);
      return (
        <ProjectWorkstation
          projectId="proj-1"
          loadState="ready"
          tasks={tasks}
          dirtyRef={{ current: false }}
          team={team}
          runId="run-1"
          sessions={[]}
          actorBotId="bot-leader"
          actorIsLeader
          onShowDiscussion={() => setShowDiscussion(true)}
          onShowTasks={() => setShowDiscussion(false)}
          discussionPanel={showDiscussion ? <div data-testid="discussion-panel-stub">讨论</div> : undefined}
        />
      );
    }

    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "开发任务" }));
    expect(await screen.findByTestId("panel-details")).toBeTruthy();
    expect(screen.getByTestId("context-leader").textContent).toContain("Alice Leader");
    expect(screen.getByTestId("context-spec").textContent).toContain("已批准规格");
    expect(screen.getByTestId("approved-spec-panel")).toBeTruthy();

    fireEvent.click(screen.getByTestId("tab-graph"));
    const node = screen.getAllByTestId("flow-node").find((el) => el.getAttribute("data-node-id") === "T-02");
    fireEvent.click(node!);

    fireEvent.click(screen.getByTestId("context-back-to-discussion"));
    expect(screen.getByTestId("discussion-panel-stub")).toBeTruthy();
    expect(screen.queryByTestId("panel-details")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "开发任务" }));
    expect(await screen.findByTestId("panel-graph")).toBeTruthy();
    expect(screen.getByTestId("context-leader").textContent).toContain("Alice Leader");
    // The selected task survived the discussion round-trip.
    expect((screen.getByLabelText("定位任务") as HTMLSelectElement).value).toBe("T-02");
  });

  it("keeps the existing empty guidance instead of an empty task body", () => {
    renderWorkstation({ tasks: [], loadState: "empty" });
    expect(screen.getByTestId("ws-empty")).toBeTruthy();
    expect(screen.queryByTestId("demo-workbench")).toBeNull();
  });
});
