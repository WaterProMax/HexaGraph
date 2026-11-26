import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Human-in-the-loop discussion controls against a REAL frontend + REAL offline backend.
 *
 * Fixture: `e2e/discussion-server.py` -> TEST3_LLM_PROVIDER=scripted,
 * TEST3_SCRIPTED_FIXTURE=discussion-e2e, ExecutionPolicy(simulated=True), temporary
 * data dir, loopback 127.0.0.1:8766; Vite on 127.0.0.1:5174. No real model call, no
 * real sandbox/repo write. The test-only async gate
 * (POST /api/e2e/discussion-gate) holds a scripted model call open so the UI can
 * pause / end the round deterministically BEFORE a decision package exists.
 *
 * Determinism rule: never sleep; gate the model call, poll the server state, then
 * release the gate.
 */

const API = "http://127.0.0.1:8766/api";
const FRONTEND = "http://127.0.0.1:5174";
const GATE = `${API}/e2e/discussion-gate`;
const IDEA = "做一个能按楼层查看自习室剩余座位并允许到场学生上报的小程序。";
const INTERVENTION = "请补充座位数据的过期规则，并写进验收标准。";
// Marker the scripted fixture inserts only when the prompt carries the revision rule.
const REVISED_MARKER = "座位数据超过 30 分钟未更新";
const END_REASON = "分差过大，人工结束本轮";

type SessionRecord = {
  session_id: string;
  status: string;
  current_round: number;
  paused: boolean;
  pause_requested: boolean;
  control_revision: number;
  decision_package: { body_md: string } | null;
  round_end_reason: { kind?: string; text?: string } | null;
  interventions?: Array<{ text?: string }>;
  budget: { max_rounds: number };
};

type GateSnapshot = {
  installed: boolean;
  released: boolean;
  holds: string[];
  blocked_operations: string[];
  timeout_seconds: number;
};

const botHeaders = (botId: string) => ({ "X-Bot-Id": botId });

/** Fail fast when the discussion config (8766/5174) is not the one running us. */
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

async function gateSnapshot(request: APIRequestContext): Promise<GateSnapshot | null> {
  const response = await request.get(GATE).catch(() => null);
  if (!response || !response.ok()) return null;
  return (await response.json()) as GateSnapshot;
}

/** The gate route only exists in e2e/discussion-server.py, not in external backends. */
async function requireGate(request: APIRequestContext): Promise<GateSnapshot | null> {
  const snapshot = await gateSnapshot(request);
  test.skip(!snapshot, "test-only gate missing (external backend? run e2e/discussion-server.py)");
  return snapshot;
}

async function resetGate(request: APIRequestContext): Promise<void> {
  const response = await request.post(GATE, { data: { released: true } });
  expect(response.status(), await response.text()).toBe(200);
}

async function configureGate(request: APIRequestContext, holds: string[]): Promise<void> {
  const response = await request.post(GATE, {
    data: { holds, released: false, timeout_seconds: 60 },
  });
  expect(response.status(), await response.text()).toBe(200);
}

async function releaseGate(request: APIRequestContext): Promise<void> {
  const response = await request.post(GATE, { data: { released: true } });
  expect(response.status(), await response.text()).toBe(200);
  const snapshot = (await response.json()) as GateSnapshot;
  expect(snapshot.released).toBe(true);
}

