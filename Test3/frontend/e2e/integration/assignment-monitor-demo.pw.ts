import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * A6: the classroom one-line demo on /projects/:id — never /workstation/:id.
 *
 *   成员 + Leader → 开发任务 → 任务图 → 任务派发（Leader 把 T-01 派给成员）
 *   → 执行监控（角色 + 派发对象 + 完成情况）→ 观测样式切换/导出
 *
 * Fixture: e2e/scripted-server.py only (scripted provider, study-room queue,
 * temporary data dir, test-only local execution policy). execution_safety_ready
 * stays False; no real model, no credentials, no sandbox. The assignment PUT
 * is the real backend route added by A1 — no scripted stub is needed.
 */

declare const process: { env: Record<string, string | undefined> };

const WEB_PORT = process.env.TEST3_E2E_WEB_PORT || "5173";
const API_PORT = process.env.TEST3_E2E_API_PORT || "8765";
const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;
const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
const IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";

type Gate = { id: string; kind: string; status: string };

async function jsonOk(response: { ok(): boolean; status(): number; text(): Promise<string> }) {
  const body = await response.text();
  expect(response.ok(), `HTTP ${response.status()}: ${body}`).toBeTruthy();
  return body ? JSON.parse(body) : null;
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  return (await jsonOk(await request.get(path))) as T;
}

async function approveAllGates(request: APIRequestContext, runId: string): Promise<void> {
  for (let round = 0; round < 12; round += 1) {
    const run = await getJson<{ revision: number; gates: Gate[] }>(request, `/api/runs/${runId}`);
    const pending = (run.gates || []).filter((gate) => gate.status === "pending");
    if (pending.length === 0) break;
    const gate = pending[pending.length - 1];
    await jsonOk(
      await request.post(`/api/gates/${gate.id}/resolve`, {
        data: { decision: "approve", payload: {}, expected_revision: run.revision },
      }),
    );
  }
}

type PublicTask = {
  code: string;
  state: string;
  revision: number;
  assignment: { assignee_bot_id: string; assignee_display_name: string } | null;
};

