import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

/**
 * Task/role memory on the REAL workstation page (ProjectWorkstationPage ->
 * RunMonitorPanel -> TaskRoleMemoryPanel) against the real offline backend.
 *
 * Fixture: `e2e/discussion-server.py` (scripted provider, simulated executor,
 * temporary data dir) on 127.0.0.1:8766; Vite on 127.0.0.1:5174. No real model,
 * no real sandbox/repo write.
 *
 * The run is created by the test-only `POST /api/e2e/seed-workstation-run` route.
 * Seed exists only because POST /discussion-sessions/{id}/plan currently 500s
 * due to an uncommitted backend WIP checkpoint regression; the workstation page
 * and task role-memory APIs exercised here are the real ones (the seed uses the
 * real bench helpers and the published discussion-e2e fixture plan, and it never
 * fakes a memory response).
 */

const API = "http://127.0.0.1:8766/api";
const FRONTEND = "http://127.0.0.1:5174";
const GATE = `${API}/e2e/discussion-gate`;
const SEED = `${API}/e2e/seed-workstation-run`;
const IDEA = "做一个能按楼层查看自习室剩余座位并允许到场学生上报的小程序。";
const MEMORY_TEXT = "本任务优先使用参数化查询；不要在查询路径里写死楼层枚举。";

type SeededTask = { code: string; role: string };

type SeededRun = {
  runId: string;
  projectId: string;
  leaderId: string;
  memberId: string;
  tasks: SeededTask[];
};

const botHeaders = (botId: string) => ({ "X-Bot-Id": botId });

async function requireDiscussionSuite(request: APIRequestContext): Promise<boolean> {
  const health = await request.get(`${API}/health`).catch(() => null);
  const frontend = await request.get(FRONTEND).catch(() => null);
  const ready = Boolean(health?.ok() && frontend?.ok());
  test.skip(
    !ready,
    "run with playwright.discussion.config.ts (scripted backend 8766 + vite 5174)",
  );
  return ready;
}

/** The gate is not needed here, but a crashed sibling must not leave it holding. */
async function resetGateIfPresent(request: APIRequestContext): Promise<void> {
  const snapshot = await request.get(GATE).catch(() => null);
  if (!snapshot || !snapshot.ok()) return;
  const response = await request.post(GATE, { data: { released: true } });
  expect(response.status(), await response.text()).toBe(200);
}

/**
 * TEST-ONLY setup: materialize project + leader/member bots + memberships + a run
 * whose tasks carry the fixture coder/tester cards. Returns null when an external
 * backend does not expose the seed route (so the spec can skip, never mis-run).
 */
async function seedWorkstationRun(request: APIRequestContext): Promise<SeededRun | null> {
  const response = await request.post(SEED, { data: { idea: IDEA } });
  if (response.status() === 404) return null;
  expect(response.ok(), await response.text()).toBeTruthy();
  const payload = (await response.json()) as {
    run_id: string;
    project_id: string;
    leader_bot_id: string;
    member_bot_id: string;
    tasks: SeededTask[];
  };
  return {
    runId: payload.run_id,
    projectId: payload.project_id,
    leaderId: payload.leader_bot_id,
    memberId: payload.member_bot_id,
    tasks: payload.tasks,
  };
}

/** Opens the project page, switches to the task workspace, and returns the task panel. */
async function openMonitor(page: Page, projectId: string, taskCode: string): Promise<Locator> {
  await page.goto(`/projects/${projectId}`);
  return showTaskPanel(page, taskCode);
}

async function selectTask(page: Page, taskCode: string): Promise<Locator> {
  const row = page.locator(".mon-task").filter({ hasText: taskCode }).first();
  await expect(row).toBeVisible({ timeout: 30000 });
  await row.click();
  const panel = page.getByTestId("task-role-memory");
  await expect(panel).toBeVisible({ timeout: 20000 });
  return panel;
}

/** Assumes the project page is already loaded (openMonitor or page.reload). */
async function showTaskPanel(page: Page, taskCode: string): Promise<Locator> {
  const tasksNav = page.getByRole("button", { name: "开发任务" });
  await expect(tasksNav).toBeVisible({ timeout: 30000 });
  await tasksNav.click();
  await expect(page.getByTestId("tab-monitor")).toBeVisible({ timeout: 20000 });
  await page.getByTestId("tab-monitor").click();
  return selectTask(page, taskCode);
}

