import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MonitorSnapshot, MonitorTask, TaskRole, TaskRoleMemory } from "../../api/types";
import ProjectWorkstationPage from "./ProjectWorkstationPage";

/**
 * F2 regression coverage against the real default-exported page.
 *
 * The page tree is kept intact (no fake RunMonitorPanel/TaskRoleMemoryPanel).
 * Every data endpoint except the task-role-memory ones is a mocked api-client
 * method; the task-role-memory methods stay real so the actor header is
 * produced by the real client and can be asserted on the offline fetch stub.
 */
const apiMock = vi.hoisted(() => ({
  projects: vi.fn(),
  memberships: vi.fn(),
  bots: vi.fn(),
  runs: vi.fn(),
  tasks: vi.fn(),
  executionGrants: vi.fn(),
  defects: vi.fn(),
  discussionSessions: vi.fn(),
  discussionSession: vi.fn(),
  discussionMessages: vi.fn(),
  discussionReviews: vi.fn(),
  discussionEventsUrl: vi.fn((sessionId: string) => `/api/discussion-sessions/${sessionId}/events`),
  monitor: vi.fn(),
  events: vi.fn(),
  memories: vi.fn(),
  publishMemory: vi.fn(),
}));

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMock,
      // Keep the real implementations: they build the URL/body and attach X-Bot-Id.
      taskRoleMemory: actual.api.taskRoleMemory,
      saveTaskRoleMemory: actual.api.saveTaskRoleMemory,
      deleteTaskRoleMemory: actual.api.deleteTaskRoleMemory,
    },
  };
});

const LEADER_A = {
  bot_id: "bot-leader-a",
  display_name: "林可",
  role_template: "leader",
  provider_ref: "offline",
  model: "offline",
  slot: "planner",
  secret_ref: "",
  tool_policy: [],
  skill_bindings: [],
  token_budget: null,
  status: "active" as const,
};

const MEMBER_A = {
  ...LEADER_A,
  bot_id: "bot-member-a",
  display_name: "周明",
  role_template: "reviewer",
  slot: "reviewer",
};