async function createBot(
  request: APIRequestContext,
  displayName: string,
  slot: "flagship" | "coder",
): Promise<string> {
  const response = await request.post(`${API}/bots`, {
    data: {
      display_name: displayName,
      role_template: slot === "flagship" ? "leader" : "pm",
      provider_ref: "dashscope",
      model: slot === "flagship" ? "qwen-max" : "qwen-plus",
      slot,
      secret_ref: "DASHSCOPE_API_KEY",
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()).bot_id as string;
}

async function createProject(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post(`${API}/projects`, {
    data: { name, profile: "python-pytest" },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).id as string;
}

async function addMember(
  request: APIRequestContext,
  projectId: string,
  botId: string,
  isLeader: boolean,
): Promise<void> {
  const response = await request.post(`${API}/projects/${projectId}/memberships`, {
    data: { bot_id: botId, role_in_project: isLeader ? "lead" : "dev", is_leader: isLeader },
  });
  expect(response.status(), await response.text()).toBe(201);
}

async function createDiscussionSetup(request: APIRequestContext) {
  const unique = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
  const leaderId = await createBot(request, `Leader-${unique}`, "flagship");
  const memberId = await createBot(request, `Member-${unique}`, "coder");
  const projectId = await createProject(request, `人工介入-${unique}`);
  await addMember(request, projectId, leaderId, true);
  await addMember(request, projectId, memberId, false);
  return { leaderId, memberId, projectId };
}

async function readSession(
  request: APIRequestContext,
  sessionId: string,
  actorId: string,
): Promise<SessionRecord> {
  const response = await request.get(`${API}/discussion-sessions/${sessionId}`, {
    headers: botHeaders(actorId),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as SessionRecord;
}

function routeLocalOnly(page: Page): Promise<unknown> {
  return page.route("**/*", (route) => {
    const origin = new URL(route.request().url()).origin;
    return origin === FRONTEND ? route.continue() : route.abort();
  });
}

type ErrorTracker = {
  pageErrors: string[];
  consoleErrors: string[];
  assertClean: () => void;
};

// Offline E2E: aborted non-local requests and dev-only warnings are expected noise.
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

/** Starts the discussion through the real composer and returns the session id. */
async function startDiscussionFromUi(page: Page, projectId: string): Promise<string> {
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("disc-view")).toHaveAttribute("data-stage", "idea");
  await page.getByLabel("一句话想法").fill(IDEA);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/projects/${projectId}/discussion-sessions`,
  );
  await page.getByRole("button", { name: "开始讨论" }).click();
  const createdResponse = await created;
  expect(createdResponse.status(), await createdResponse.text()).toBe(201);
  return (await createdResponse.json()).session_id as string;
}

/** Wait until the scripted `review` call is held by the test-only gate. */
async function waitForHeldReview(page: Page, request: APIRequestContext): Promise<void> {
  await expect(page.getByTestId("disc-chat").getByTestId("disc-bubble-proposal")).toHaveCount(
    2,
    { timeout: 30000 },
  );
  await expect
    .poll(async () => (await gateSnapshot(request))?.blocked_operations ?? [], {
      timeout: 30000,
    })
    .toContain("review");
}

test("scripted: pause a held review, intervene, resume to a human approval", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  test.info().annotations.push({
    type: "fixture",
    description: "scripted provider + simulated executor; no real model, sandbox or repo write",
  });
  if (!(await requireDiscussionSuite(request))) return;
  if (!(await requireGate(request))) return;
  await resetGate(request);
  const errors = trackErrors(page);
  await routeLocalOnly(page);

  const { leaderId, projectId } = await createDiscussionSetup(request);
  await configureGate(request, ["review"]);
  const sessionId = await startDiscussionFromUi(page, projectId);
  await waitForHeldReview(page, request);

  // 1. Pause while the review model call is still held: no decision package exists.
  const pauseButton = page.getByTestId("disc-pause-resume");
  await expect(pauseButton).toHaveText("暂停");
  await pauseButton.click();
  await expect(pauseButton).toHaveText("正在请求暂停…");
  await expect
    .poll(async () => (await readSession(request, sessionId, leaderId)).pause_requested, {
      timeout: 15000,
    })
    .toBe(true);

  // 2. Release the in-flight call: the driver must publish a safe cooperative pause.
  await releaseGate(request);
  await expect(page.getByTestId("disc-intervention")).toBeVisible({ timeout: 20000 });
  await expect(pauseButton).toHaveText("继续");
  const paused = await readSession(request, sessionId, leaderId);
  expect(paused.paused).toBe(true);
  expect(paused.pause_requested).toBe(false);
  expect(paused.decision_package).toBeNull();
  expect(paused.status).toBe("cross_review");

  // 3. Same-session intervention; the revision rule must steer the resumed output.
  await page.getByLabel("讨论插话").fill(INTERVENTION);
  await page.getByTestId("disc-send-intervention").click();
  await expect(
    page
      .getByTestId("disc-chat")
      .getByTestId("disc-bubble-user")
      .filter({ hasText: INTERVENTION })
      .first(),
  ).toBeVisible({ timeout: 20000 });
  await expect
    .poll(async () => ((await readSession(request, sessionId, leaderId)).interventions ?? []).length, {
      timeout: 15000,
    })
    .toBe(1);
  const intervened = await readSession(request, sessionId, leaderId);
  expect(intervened.interventions?.[0]?.text).toBe(INTERVENTION);
  expect(intervened.control_revision).toBeGreaterThan(paused.control_revision);

  // 4. Resume: the discussion completes and stops at the human approval gate.
  await pauseButton.click();
  await expect(page.getByTestId("disc-approval-banner")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("disc-approval-dialog")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("disc-approval-dialog")).toContainText(REVISED_MARKER);

  const finalSessions: SessionRecord[] = [];
  await expect
    .poll(
      async () => {
        const record = await readSession(request, sessionId, leaderId);
        finalSessions.push(record);
        return Boolean(record.decision_package);
      },
      { timeout: 30000 },
    )
    .toBe(true);
  const approval = finalSessions[finalSessions.length - 1];
  expect(approval).toBeDefined();
  expect(approval.status).toBe("converged_pending_human");
  expect(approval.paused).toBe(false);
  expect(approval.decision_package?.body_md).toContain(REVISED_MARKER);
  expect(approval.decision_package?.body_md).toContain("本次修订");
  errors.assertClean();
});

test("scripted: manual end-round settles, then an explicit new round runs", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  test.info().annotations.push({
    type: "fixture",
    description: "scripted provider + simulated executor; no real model, sandbox or repo write",
  });
  if (!(await requireDiscussionSuite(request))) return;
  if (!(await requireGate(request))) return;
  await resetGate(request);
  const errors = trackErrors(page);
  await routeLocalOnly(page);

  const { leaderId, projectId } = await createDiscussionSetup(request);
  await configureGate(request, ["review"]);
  const sessionId = await startDiscussionFromUi(page, projectId);
  await waitForHeldReview(page, request);

  // 1. End the round while the review call is held: no decision package can exist.
  await page.getByTestId("disc-end-round").click();
  await expect(page.getByTestId("disc-end-round-dialog")).toBeVisible();
  await page.getByLabel("结束本轮原因").fill(END_REASON);
  await page.getByTestId("disc-confirm-end-round").click();

  // 2. The manual-end intent must be persisted while the model call is still held.
  await expect
    .poll(
      async () => {
        const record = await readSession(request, sessionId, leaderId);
        return [record.round_end_reason?.kind, record.pause_requested];
      },
      { timeout: 15000 },
    )
    .toEqual(["manual", true]);

  // 3. Reload to observe the transient "manual end pending" UI deterministically:
  //    the page does not refresh while its own control request is in flight.
  await page.reload();
  await expect(page.getByTestId("disc-manual-ending")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("disc-manual-end")).toContainText("正在等待安全检查点完成");
  await expect(page.getByTestId("disc-manual-ending")).toContainText("正在结束本轮");
  await expect(page.getByTestId("disc-start-round")).toHaveCount(0);
  await expect(page.getByTestId("disc-pause-resume")).toHaveCount(0);
  await expect(page.getByTestId("disc-intervention")).toHaveCount(0);

  // 4. Release the held call; the driver finalizes the manual end (never a package).
  await releaseGate(request);
  await expect(page.getByTestId("disc-manual-ending")).toHaveCount(0, { timeout: 20000 });
  await expect(page.getByTestId("disc-manual-end")).toContainText("已安全停止", {
    timeout: 20000,
  });
  await expect(page.getByTestId("disc-start-round")).toBeVisible({ timeout: 20000 });

  const settledRecords: SessionRecord[] = [];
  await expect
    .poll(
      async () => {
        const record = await readSession(request, sessionId, leaderId);
        settledRecords.push(record);
        return [
          record.status,
          record.paused,
          record.pause_requested,
          Boolean(record.decision_package),
          record.round_end_reason?.kind,
          record.current_round,
          record.budget.max_rounds,
        ];
      },
      { timeout: 20000 },
    )
    .toEqual(["converged_pending_human", true, false, false, "manual", 1, 3]);
  const settledRecord = settledRecords[settledRecords.length - 1];
  expect(settledRecord.round_end_reason?.text).toBe(END_REASON);

  // 5. Only the explicit rounds/start (then run) may reopen the round.
  await page.getByTestId("disc-start-round").click();
  await expect(page.getByTestId("disc-start-round-dialog")).toBeVisible();
  await page.getByTestId("disc-confirm-start-round").click();
  await expect
    .poll(
      async () => {
        const record = await readSession(request, sessionId, leaderId);
        return [record.current_round, record.round_end_reason, record.paused];
      },
      { timeout: 20000 },
    )
    .toEqual([2, null, false]);

  // 6. Round 2 runs to the human approval gate; nothing is auto-approved/planned.
  const waitingRecords: SessionRecord[] = [];
  await expect
    .poll(
      async () => {
        const record = await readSession(request, sessionId, leaderId);
        waitingRecords.push(record);
        return Boolean(record.decision_package);
      },
      { timeout: 30000 },
    )
    .toBe(true);
  const waitingRecord = waitingRecords[waitingRecords.length - 1];
  expect(waitingRecord.status).toBe("converged_pending_human");
  expect(waitingRecord.status).not.toBe("approved");
  expect(waitingRecord.current_round).toBe(2);
  await expect(page.getByTestId("disc-approval-banner")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("disc-spec-summary")).toHaveCount(0);
  errors.assertClean();
});