test("classroom demo: members/Leader → dispatch → monitor → observation styles", async ({ page, request }) => {
  test.setTimeout(150000);
  test.info().annotations.push({
    type: "fixture",
    description: "offline scripted provider; real assignment API; no real model/sandbox; main path stays on /projects/:id",
  });

  // ------------------------------------------------------------- API setup
  const project = await jsonOk(
    await request.post("/api/projects", { data: { name: "派发演示 E2E", profile: "python-pytest" } }),
  );
  const projectId = String(project.id);

  // Two project members with exactly one Leader (the group-chat precondition).
  const leaderBot = await jsonOk(
    await request.post("/api/bots", {
      data: { display_name: "E2E Leader", role_template: "developer", provider_ref: "dashscope", model: "scripted", slot: "coder", secret_ref: "" },
    }),
  );
  const memberBot = await jsonOk(
    await request.post("/api/bots", {
      data: { display_name: "E2E Member", role_template: "developer", provider_ref: "dashscope", model: "scripted", slot: "coder", secret_ref: "" },
    }),
  );
  await jsonOk(
    await request.post(`/api/projects/${projectId}/memberships`, {
      data: { bot_id: leaderBot.bot_id, role_in_project: "dev", is_leader: true },
    }),
  );
  await jsonOk(
    await request.post(`/api/projects/${projectId}/memberships`, {
      data: { bot_id: memberBot.bot_id, role_in_project: "dev", is_leader: false },
    }),
  );

  const created = await jsonOk(await request.post(`/api/projects/${projectId}/runs`, { data: { idea: IDEA } }));
  const runId = String(created.run.id);
  await approveAllGates(request, runId);

  // Unassigned tasks are honestly null before any dispatch.
  let tasks = await getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`);
  expect(tasks.map((task) => task.code).sort()).toEqual(["T-01", "T-02"]);
  expect(tasks.every((task) => task.assignment === null)).toBeTruthy();

  // -------------------------------------------------------------------- UI
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const allowedOrigins = new Set([WEB_ORIGIN, API_ORIGIN]);
  await page.route("**/*", (route) => {
    const origin = new URL(route.request().url()).origin;
    return allowedOrigins.has(origin) ? route.continue() : route.abort();
  });

  await page.goto(`/projects/${projectId}`);
  const tasksNav = page.getByRole("button", { name: "开发任务" });
  await expect(tasksNav).toBeVisible({ timeout: 30000 });
  await tasksNav.click();
  // 开发任务 now opens the six-tab split view directly (classroom grid retired).
  await expect(page.getByTestId("project-workstation")).toBeVisible({ timeout: 30000 });

  // 1. 任务图: dependencies + role are visible before dispatch.
  await page.getByTestId("tab-graph").click();
  await expect(page.getByTestId("task-dependency-edges")).toContainText("T-02 依赖 T-01", { timeout: 20000 });
  await expect(page.getByTestId("graph-assignee-T-01")).toContainText("未派发");

  // 2. 任务派发: the Leader is visible with the team, and dispatch is one select.
  await page.getByTestId("tab-assignment").click();
  const board = page.getByTestId("assignment-board");
  await expect(board).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("assignment-team")).toContainText("E2E Leader");
  await expect(page.getByTestId("assignment-team")).toContainText("E2E Member");
  await expect(page.getByTestId("assignment-semantics-note")).toContainText("不会改记忆主语");
  await expect(page.getByTestId("assignment-assignee-T-01")).toContainText("尚未派发");
  await expect(page.getByTestId("assignment-back-to-discussion")).toBeVisible();

  const select = page.getByTestId("assignment-select-T-01");
  await expect(select).toBeEnabled();
  await select.selectOption(memberBot.bot_id);
  await expect(page.getByTestId("assignment-assignee-T-01")).toContainText("E2E Member", { timeout: 20000 });

  // The overlay is persisted and readable through the public API.
  tasks = await getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`);
  const t01 = tasks.find((task) => task.code === "T-01")!;
  expect(t01.assignment?.assignee_bot_id).toBe(memberBot.bot_id);
  expect(t01.assignment?.assignee_display_name).toBe("E2E Member");
  expect(tasks.find((task) => task.code === "T-02")?.assignment).toBeNull();

  // A non-Leader member cannot write the overlay (read-only for members).
  const forbidden = await request.put(`/api/runs/${runId}/tasks/T-02/assignment`, {
    headers: { "X-Bot-Id": memberBot.bot_id },
    data: { assignee_bot_id: memberBot.bot_id, expected_revision: tasks.find((task) => task.code === "T-02")!.revision },
  });
  expect(forbidden.status()).toBe(403);

  // 3. The graph badge reflects the dispatch without a second graph.
  await page.getByTestId("tab-graph").click();
  await expect(page.getByTestId("graph-assignee-T-01")).toContainText("E2E Member", { timeout: 20000 });
  await expect(page.getByTestId("graph-assignee-T-02")).toContainText("未派发");
  await page.screenshot({ path: test.info().outputPath("assignment-01-graph.png"), fullPage: true });

  // 4. Schedule still works with T-02 unassigned (no dispatch gate), then the
  //    monitor shows role + assignee + completion on the same screen.
  await jsonOk(await request.post(`/api/runs/${runId}/schedule`, { data: {} }));
  await expect
    .poll(async () => (await getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`)).find((task) => task.code === "T-02")?.state, {
      timeout: 45000,
      intervals: [300, 1000],
    })
    .toBe("done");

  await page.getByTestId("tab-monitor").click();
  const monitorPanel = page.getByTestId("run-monitor");
  await expect(monitorPanel).toBeVisible({ timeout: 20000 });
  await expect(monitorPanel.getByTestId("monitor-task-assignee-T-01")).toContainText("E2E Member", { timeout: 30000 });
  await expect(monitorPanel.getByTestId("monitor-task-assignee-T-02")).toContainText("未派发");
  await expect(monitorPanel.getByTestId("monitor-assigned-kpi")).toContainText("1/2");

  const t01Row = monitorPanel.locator(".mon-task").filter({ hasText: "T-01" }).first();
  await t01Row.click();
  await expect(monitorPanel.getByTestId("monitor-detail-role")).toContainText("coder");
  await expect(monitorPanel.getByTestId("monitor-detail-assignee")).toContainText("E2E Member");

  // 5. Observation styles on the real scripted trace: switch + export affordance.
  const tracePanel = monitorPanel.getByTestId("execution-trace");
  await expect(tracePanel).toBeVisible({ timeout: 20000 });
  await expect(tracePanel.getByTestId("observation-style-switch")).toBeVisible();
  await tracePanel.getByTestId("observation-style-option-table").click();
  await expect(tracePanel.getByTestId("observation-table")).toBeVisible();
  await expect(tracePanel.getByTestId("observation-table")).toContainText("write_file");
  await tracePanel.getByTestId("observation-style-option-json").click();
  await expect(tracePanel.getByTestId("observation-json")).toContainText("T-01");
  await expect(tracePanel.getByTestId("observation-export")).toBeEnabled();
  await tracePanel.getByTestId("observation-style-option-timeline").click();
  await expect(tracePanel.getByTestId("execution-step-1")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("assignment-02-monitor.png"), fullPage: true });

  // The whole demo stayed on the project main path.
  expect(page.url()).toContain(`/projects/${projectId}`);
  expect(page.url()).not.toContain("/workstation/");
  expect(pageErrors, `page errors: ${pageErrors.join(" | ")}`).toEqual([]);
});