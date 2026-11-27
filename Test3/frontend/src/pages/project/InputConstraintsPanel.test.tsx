import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InputConstraintsPanel, type TaskInputConstraints } from "./InputConstraintsPanel";

const apiMock = vi.hoisted(() => ({
  artifacts: vi.fn(),
  taskRoleMemory: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  api: {
    artifacts: apiMock.artifacts,
    taskRoleMemory: apiMock.taskRoleMemory,
  },
  // The raw field panel only catches errors; the class identity just needs to exist.
  ApiError: class ApiError extends Error {
    status: number;
    category?: string;
    constructor(message: string, status = 0, category?: string) {
      super(message);
      this.status = status;
      this.category = category;
    }
  },
}));

const task: TaskInputConstraints = {
  code: "T-02",
  title: "接通座位查询与上报表单",
  role: "coder",
  dependsOn: ["T-01"],
  writeSet: ["src/seats.py", "tests/test_seats.py"],
  acceptance: [{ cmd: ["python", "-m", "pytest", "tests/test_seats.py", "-q"], passCriteria: "全部通过" }],
  description: "按接口契约实现查询与上报。",
  module: "M2",
  parent: "WP-01",
  points: 2,
  budget: { max_tool_steps: 30, max_tokens: 1500000, max_seconds: 600 },
};

const memoryFixture = {
  run_id: "run-1",
  project_id: "proj-1",
  task_code: "T-02",
  role: "coder" as const,
  revision: 2,
  manual_text: "先覆盖空输入",
  manual_updated_by: "bot-leader",
  manual_updated_at: "2026-11-25T00:00:00+00:00",
  role_snapshot: {
    text: "任务：T-02\n角色：coder",
    sources: [{ kind: "task_card", ref: "T-02", sha256: "a".repeat(64) }],
    matcher_version: "task-role-v1",
  },
  role_section: {
    kind: "task_role",
    source_id: "T-02:coder",
    source_version: "task-role-v1",
    text: "任务：T-02\n角色：coder",
    sha256: "a".repeat(64),
  },
  manual_section: {
    kind: "task_manual",
    source_id: "T-02:coder",
    source_version: "2",
    text: "先覆盖空输入",
    sha256: "c".repeat(64),
  },
  context_hash: "d".repeat(64),
  frozen: false,
  frozen_context: {},
  effective: "current",
};

beforeEach(() => {
  apiMock.artifacts.mockReset().mockResolvedValue({});
  apiMock.taskRoleMemory.mockReset().mockResolvedValue(memoryFixture);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("InputConstraintsPanel", () => {
  it("shows the persisted task-card inputs: role, depends_on, write_set and acceptance", () => {
    render(<InputConstraintsPanel task={task} />);
    const meta = screen.getByTestId("input-task-meta").textContent || "";
    expect(meta).toContain("coder");
    expect(meta).toContain("T-01");
    expect(meta).toContain("src/seats.py");
    expect(meta).toContain("M2");
    expect(meta).toContain("最多 30 个工具步骤");
    expect(screen.getByTestId("input-acceptance").textContent).toContain("python -m pytest");
    expect(screen.getByTestId("input-acceptance").textContent).toContain("全部通过");
    expect(screen.getByTestId("input-task-description").textContent).toContain("按接口契约实现查询与上报");
  });

  it("states the honest simulated/granted context copy when nothing was injected", () => {
    render(<InputConstraintsPanel task={{ ...task, contextInjected: false, executionPath: "simulated" }} />);
    expect(screen.getByTestId("input-context-state").textContent).toContain(
      "本尝试仅冻结上下文哈希，未向模型提示词注入任务上下文（路径：simulated / granted_v1）",
    );
  });

  it("says the shared skill bundle was not loaded instead of claiming imported skills", () => {
    render(
      <InputConstraintsPanel
        task={{ ...task, contextInjected: true, executionPath: "legacy_tool_agent", skillBundleHash: "" }}
      />,
    );
    const text = screen.getByTestId("input-context-state").textContent || "";
    expect(text).toContain("已注入角色/手动段；公共 skill 包未导入或加载失败");
    expect(text).not.toContain("已导入");
    expect(screen.queryByText(/20 个技能/)).toBeNull();
  });

  it("treats a frozen skill hash as a record only, never as proof of imported skills", () => {
    render(
      <InputConstraintsPanel
        task={{ ...task, contextInjected: true, skillBundleHash: "f".repeat(64) }}
      />,
    );
    const text = screen.getByTestId("input-context-state").textContent || "";
    expect(text).toContain("ffffffffffff");
    expect(text).toContain("不代表已加载的技能数量");
    expect(text).not.toContain("已导入");
    expect(text).not.toContain("20 个技能");
  });

  it("keeps the other sections when the approved SPEC cannot be loaded", async () => {
    apiMock.artifacts.mockRejectedValue(new Error("offline"));
    render(<InputConstraintsPanel task={task} runId="run-1" />);
    expect(await screen.findByTestId("input-spec-error")).toBeTruthy();
    expect(screen.getByTestId("input-spec-error").textContent).toContain("暂时无法载入已批准规格");
    // A SPEC read failure must not blank the constraints.
    expect(screen.getByTestId("input-task-meta").textContent).toContain("src/seats.py");
  });

  it("summarises the approved SPEC counts and features when the read succeeds", async () => {
    apiMock.artifacts.mockResolvedValue({
      baseline_SPEC: "1.2",
      spec: {
        scenarios: [{ code: "S1" }, { code: "S2" }],
        features: [
          { code: "F1", title: "座位查询" },
          { code: "F2", title: "上报表单" },
          { code: "F3", title: "限频" },
          { code: "F4", title: "告警" },
        ],
        nonfunc: [{ code: "N1", title: "响应时间" }],
        out_of_scope: [],
        open_questions: [],
      },
    });
    render(<InputConstraintsPanel task={task} runId="run-1" />);
    expect(await screen.findByTestId("input-spec-body")).toBeTruthy();
    const text = screen.getByTestId("input-spec-body").textContent || "";
    expect(text).toContain("基线 v1.2");
    expect(text).toContain("场景 2");
    expect(text).toContain("功能 4");
    expect(text).toContain("非功能 1");
    expect(text).toContain("座位查询");
    expect(text).toContain("还有 1 项功能");
  });

  it("reuses the task/role memory panel read-only when a run and actor identify the role", async () => {
    render(<InputConstraintsPanel task={task} runId="run-1" actorBotId="bot-leader" />);
    expect(await screen.findByTestId("task-role-memory")).toBeTruthy();
    const input = screen.getByTestId("task-role-memory-input") as HTMLTextAreaElement;
    expect(input.readOnly).toBe(true);
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).disabled).toBe(true);
  });

  it("guides the reader with Chinese copy when no task is selected", () => {
    render(<InputConstraintsPanel />);
    expect(screen.getByTestId("input-constraints-empty").textContent).toContain("在左侧选择一个任务");
  });
});