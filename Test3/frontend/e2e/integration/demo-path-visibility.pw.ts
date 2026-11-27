import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * V4 → v1.36: the classroom main path on `/projects/:id` with split tabs.
 *
 *   详情（规格 + 约束）| 任务图 | 任务派发 | 执行监控（样式切换）| 活动（完整事件时间线）
 *
 * The retired one-screen demo grid now lives only in the read-only static
 * project; the live project page always uses the split tabs.
 *
 * Fixture: e2e/scripted-server.py only (scripted provider, study-room queue,
 * temporary data dir, test-only local execution policy). `execution_safety_ready`
 * stays False; no real model, no credentials, no sandbox.
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
  assignment?: { assignee_display_name: string } | null;
};

test("classroom main path: split tabs for spec, graph, dispatch, monitor and timeline", async ({ page, request }) => {
  test.setTimeout(180000);
  test.info().annotations.push({
    type: "fixture",
    description: "offline scripted provider; no real model/sandbox; main path stays on /projects/:id",
  });

  // ------------------------------------------------------------- API setup
  const project = await jsonOk(
    await request.post("/api/projects", { data: { name: "课上演示可见性 E2E", profile: "python-pytest" } }),
  );
  const projectId = String(project.id);

  const leaderBot = await jsonOk(
    await request.post("/api/bots", {
      data: { display_name: "Demo Leader", role_template: "developer", provider_ref: "dashscope", model: "scripted", slot: "coder", secret_ref: "" },
    }),
  );
  const memberBot = await jsonOk(
    await request.post("/api/bots", {
      data: { display_name: "Demo Member", role_template: "developer", provider_ref: "dashscope", model: "scripted", slot: "coder", secret_ref: "" },
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

  const tasks = await getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`);
  expect(tasks.map((task) => task.code).sort()).toEqual(["T-01", "T-02"]);

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

  // 1. 开发任务 opens the split tabs directly; the classroom grid and its switch are gone.
  await expect(page.getByTestId("panel-details")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("demo-context")).toBeVisible();
  await expect(page.getByTestId("context-leader")).toContainText("Demo Leader");
  await expect(page.getByTestId("demo-workbench")).toHaveCount(0);
  await expect(page.getByTestId("layout-mode-switch")).toHaveCount(0);

  // 2. Full approved SPEC is on the details tab (scripted path: artifact fallback, all features).
  const specPanel = page.getByTestId("approved-spec-panel");
  await expect(specPanel).toBeVisible({ timeout: 30000 });
  await expect(specPanel.getByTestId("approved-spec-artifact")).toBeVisible({ timeout: 30000 });
  await expect(specPanel.getByTestId("approved-spec-feature")).toHaveCount(3);
  await expect(specPanel).toContainText("按楼层查看剩余座位");
  await expect(specPanel).toContainText("上报剩余座位");
  await expect(specPanel).toContainText("收藏教室");
  await expect(page.getByTestId("context-spec")).toContainText("已批准规格");
  // The selected task's constraints share the details tab.
  await expect(page.getByTestId("input-constraints")).toContainText("coder");
  await expect(page.getByTestId("input-constraints")).toContainText("src/seats.py");

  // 3. Graph, dispatch board, monitor and full timeline each own a tab.
  await page.getByTestId("tab-graph").click();
  await expect(page.getByTestId("task-dependency-graph")).toBeVisible();
  await expect(page.getByTestId("task-dependency-edges")).toContainText("T-02 依赖 T-01");
  await page.getByTestId("tab-assignment").click();
  await expect(page.getByTestId("assignment-board")).toBeVisible();
  await page.getByTestId("tab-monitor").click();
  await expect(page.getByTestId("run-monitor")).toBeVisible();
  await expect(page.getByTestId("monitor-kpis")).toBeVisible();
  await page.getByTestId("tab-activity").click();
  await expect(page.getByTestId("timeline-events")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("timeline-count")).toContainText("共");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: test.info().outputPath("demo-path-00-initial.png"), fullPage: true });

  // 4. Dispatch stays the visible classroom overlay (the write path itself is covered by
  // assignment-monitor-demo.pw.ts; this spec asserts the board is reachable in one click).
  await page.getByTestId("tab-assignment").click();
  const board = page.getByTestId("assignment-board");
  await expect(board).toBeVisible();
  await expect(page.getByTestId("assignment-semantics-note")).toContainText("不会改记忆主语");
  await expect(page.getByTestId("assignment-select-T-01")).toBeVisible();
  await expect(page.getByTestId("assignment-select-T-01")).toBeEnabled();

  // 5. The graph drives the shared selection: the details constraints follow T-02.
  await page.getByTestId("tab-graph").click();
  const t02Node = page.locator(".react-flow__node").filter({ hasText: "T-02" }).first();
  await t02Node.click();
  await page.getByTestId("tab-details").click();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-02");
  await expect(page.getByTestId("input-constraints")).toContainText("tester");

  // 6. Make sure the scripted run executed, then switch observation styles inside the monitor.
  const runInfo = await getJson<{ status: string }>(request, `/api/runs/${runId}`);
  if (!["done", "terminated"].includes(runInfo.status)) {
    await jsonOk(await request.post(`/api/runs/${runId}/schedule`, { data: {} }));
  }
  await expect
    .poll(async () => (await getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`)).find((task) => task.code === "T-02")?.state, {
      timeout: 60000,
      intervals: [300, 1000],
    })
    .toBe("done");

  await page.getByTestId("tab-monitor").click();
  const monitor = page.getByTestId("run-monitor");
  await monitor.locator("button", { hasText: "T-02" }).first().click();
  await expect(monitor.getByTestId("monitor-detail-role")).toContainText("tester", { timeout: 30000 });
  const trace = monitor.getByTestId("execution-trace");
  await expect(trace).toBeVisible({ timeout: 30000 });
  await expect(trace.getByTestId("observation-style-switch")).toBeVisible();
  await trace.getByTestId("observation-style-option-table").click();
  await expect(trace.getByTestId("observation-table")).toBeVisible();
  await trace.getByTestId("observation-style-option-json").click();
  await expect(trace.getByTestId("observation-json")).toContainText("T-02");
  await expect(trace.getByTestId("observation-export")).toBeEnabled();
  await trace.getByTestId("observation-style-option-timeline").click();
  await expect(trace.getByTestId("execution-step-1")).toBeVisible();

  // The full event timeline lives on the activity tab (one event source per view).
  await page.getByTestId("tab-activity").click();
  await expect(page.getByTestId("timeline-events")).toBeVisible();
  await expect(page.getByTestId("timeline-event").first()).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: test.info().outputPath("demo-path-01-workbench.png"), fullPage: true });

  // 7. Discussion round-trip keeps Leader, spec and selection context.
  await page.getByTestId("context-back-to-discussion").click();
  await expect(page.getByTestId("ws-discussion")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("panel-details")).toHaveCount(0);
  await page.getByRole("button", { name: "开发任务" }).click();
  await expect(page.getByTestId("panel-activity")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("context-leader")).toContainText("Demo Leader");
  await page.getByTestId("tab-details").click();
  await expect(page.getByTestId("approved-spec-panel")).toBeVisible();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-02");

  // 8. All six tabs stay available, including the evaluation and activity views.
  await expect(page.getByTestId("tab-details")).toBeVisible();
  await expect(page.getByTestId("tab-evaluation")).toBeVisible();
  await page.getByTestId("tab-activity").click();
  await expect(page.getByTestId("panel-activity")).toBeVisible();
  await expect(page.getByTestId("timeline-events")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("requirement-trace-panel")).toBeVisible();

  // The whole demo stayed on the project main path.
  expect(page.url()).toContain(`/projects/${projectId}`);
  expect(page.url()).not.toContain("/workstation/");
  expect(pageErrors, `page errors: ${pageErrors.join(" | ")}`).toEqual([]);
});