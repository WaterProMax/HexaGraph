import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * Teacher main path on the REAL project workstation page, end to end.
 *
 *   one-line idea → 6 human gates approved → T-01/T-02 materialized
 *   → legacy + scripted execution (real worktree + real write_file tool loop)
 *   → 任务图 / 详情 / 执行监控 / 活动 all show real persisted data
 *
 * Fixture: `e2e/scripted-server.py` only (scripted provider, study-room queue,
 * temporary data dir) plus the Vite dev server. Both stay offline; ports come
 * from `playwright.integration.config.ts` (documented default 8765 → 5173,
 * overridable via TEST3_E2E_API_PORT / TEST3_E2E_WEB_PORT when a local dev
 * stack already owns that pair). The backend server injects a TEST-ONLY
 * execution policy so the *real* legacy tool-agent path can run offline;
 * `execution_safety_ready` stays False and granted_v1 is never enabled.
 * No real model, no credentials, no sandbox.
 *
 * API setup (project / gates / schedule / trace checks) uses Playwright's
 * request context with the same baseURL as the page, so the test asserts the
 * exact JSON the UI reads; the UI part then verifies the observability panels
 * render that data instead of a plain text list.
 */

declare const process: { env: Record<string, string | undefined> };

const WEB_PORT = process.env.TEST3_E2E_WEB_PORT || "5173";
const API_PORT = process.env.TEST3_E2E_API_PORT || "8765";
const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;
const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
const IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";
/** Source text written by the scripted T-01 write_file call; must never reach the task list or UI. */
const SOURCE_BODY = "def seats() -> int";

type Gate = { id: string; kind: string; status: string };

async function jsonOk(response: { ok(): boolean; status(): number; text(): Promise<string> }) {
  const body = await response.text();
  expect(response.ok(), `HTTP ${response.status()}: ${body}`).toBeTruthy();
  return body ? JSON.parse(body) : null;
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  return (await jsonOk(response)) as T;
}

/** approve every pending gate (idea confirm → issues → review → SPEC → DESIGN → PLAN). */
async function approveAllGates(request: APIRequestContext, runId: string): Promise<string[]> {
  const approved: string[] = [];
  for (let round = 0; round < 12; round += 1) {
    const run = await getJson<{ revision: number; gates: Gate[] }>(request, `/api/runs/${runId}`);
    const pending = (run.gates || []).filter((gate) => gate.status === "pending");
    if (pending.length === 0) break;
    const gate = pending[pending.length - 1];
    const response = await request.post(`/api/gates/${gate.id}/resolve`, {
      data: { decision: "approve", payload: {}, expected_revision: run.revision },
    });
    await jsonOk(response);
    approved.push(gate.kind);
  }
  return approved;
}

type PublicTask = {
  code: string;
  state: string;
  card: {
    title?: string;
    role?: string;
    depends_on?: string[];
    write_set?: string[];
    acceptance?: Array<{ cmd?: string[]; pass_criteria?: string }>;
  };
  attempt?: {
    execution_step_count?: number;
    last_execution_step?: { kind?: string; name?: string } | null;
  };
  attempt_history?: unknown[];
};

type TraceStep = {
  step: number;
  kind: string;
  name?: string;
  status?: string;
  input_summary?: string;
  output_summary?: string;
};

type ExecutionTrace = {
  task_code: string;
  execution_path?: string;
  context_injected?: boolean;
  attempts: Array<{ attempt_id: string; steps: TraceStep[] }>;
};

async function tasksOf(request: APIRequestContext, runId: string): Promise<PublicTask[]> {
  return getJson<PublicTask[]>(request, `/api/runs/${runId}/tasks`);
}