const MEMBER_B = {
  ...LEADER_A,
  bot_id: "bot-member-b",
  display_name: "陈可",
  role_template: "coder",
  slot: "coder",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function monitorTask(overrides: Partial<MonitorTask>): MonitorTask {
  return {
    code: "T-01",
    title: "任务",
    state: "running",
    status: "running",
    role: "coder",
    slot: "coder",
    model: "offline",
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
    ...overrides,
  };
}

const TASKS_A: MonitorTask[] = [
  monitorTask({ code: "T-A1", title: "实现登录", role: "coder", state: "running" }),
  monitorTask({ code: "T-A2", title: "验收回归", role: "tester", state: "pending", status: "pending" }),
];

const TASKS_B: MonitorTask[] = [
  monitorTask({ code: "T-B1", title: "接入支付", role: "coder", state: "running" }),
];

function monitorSnapshot(runId: string, projectId: string, tasks: MonitorTask[]): MonitorSnapshot {
  const running = tasks.filter((task) => task.status === "running").length;
  return {
    generated_at: "2026-11-25T10:00:00+00:00",
    run: {
      id: runId,
      project_id: projectId,
      status: "active",
      stage: "7",
      paused: false,
      revision: 1,
      tokens_used: 100,
      event_count: 2,
      task_count: tasks.length,
      state_counts: { running, pending: tasks.length - running },
      total: tasks.length,
      done: 0,
      running,
      failed: 0,
      blocked: 0,
      pending: tasks.length - running,
      skipped: 0,
      progress: 0,
      repair_rounds: 0,
      fallback_count: 0,
      fallback_by_slot: {},
      first_event_at: "",
      last_event_at: "",
      elapsed_seconds: 12,
    },
    work_packages: [],
    tasks,
    agents: [],
  };
}

function roleMemoryFixture(
  runId: string,
  projectId: string,
  taskCode: string,
  role: TaskRole,
  overrides: Partial<TaskRoleMemory> = {},
): TaskRoleMemory {
  const text = `任务：${taskCode}\n角色：${role}`;
  return {
    run_id: runId,
    project_id: projectId,
    task_code: taskCode,
    role,
    revision: 2,
    manual_text: "优先覆盖空输入测试",
    manual_updated_by: "bot-leader-a",
    manual_updated_at: "2026-11-25T00:00:00+00:00",
    role_snapshot: {
      text,
      sources: [{ kind: "task_card", ref: taskCode, sha256: "a".repeat(64) }],
      matcher_version: "task-role-v1",
    },
    role_section: {
      kind: "task_role",
      source_id: `${taskCode}:${role}`,
      source_version: "task-role-v1",
      text,
      sha256: "a".repeat(64),
    },
    manual_section: {
      kind: "task_manual",
      source_id: `${taskCode}:${role}`,
      source_version: "2",
      text: "优先覆盖空输入测试",
      sha256: "c".repeat(64),
    },
    context_hash: "d".repeat(64),
    frozen: false,
    frozen_context: {},
    effective: "current",
    ...overrides,
  };
}

type RoleMemoryCall = {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Record<string, unknown> | null;
};

/** Offline fetch stub: only the real task-role-memory client methods may reach it. */
function stubRoleMemoryFetch(
  memories: Record<string, TaskRoleMemory>,
  calls: RoleMemoryCall[],
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      const match = url.match(/^\/api\/runs\/([^/]+)\/tasks\/([^/]+)\/role-memory\/(coder|tester)(\?.*)?$/);
      if (!match) throw new Error(`unexpected network request in offline test: ${method} ${url}`);
      const [, runId, rawTaskCode, rawRole] = match;
      const taskCode = decodeURIComponent(rawTaskCode);
      const role = decodeURIComponent(rawRole) as TaskRole;
      const memory = memories[`${runId}:${taskCode}:${role}`];
      if (!memory) return json({ error_category: "memory_not_found", detail: "not found" }, 404);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
      calls.push({
        url,
        method,
        headers: { ...((init?.headers || {}) as Record<string, string>) },
        body,
      });
      if (method === "PUT") {
        const revision = Number(body?.expected_revision || memory.revision) + 1;
        return json({
          ...memory,
          revision,
          manual_text: String(body?.manual_text ?? ""),
          manual_section: {
            ...memory.manual_section!,
            text: String(body?.manual_text ?? ""),
            source_version: String(revision),
          },
        });
      }
      if (method === "DELETE") {
        return json({
          ...memory,
          revision: memory.revision + 1,
          manual_text: "",
          manual_section: null,
          manual_updated_by: null,
          manual_updated_at: null,
        });
      }
      return json(memory);
    }),
  );
}

class FakeEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
  }
}

function installDefaultApi() {
  apiMock.projects.mockResolvedValue([
    { id: "proj-A", name: "项目甲" },
    { id: "proj-B", name: "项目乙" },
  ]);
  apiMock.memberships.mockImplementation(async (projectId: string) => {
    if (projectId === "proj-A") {
      return {
        items: [
          { bot_id: "bot-leader-a", role_in_project: "lead", is_leader: true },
          { bot_id: "bot-member-a", role_in_project: "dev", is_leader: false },
        ],
      };
    }
    return { items: [{ bot_id: "bot-member-b", role_in_project: "dev", is_leader: false }] };
  });
  apiMock.bots.mockResolvedValue({ items: [LEADER_A, MEMBER_A, MEMBER_B] });
  apiMock.runs.mockResolvedValue([
    { id: "run-A", project_id: "proj-A" },
    { id: "run-B", project_id: "proj-B" },
  ]);
  apiMock.tasks.mockImplementation(async (runId: string) => {
    if (runId === "run-B") {
      return [{ code: "T-B1", state: "running", card: { title: "接入支付" } }];
    }
    return [
      { code: "T-A1", state: "running", card: { title: "实现登录" } },
      { code: "T-A2", state: "ready", card: { title: "验收回归" } },
    ];
  });
  apiMock.monitor.mockImplementation(async (runId: string) => {
    if (runId === "run-B") return monitorSnapshot("run-B", "proj-B", TASKS_B);
    return monitorSnapshot("run-A", "proj-A", TASKS_A);
  });
  apiMock.executionGrants.mockResolvedValue({ items: [] });
  apiMock.defects.mockResolvedValue({ items: [] });
  apiMock.discussionSessions.mockResolvedValue({ items: [] });
  apiMock.discussionSession.mockResolvedValue(null);
  apiMock.discussionMessages.mockResolvedValue({ items: [] });
  apiMock.discussionReviews.mockResolvedValue({ items: [] });
  apiMock.events.mockResolvedValue([]);
  apiMock.memories.mockResolvedValue({ items: [] });
}

