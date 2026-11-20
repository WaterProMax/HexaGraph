import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * Idea → group chat → approval → reject → second session → approve.
 *
 * Real React pages and the real API client talk to the dedicated scripted backend
 * on 8766 (fixture `discussion-e2e`, temporary data dir). No API mock: the only
 * intercepted traffic is non-local, which is aborted so the case stays offline.
 */

const API = "http://127.0.0.1:8766/api";
const IDEA = "做一个能按楼层查看自习室剩余座位并允许到场学生上报的小程序。";
const REJECT_COMMENT = "请补充座位数据的过期规则，并写进验收标准。";

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
  return (await response.json()).bot_id;
}

async function createProject(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post(`${API}/projects`, { data: { name, profile: "python-pytest" } });
  expect(response.status()).toBe(200);
  return (await response.json()).id;
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

test("discussion flow: idea, chat, approval, reject, approve", async ({ page, request }) => {
  // `playwright.integration.config.ts` also matches `integration/*.pw.ts`; that
  // suite runs the study-room fixture on 8765, so this case must only run under
  // `playwright.discussion.config.ts` (fixture `discussion-e2e` on 8766).
  const health = await request.get(`${API}/health`).catch(() => null);
  const frontend = await request.get("http://127.0.0.1:5174").catch(() => null);
  test.skip(
    !health || !health.ok() || !frontend || !frontend.ok(),
    "run with playwright.discussion.config.ts (backend 8766 + frontend 5174)",
  );
  if (!health || !health.ok() || !frontend || !frontend.ok()) return;

  await page.route("**/*", (route) => {
    const origin = new URL(route.request().url()).origin;
    return origin === "http://127.0.0.1:5174" ? route.continue() : route.abort();
  });
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const unique = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;

  const leaderId = await createBot(request, `讨论组长-${unique}`, "flagship");
  const memberId = await createBot(request, `讨论成员-${unique}`, "coder");
  const projectId = await createProject(request, "多 Bot 讨论 E2E");
  await addMember(request, projectId, leaderId, true);
  await addMember(request, projectId, memberId, false);

  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("disc-view")).toHaveAttribute("data-stage", "idea");

  // 1. One-line idea → start discussion.
  const idea = page.getByLabel("一句话想法");
  await idea.fill(IDEA);
  const start = page.getByRole("button", { name: "开始讨论" });
  await expect(start).toBeEnabled();
  await start.click();

  // 2. Chat scrolls with system + proposal messages (blind round already unsealed).
  const chat = page.getByTestId("disc-chat");
  await expect(chat).toBeVisible();
  await expect(chat).toContainText("第 1 轮讨论开始");
  await expect(chat.getByTestId("disc-bubble-proposal").first()).toContainText("提交了方案");
  await expect(chat.getByTestId("disc-bubble-proposal")).toHaveCount(2);

  // 3. Approval banner + auto-opened dialog with the synthesized spec.
  const banner = page.getByTestId("disc-approval-banner");
  await expect(banner).toContainText("需求规格待你审批");
  const dialog = page.getByTestId("disc-approval-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "需求规格待你审批" })).toBeVisible();
  await expect(dialog).toContainText("自习座位查看工具");
  await expect(dialog.getByText("硬门槛 3/3")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("discussion-01-approval.png"), fullPage: true });

  // Close is not a decision: the banner stays, and a reload restores everything from the server.
  await dialog.getByRole("button", { name: "关闭" }).click();
  await expect(dialog).toBeHidden();
  await expect(banner).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("disc-approval-banner")).toBeVisible();
  await expect(page.getByTestId("disc-approval-dialog")).toBeVisible();

  // 4. Reject: the comment is required, then a second session starts automatically.
  await dialog.getByRole("button", { name: "打回重新讨论" }).click();
  const confirmReject = dialog.getByRole("button", { name: "确认打回并重新讨论" });
  await expect(confirmReject).toBeDisabled();
  await dialog.getByLabel("打回意见").fill(REJECT_COMMENT);
  await expect(confirmReject).toBeEnabled();
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/projects/${projectId}/discussion-sessions`,
  );
  await confirmReject.click();
  const secondSession = await (await created).json();
  expect(secondSession.previous_session_id).toBeTruthy();

  // 5. Timeline keeps both sessions with the user's comment as a divider.
  await expect(chat.getByTestId("disc-divider").last()).toContainText(
    `第 2 次讨论 · 你的意见：${REJECT_COMMENT}`,
  );
  await expect(banner).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("自习座位查看工具");
  await page.screenshot({ path: test.info().outputPath("discussion-02-second-approval.png"), fullPage: true });

  // 6. Approve → approved stage with "等待任务拆解" and the spec entry point.
  await dialog.getByRole("button", { name: "通过，进入任务拆解" }).click();
  await expect(dialog).toBeHidden();
  await expect(banner).toBeHidden();
  const summary = page.getByTestId("disc-spec-summary");
  await expect(summary).toBeVisible();
  await expect(summary).toContainText("等待任务拆解");
  await expect(page.getByTestId("disc-stage-bar")).toContainText("等待任务拆解");
  await expect(page.getByRole("button", { name: "查看需求规格" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("discussion-03-approved.png"), fullPage: true });

  await page.getByRole("button", { name: "查看需求规格" }).click();
  const spec = page.getByTestId("disc-spec-dialog");
  await expect(spec).toBeVisible();
  await expect(spec.getByTestId("disc-spec-current")).toContainText("自习座位查看工具");
  const history = spec.getByTestId("disc-spec-history");
  await expect(history).toContainText("已批准");
  await expect(history).toContainText("已打回");
  await page.screenshot({ path: test.info().outputPath("discussion-04-spec-viewer.png"), fullPage: true });

  // 7. Server truth: first session rejected, second approved, both carry a decision package.
  const sessions = await request.get(`${API}/projects/${projectId}/discussion-sessions`, {
    headers: { "X-Bot-Id": leaderId },
  });
  const items: Array<{
    session_id: string;
    status: string;
    previous_session_id: string | null;
    decision_package: { body_md: string } | null;
  }> = (await sessions.json()).items;
  expect(items).toHaveLength(2);
  expect(items[0].status).toBe("rejected");
  expect(items[0].session_id).toBe(secondSession.previous_session_id);
  expect(items[0].decision_package?.body_md).toContain("自习座位查看工具");
  expect(items[1].status).toBe("approved");
  expect(items[1].session_id).toBe(secondSession.session_id);
  expect(items[1].decision_package?.body_md).toContain("自习座位查看工具");
  expect(secondSession.requirement_text).toBe(IDEA);
  expect(pageErrors).toEqual([]);
});