test("teacher main path: idea → tasks → execution → observability panels", async ({ page, request }) => {
  test.setTimeout(120000);
  test.info().annotations.push({
    type: "fixture",
    description:
      "offline scripted provider + test-only local execution policy; real legacy tool-agent path (write_file steps), no real model/sandbox",
  });

  // ---------------------------------------------------------------- API setup
  const project = await jsonOk(
    await request.post("/api/projects", { data: { name: "期末周自习室空位 E2E", profile: "python-pytest" } }),
  );
  expect(project?.id).toBeTruthy();
  const projectId = String(project.id);

  const created = await jsonOk(await request.post(`/api/projects/${projectId}/runs`, { data: { idea: IDEA } }));
  const runId = String(created.run.id);
  expect(runId).toBeTruthy();

  // 1. Approve the whole human gate chain; SPEC/DESIGN/PLAN must actually happen.
  const approvedKinds = await approveAllGates(request, runId);
  expect(approvedKinds).toEqual(
    expect.arrayContaining(["SPEC基线确认", "DESIGN基线确认", "PLAN基线确认"]),
  );

  // 2. The plan materialized two dependent task cards with persisted input constraints.
  let tasks = await tasksOf(request, runId);
  expect(tasks.map((task) => task.code).sort()).toEqual(["T-01", "T-02"]);
  const t01 = tasks.find((task) => task.code === "T-01")!;
  const t02 = tasks.find((task) => task.code === "T-02")!;
  expect(t01.card.role).toBe("coder");
  expect(t01.card.write_set).toEqual(["src/seats.py"]);
  expect(t02.card.role).toBe("tester");
  expect(t02.card.depends_on).toEqual(["T-01"]);
  expect(t01.card.acceptance?.[0]?.cmd?.join(" ")).toContain("pytest");

  // 3. Schedule the execution phase; the scripted queue must produce real steps.
  const scheduled = await jsonOk(await request.post(`/api/runs/${runId}/schedule`, { data: {} }));
  expect(Array.isArray(scheduled?.started)).toBeTruthy();
  await expect
    .poll(
      async () => (await tasksOf(request, runId)).find((task) => task.code === "T-01")?.state,
      { timeout: 30000, intervals: [200, 500, 1000] },
    )
    .toBe("done");
  await expect
    .poll(
      async () => (await tasksOf(request, runId)).find((task) => task.code === "T-02")?.state,
      { timeout: 30000, intervals: [200, 500, 1000] },
    )
    .toBe("done");

  // ------------------------------------------------------- API observability
  // 4a. Dedicated execution-trace route carries the attempt steps (llm + tool).
  const trace = await getJson<ExecutionTrace>(request, `/api/runs/${runId}/tasks/T-01/execution-trace`);
  expect(trace.task_code).toBe("T-01");
  expect(trace.execution_path).toBe("legacy_tool_agent");
  expect(trace.attempts.length).toBeGreaterThan(0);
  const lastAttempt = trace.attempts[trace.attempts.length - 1];
  expect(lastAttempt.steps.length).toBeGreaterThanOrEqual(2);
  const toolStep = lastAttempt.steps.find((step) => step.kind === "tool");
  expect(toolStep?.name).toBe("write_file");
  const llmStep = lastAttempt.steps.find((step) => step.kind === "llm");
  expect(llmStep).toBeTruthy();
  // The tool summary keeps path/chars/sha only — never the file body.
  expect(toolStep?.input_summary).toContain("path=src/seats.py");
  expect(toolStep?.input_summary).toContain("chars=33");
  expect(toolStep?.input_summary).not.toContain(SOURCE_BODY);

  // 4b. The task list stays step-free: no execution_steps bodies, no source code.
  const taskListResponse = await request.get(`/api/runs/${runId}/tasks`);
  const taskListText = await taskListResponse.text();
  expect(taskListText).not.toContain("execution_steps");
  expect(taskListText).not.toContain(SOURCE_BODY);
  tasks = JSON.parse(taskListText) as PublicTask[];
  const t01Public = tasks.find((task) => task.code === "T-01")!;
  // Steps are summarized, not serialized: count + last-step identity only.
  expect(t01Public.attempt?.execution_step_count).toBe(lastAttempt.steps.length);
  expect(t01Public.attempt?.last_execution_step?.kind).toBeTruthy();
  expect(t01Public.attempt_history?.length).toBeGreaterThanOrEqual(1);

  // 4c. Monitor aggregates the same honest summary.
  const monitor = await getJson<{
    tasks: Array<{ code: string; state: string; execution_step_count?: number; last_execution_step?: unknown }>;
  }>(request, `/api/runs/${runId}/monitor`);
  const monitored = monitor.tasks.find((task) => task.code === "T-01");
  expect(monitored?.state).toBe("done");
  expect(monitored?.execution_step_count).toBe(lastAttempt.steps.length);
  expect(monitored?.last_execution_step).toBeTruthy();

  // 4d. Requirement/spec → task trace links exist for the activity tab.
  const links = await getJson<Array<{ from: string; to: string; kind: string; version: string }>>(
    request,
    `/api/runs/${runId}/trace`,
  );
  expect(links.some((link) => link.kind.includes("spec_item") && link.to === "T-01")).toBeTruthy();
  expect(links.some((link) => link.to === "T-02")).toBeTruthy();

  // -------------------------------------------------------------------- UI
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  // Only the two origins of this offline suite may be contacted. Both are
  // derived, so the same spec runs on the documented or overridden ports.
  const allowedOrigins = new Set([WEB_ORIGIN, API_ORIGIN]);
  await page.route("**/*", (route) => {
    const origin = new URL(route.request().url()).origin;
    return allowedOrigins.has(origin) ? route.continue() : route.abort();
  });

  await page.goto(`/projects/${projectId}`);
  // The page opens on 项目讨论; the teacher path is the 开发任务 side.
  const tasksNav = page.getByRole("button", { name: "开发任务" });
  await expect(tasksNav).toBeVisible({ timeout: 30000 });
  await tasksNav.click();
  await expect(page.getByTestId("ws-discussion")).toHaveCount(0);
  // 开发任务 now opens the six split tabs directly (classroom grid retired).
  const workstation = page.getByTestId("project-workstation");
  await expect(workstation).toBeVisible({ timeout: 30000 });

  // 5a. 详情: main content is the persisted task card (role / depends_on / write_set / acceptance).
  await expect(page.getByTestId("tab-details")).toBeVisible();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-01");
  const constraints = page.getByTestId("input-constraints");
  await expect(constraints).toBeVisible();
  await expect(constraints).toContainText("coder");
  await expect(constraints).toContainText("src/seats.py");
  await expect(constraints).toContainText("python -m pytest tests/test_smoke.py -q");
  await expect(constraints).not.toContainText("任务备注");
  // The in-memory note is explicitly secondary and non-persisted.
  await expect(page.getByTestId("task-note-secondary")).toContainText("仅本页内存");
  await expect(page.getByTestId("task-note-secondary")).toContainText("未持久化");
  await page.screenshot({ path: test.info().outputPath("observability-01-details.png"), fullPage: true });

  // 5b. 任务图: shared ReactFlow dependency graph instead of a plain text list.
  await page.getByTestId("tab-graph").click();
  await expect(page.getByTestId("panel-graph")).toBeVisible();
  const graph = page.getByTestId("task-dependency-graph");
  await expect(graph).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".task-graph-list")).toHaveCount(0);
  const edges = page.getByTestId("task-dependency-edges");
  await expect(edges).toContainText("T-02 依赖 T-01");
  await expect(graph.locator(".react-flow__node")).toHaveCount(2);
  // T-01 is selected by default; clicking the T-02 node moves the selection.
  await expect(graph.locator(".flow-node.selected")).toContainText("T-01");
  const t02Node = graph.locator(".react-flow__node").filter({ hasText: "T-02" }).first();
  await t02Node.click();
  await expect(graph.locator(".flow-node.selected")).toContainText("T-02");
  // 任务图 is full width now: the header picker (not a side tree) reflects the selection.
  await expect(page.getByTestId("task-tree")).toHaveCount(0);
  await expect(page.getByLabel("定位任务")).toHaveValue("T-02");
  await page.screenshot({ path: test.info().outputPath("observability-02-graph.png"), fullPage: true });

  // Selecting T-02 also feeds 详情 with its own constraints.
  await page.getByTestId("tab-details").click();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-02");
  await expect(page.getByTestId("input-constraints")).toContainText("tester");
  await expect(page.getByTestId("input-constraints")).toContainText("tests/test_feature.py");
  await expect(page.getByTestId("input-constraints")).toContainText("T-01");

  // 5c. 执行监控: pick the executed T-01 and read its step trace, effort and cost copy.
  await page.getByTestId("tab-monitor").click();
  const monitorPanel = page.getByTestId("run-monitor");
  await expect(monitorPanel).toBeVisible({ timeout: 20000 });
  await expect(monitorPanel.getByTestId("monitor-kpis")).toBeVisible();
  const t01Row = monitorPanel.locator(".mon-task").filter({ hasText: "T-01" }).first();
  await expect(t01Row).toBeVisible({ timeout: 20000 });
  await t01Row.click();
  const tracePanel = monitorPanel.getByTestId("execution-trace");
  await expect(tracePanel).toBeVisible({ timeout: 20000 });
  const stepItems = tracePanel.locator('li[data-testid^="execution-step-"]');
  await expect(stepItems).toHaveCount(lastAttempt.steps.length, { timeout: 20000 });
  await expect(tracePanel.getByTestId("execution-step-2")).toContainText("工具 write_file");
  await expect(tracePanel.getByTestId("execution-step-input-2")).toContainText("path=src/seats.py");
  await expect(tracePanel.getByTestId("execution-step-input-2")).toContainText("chars=33");
  // LLM step shows model/slot summary, not the raw prompt.
  await expect(tracePanel.getByTestId("execution-step-1")).toContainText("模型");
  await expect(tracePanel.getByTestId("execution-step-1")).toContainText("Token");
  // Honest context-injection note for the legacy path (hash frozen, shared skill not loaded).
  await expect(tracePanel.getByTestId("execution-context-state")).toBeVisible();
  await expect(tracePanel.getByTestId("execution-context-injected")).toContainText("已注入角色/手动段");
  // Attempt history is adjacent to the steps.
  await expect(monitorPanel.getByTestId("attempt-history")).toBeVisible({ timeout: 20000 });
  // Cost is honestly labelled as unpriced, and no source body leaks into the page.
  await expect(tracePanel.getByTestId("execution-trace-cost")).toHaveText("费用：当前未计价");
  await expect(page.locator("body")).not.toContainText(SOURCE_BODY);
  await page.screenshot({ path: test.info().outputPath("observability-03-monitor.png"), fullPage: true });

  // 5d. 活动: inline event feed + requirement trace table, not just external links.
  await page.getByTestId("tab-activity").click();
  const activity = page.getByTestId("panel-activity");
  await expect(activity).toBeVisible();
  await expect(activity.getByTestId("requirement-trace-panel")).toBeVisible();
  const traceTable = activity.getByTestId("requirement-trace-table");
  await expect(traceTable).toBeVisible({ timeout: 20000 });
  await expect(traceTable).toContainText("T-01");
  await expect(activity.getByTestId("requirement-trace-link").first()).toBeVisible();
  // V2: the activity tab now embeds the full event timeline (no 20-row feed).
  await expect(activity.getByTestId("timeline-events")).toBeVisible();
  await expect(activity.getByTestId("timeline-event").first()).toBeVisible({ timeout: 20000 });
  await expect(activity.getByTestId("timeline-event-summary").first()).toBeVisible();
  await expect(activity.getByTestId("timeline-count")).toContainText("共");
  await expect(activity.getByTestId("activity-feed")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("observability-04-activity.png"), fullPage: true });

  expect(pageErrors, `page errors: ${pageErrors.join(" | ")}`).toEqual([]);
});