type ErrorTracker = {
  pageErrors: string[];
  consoleErrors: string[];
  assertClean: () => void;
};

const CONSOLE_NOISE = [
  /Failed to load resource/i,
  /net::ERR_/i,
  /fonts\.googleapis/i,
  /\[antd:/i,
  /^Warning:/,
  /React Router Future Flag/i,
];

function trackErrors(page: Page): ErrorTracker {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (CONSOLE_NOISE.some((pattern) => pattern.test(text))) return;
    consoleErrors.push(text);
  });
  return {
    pageErrors,
    consoleErrors,
    assertClean: () => {
      expect(pageErrors, `page errors: ${pageErrors.join(" | ")}`).toEqual([]);
      expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
    },
  };
}

function routeLocalOnly(page: Page): Promise<unknown> {
  return page.route("**/*", (route) => {
    const origin = new URL(route.request().url()).origin;
    return origin === FRONTEND ? route.continue() : route.abort();
  });
}

test("scripted: Leader saves, restores and clears task role memory", async ({ page, request }) => {
  test.setTimeout(120000);
  test.info().annotations.push({
    type: "fixture",
    description:
      "scripted provider + simulated executor; seeded run (POST /plan backend regression); no real model/sandbox",
  });
  if (!(await requireDiscussionSuite(request))) return;
  await resetGateIfPresent(request);
  const seeded = await seedWorkstationRun(request);
  test.skip(!seeded, "test-only seed route missing (external backend? run e2e/discussion-server.py)");
  if (!seeded) return;
  const errors = trackErrors(page);
  await routeLocalOnly(page);

  expect(seeded.tasks.map((task) => task.code).sort()).toEqual(["T1", "T2", "T3", "T4"]);
  expect(seeded.tasks).toEqual(
    expect.arrayContaining([
      { code: "T1", role: "coder" },
      { code: "T2", role: "tester" },
    ]),
  );
  const roleMemoryUrl = `${API}/runs/${seeded.runId}/tasks/T1/role-memory/coder`;

  // The panel only mounts for coder/tester roles read from the real monitor API.
  const monitor = (await (await request.get(`${API}/runs/${seeded.runId}/monitor`)).json()) as {
    tasks?: Array<{ code: string; role: string }>;
  };
  expect(monitor.tasks?.find((task) => task.code === "T1")?.role).toBe("coder");

  const panel = await openMonitor(page, seeded.projectId, "T1");
  await expect(panel).toContainText("任务记忆 · coder");
  await expect(panel.getByTestId("task-role-memory-input")).toBeEditable();
  await expect(panel.getByTestId("task-role-memory-input")).toHaveValue("");
  await expect(panel.getByTestId("task-role-memory-clear")).toBeDisabled();

  const saveRequest = page.waitForRequest(
    (req) =>
      req.method() === "PUT" &&
      new URL(req.url()).pathname ===
        `/api/runs/${seeded.runId}/tasks/T1/role-memory/coder`,
  );
  await panel.getByTestId("task-role-memory-input").fill(MEMORY_TEXT);
  await panel.getByTestId("task-role-memory-save").click();
  const save = await saveRequest;
  expect(save.headers()["x-bot-id"]).toBe(seeded.leaderId);
  expect(save.postDataJSON()).toEqual({ expected_revision: 0, manual_text: MEMORY_TEXT });
  await expect(panel.getByTestId("task-role-memory-notice")).toHaveText(
    "已保存，供后续新建尝试使用。",
  );
  await expect(panel).toContainText("revision 1");

  const saved = (await (
    await request.get(roleMemoryUrl, { headers: botHeaders(seeded.leaderId) })
  ).json()) as { revision: number; manual_text: string };
  expect(saved.manual_text).toBe(MEMORY_TEXT);
  expect(saved.revision).toBe(1);

  // Refresh-restore: a fresh page load rebuilds the panel from the server.
  await page.reload();
  const restored = await showTaskPanel(page, "T1");
  await expect(restored.getByTestId("task-role-memory-input")).toHaveValue(MEMORY_TEXT);
  await expect(restored).toContainText("revision 1");

  const clearRequest = page.waitForRequest(
    (req) =>
      req.method() === "DELETE" &&
      new URL(req.url()).pathname ===
        `/api/runs/${seeded.runId}/tasks/T1/role-memory/coder`,
  );
  await restored.getByTestId("task-role-memory-clear").click();
  const clearedRequest = await clearRequest;
  expect(clearedRequest.headers()["x-bot-id"]).toBe(seeded.leaderId);
  expect(new URL(clearedRequest.url()).searchParams.get("expected_revision")).toBe("1");
  await expect(restored.getByTestId("task-role-memory-notice")).toContainText("已清空");
  await expect(restored).toContainText("revision 2");
  await expect(restored.getByTestId("task-role-memory-input")).toHaveValue("");
  await expect(restored.getByTestId("task-role-memory-clear")).toBeDisabled();

  const cleared = (await (
    await request.get(roleMemoryUrl, { headers: botHeaders(seeded.leaderId) })
  ).json()) as { revision: number; manual_text: string };
  expect(cleared.manual_text).toBe("");
  expect(cleared.revision).toBe(2);
  errors.assertClean();
});