function renderPage(projectId: string) {
  return render(
    <MemoryRouter>
      <ProjectWorkstationPage projectId={projectId} />
    </MemoryRouter>,
  );
}

/** The page opens on the discussion; switch to the task workstation, then the monitor tab. */
async function openMonitorTab() {
  fireEvent.click(await screen.findByRole("button", { name: "开发任务" }));
  fireEvent.click(await screen.findByTestId("tab-monitor"));
  await screen.findByTestId("run-monitor");
  // The run summary only renders once the real monitor snapshot has loaded.
  await screen.findByRole("button", { name: "调度执行" });
}

function selectMonitorTask(code: string) {
  const label = screen.getByText(code, { selector: ".mon-task-code" });
  const button = label.closest("button");
  if (!button) throw new Error(`monitor task ${code} has no clickable row`);
  fireEvent.click(button);
}

function roleMemoryCallsFor(calls: RoleMemoryCall[], taskCode: string) {
  return calls.filter((call) => call.url.includes(`/tasks/${taskCode}/role-memory/`));
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  window.localStorage.clear();
  for (const mock of Object.values(apiMock)) mock.mockReset();
  installDefaultApi();
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("ProjectWorkstationPage task memory permissions", () => {
  it("leader_can_save_task_memory_from_real_page", async () => {
    const calls: RoleMemoryCall[] = [];
    stubRoleMemoryFetch(
      { "run-A:T-A1:coder": roleMemoryFixture("run-A", "proj-A", "T-A1", "coder") },
      calls,
    );

    renderPage("proj-A");
    await openMonitorTab();
    selectMonitorTask("T-A1");

    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    expect(await screen.findByText(/任务：T-A1/)).toBeTruthy();
    expect(input.value).toBe("优先覆盖空输入测试");

    const save = screen.getByTestId("task-role-memory-save") as HTMLButtonElement;
    const clear = screen.getByTestId("task-role-memory-clear") as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    expect(clear.disabled).toBe(false);

    fireEvent.change(input, { target: { value: "补充：先覆盖空输入" } });
    fireEvent.click(save);

    await waitFor(() => expect(roleMemoryCallsFor(calls, "T-A1").some((call) => call.method === "PUT")).toBe(true));
    const put = roleMemoryCallsFor(calls, "T-A1").find((call) => call.method === "PUT")!;
    expect(put.url).toBe("/api/runs/run-A/tasks/T-A1/role-memory/coder");
    expect(put.body).toEqual({ expected_revision: 2, manual_text: "补充：先覆盖空输入" });
    expect(put.headers["X-Bot-Id"]).toBe("bot-leader-a");
    expect(await screen.findByTestId("task-role-memory-notice")).toBeTruthy();

    // The save response advanced the revision; clearing must use the new revision.
    fireEvent.click(screen.getByTestId("task-role-memory-clear"));
    await waitFor(() => expect(roleMemoryCallsFor(calls, "T-A1").some((call) => call.method === "DELETE")).toBe(true));
    const del = roleMemoryCallsFor(calls, "T-A1").find((call) => call.method === "DELETE")!;
    expect(del.url).toContain("expected_revision=3");
    expect(del.headers["X-Bot-Id"]).toBe("bot-leader-a");
  });

  it("member_cannot_write_task_memory_from_real_page", async () => {
    const calls: RoleMemoryCall[] = [];
    stubRoleMemoryFetch(
      { "run-B:T-B1:coder": roleMemoryFixture("run-B", "proj-B", "T-B1", "coder") },
      calls,
    );

    renderPage("proj-B");
    await openMonitorTab();
    selectMonitorTask("T-B1");

    expect(await screen.findByTestId("task-role-memory-input")).toBeTruthy();
    expect(await screen.findByText(/任务：T-B1/)).toBeTruthy();

    const save = screen.getByTestId("task-role-memory-save") as HTMLButtonElement;
    const clear = screen.getByTestId("task-role-memory-clear") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(clear.disabled).toBe(true);
    expect(screen.getByText("只读：只有项目 Leader 可以编辑")).toBeTruthy();

    const get = roleMemoryCallsFor(calls, "T-B1").find((call) => call.method === "GET")!;
    expect(get.url).toBe("/api/runs/run-B/tasks/T-B1/role-memory/coder");
    expect(get.headers["X-Bot-Id"]).toBe("bot-member-b");

    // Disabled buttons cannot dispatch a write even if clicked programmatically.
    fireEvent.click(save);
    fireEvent.click(clear);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(roleMemoryCallsFor(calls, "T-B1").some((call) => call.method === "PUT")).toBe(false);
    expect(roleMemoryCallsFor(calls, "T-B1").some((call) => call.method === "DELETE")).toBe(false);
  });

  it("project_change_recomputes_task_memory_permissions", async () => {
    const calls: RoleMemoryCall[] = [];
    stubRoleMemoryFetch(
      {
        "run-A:T-A1:coder": roleMemoryFixture("run-A", "proj-A", "T-A1", "coder"),
        "run-B:T-B1:coder": roleMemoryFixture("run-B", "proj-B", "T-B1", "coder"),
      },
      calls,
    );

    const view = renderPage("proj-A");
    await openMonitorTab();
    selectMonitorTask("T-A1");
    const leaderSave = (await screen.findByTestId("task-role-memory-save")) as HTMLButtonElement;
    expect(await screen.findByText(/任务：T-A1/)).toBeTruthy();
    expect(leaderSave.disabled).toBe(false);
    expect(
      roleMemoryCallsFor(calls, "T-A1").find((call) => call.method === "GET")?.headers["X-Bot-Id"],
    ).toBe("bot-leader-a");

    // Same mount switches to project B, where the acting bot is an ordinary member.
    view.rerender(
      <MemoryRouter>
        <ProjectWorkstationPage projectId="proj-B" />
      </MemoryRouter>,
    );

    await screen.findByText("T-B1", { selector: ".mon-task-code" });
    selectMonitorTask("T-B1");

    // Wait for the freshly selected run-B task memory, not the stale project-A panel.
    expect(await screen.findByText(/任务：T-B1/)).toBeTruthy();
    const memberSave = (await screen.findByTestId("task-role-memory-save")) as HTMLButtonElement;
    const memberClear = screen.getByTestId("task-role-memory-clear") as HTMLButtonElement;
    expect(memberSave.disabled).toBe(true);
    expect(memberClear.disabled).toBe(true);
    expect(screen.getByText("只读：只有项目 Leader 可以编辑")).toBeTruthy();

    // The settled run-B read is attributed to project B's actor, not project A's leader.
    await waitFor(() => {
      const gets = roleMemoryCallsFor(calls, "T-B1").filter((call) => call.method === "GET");
      expect(gets.at(-1)?.headers["X-Bot-Id"]).toBe("bot-member-b");
    });

    fireEvent.click(memberSave);
    fireEvent.click(memberClear);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(roleMemoryCallsFor(calls, "T-B1").some((call) => call.method === "PUT")).toBe(false);
    expect(roleMemoryCallsFor(calls, "T-B1").some((call) => call.method === "DELETE")).toBe(false);
  });
});