test("scripted: non-leader member reads task role memory read-only", async ({ page, request }) => {
  test.setTimeout(120000);
  test.info().annotations.push({
    type: "fixture",
    description:
      "scripted provider + simulated executor; seeded run (POST /plan backend regression); no real model/sandbox",
  });
  if (!(await requireDiscussionSuite(request))) return;
  await resetGateIfPresent(request);
  const seeded = await seedWorkstationRun(request);
  test.skip(!seeded, "test-only seed route missing (external backend? run e2e/discussion-server.py)");
  if (!seeded) return;
  const errors = trackErrors(page);
  await routeLocalOnly(page);
  const roleMemoryUrl = `${API}/runs/${seeded.runId}/tasks/T1/role-memory/coder`;

  // Leader authors the memory first, then loses membership so the page actor
  // falls back to the remaining project member (no login/member switch exists).
  const authored = await request.put(roleMemoryUrl, {
    headers: botHeaders(seeded.leaderId),
    data: { expected_revision: 0, manual_text: MEMORY_TEXT },
  });
  expect(authored.ok(), await authored.text()).toBeTruthy();
  const removed = await request.delete(
    `${API}/projects/${seeded.projectId}/memberships/${seeded.leaderId}`,
  );
  expect(removed.status(), await removed.text()).toBe(204);

  // The role-memory GET must carry the member actor, not the leader.
  const memoryGet = page.waitForRequest(
    (req) =>
      req.method() === "GET" &&
      new URL(req.url()).pathname ===
        `/api/runs/${seeded.runId}/tasks/T1/role-memory/coder`,
  );
  const panel = await openMonitor(page, seeded.projectId, "T1");
  const getRequest = await memoryGet;
  expect(getRequest.headers()["x-bot-id"]).toBe(seeded.memberId);
  await expect(panel.getByTestId("task-role-memory-input")).toHaveAttribute("readonly", "");
  await expect(panel.getByTestId("task-role-memory-input")).not.toBeEditable();
  await expect(panel.getByTestId("task-role-memory-input")).toHaveValue(MEMORY_TEXT);
  await expect(panel.getByTestId("task-role-memory-save")).toBeDisabled();
  await expect(panel.getByTestId("task-role-memory-clear")).toBeDisabled();
  await expect(panel).toContainText("只读：只有项目 Leader 可以编辑");
  await expect(panel).toContainText("revision 1");

  // Read is membership-scoped and still works; writes stay leader-only.
  const asMember = await request.get(roleMemoryUrl, { headers: botHeaders(seeded.memberId) });
  expect(asMember.ok(), await asMember.text()).toBeTruthy();
  const view = (await asMember.json()) as {
    manual_text: string;
    manual_updated_by: string | null;
  };
  expect(view.manual_text).toBe(MEMORY_TEXT);
  expect(view.manual_updated_by).toBe(seeded.leaderId);
  const forbidden = await request.put(roleMemoryUrl, {
    headers: botHeaders(seeded.memberId),
    data: { expected_revision: 1, manual_text: "member write must fail" },
  });
  expect(forbidden.status()).toBe(403);
  errors.assertClean();
});