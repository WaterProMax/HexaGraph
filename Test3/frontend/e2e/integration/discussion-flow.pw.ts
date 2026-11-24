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
const SUPPLEMENT = "第一版以学生手动上报为准，暂不接入门禁。";

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

test("project chat: reject, supplement, approve, and inspect the Leader plan", async ({ page, request }) => {
  // 调度闭包会用真实子进程完整执行 4 个任务（编码+验收+评审+合并），需数分钟。
  test.setTimeout(900000);
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

  const leaderId = await createBot(request, `Zeng-${unique}`, "flagship");
  const memberId = await createBot(request, `Liang-${unique}`, "coder");
  const projectId = await createProject(request, "自习室空位查询小程序");
  await addMember(request, projectId, leaderId, true);
  await addMember(request, projectId, memberId, false);

  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("disc-view")).toHaveAttribute("data-stage", "idea");
  const idea = page.getByLabel("一句话想法");
  await expect(idea).toBeVisible();

  // 1. One-line idea → start discussion.
  await idea.fill(IDEA);
  const start = page.getByRole("button", { name: "开始讨论" });
  await expect(start).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath("discussion-00-composer.png"), fullPage: true });
  await start.click();

  // 2. Chat scrolls with system + proposal messages (blind round already unsealed).
  const chat = page.getByTestId("disc-chat");
  await expect(chat).toBeVisible();
  await expect(chat.getByTestId("disc-bubble-user").first()).toContainText(IDEA);
  await expect(chat).toContainText("第 1 轮讨论开始");
  await expect(chat.getByTestId("disc-bubble-proposal").first()).toContainText("提交了方案");
  await expect(chat.getByTestId("disc-bubble-proposal")).toHaveCount(2);

  // The two-column discussion layout must not overflow horizontally at any rail width.
  for (const width of [1600, 1280, 1024, 768]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.getByTestId("disc-layout").evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  }
  await page.screenshot({ path: test.info().outputPath("discussion-00-768.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

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
  await expect(dialog).toContainText(REJECT_COMMENT);
  await expect(dialog).toContainText("座位数据超过 30 分钟未更新");
  await page.screenshot({ path: test.info().outputPath("discussion-02-second-approval.png"), fullPage: true });

  // 6. Supplement in the same conversation from the pending approval state.
  const leaderHeaders = { "X-Bot-Id": leaderId };
  const premature = await request.post(`${API}/discussion-sessions/${secondSession.session_id}/plan`, {
    headers: leaderHeaders,
  });
  expect(premature.status()).toBe(409);
  await dialog.getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "暂停", exact: true }).click();
  await expect(page.getByRole("button", { name: "继续", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.getByRole("button", { name: "暂停", exact: true })).toBeVisible();
  await page.getByLabel("补充信息", { exact: true }).fill(SUPPLEMENT);
  expect(await page.getByTestId("disc-layout").evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("discussion-02-chat.png"), fullPage: true });
  await page.getByRole("button", { name: "发送补充" }).click();
  await expect(chat.getByTestId("disc-bubble-user").last()).toContainText(SUPPLEMENT);
  await expect(dialog).toBeVisible();

  // 7. Approval hands the structured plan to the existing run workstation.
  await dialog.getByRole("button", { name: "通过，进入任务拆解" }).click();
  await expect(dialog).toBeHidden();
  await expect(banner).toBeHidden();
  const summary = page.getByTestId("disc-spec-summary");
  await expect(summary).toBeVisible();
  const planLink = summary.getByRole("link", { name: "查看任务编排" });
  await expect(planLink).toBeVisible();
  const firstProposal = chat.getByTestId("disc-bubble-proposal").first();
  await firstProposal.getByRole("button", { name: "展开方案" }).click();
  await expect(firstProposal).toContainText("目标用户与痛点");
  await expect(firstProposal).not.toContainText("正文加载失败");
  // HEAD 63e3608 起方案正文改为居中弹窗：读完关闭，后续按钮才可点击。
  await page.getByTestId("disc-proposal-mask").click({ position: { x: 6, y: 6 } });
  await expect(page.getByTestId("disc-proposal-mask")).toHaveCount(0);
  const runId = (await planLink.getAttribute("href"))?.split("/").pop();
  expect(runId).toBeTruthy();
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

  // The earlier decisions and the new requirement snapshot are persisted.
  const sessions = await request.get(`${API}/projects/${projectId}/discussion-sessions`, {
    headers: { "X-Bot-Id": leaderId },
  });
  const items: Array<{
    session_id: string;
    status: string;
    previous_session_id: string | null;
    requirement_text: string;
    decision_package: { body_md: string } | null;
  }> = (await sessions.json()).items;
  expect(items).toHaveLength(3);
  expect(items[0].status).toBe("rejected");
  expect(items[0].session_id).toBe(secondSession.previous_session_id);
  expect(items[0].decision_package?.body_md).toContain("自习座位查看工具");
  expect(items[1].status).toBe("terminated");
  expect(items[1].session_id).toBe(secondSession.session_id);
  expect(items[1].decision_package?.body_md).toContain("自习座位查看工具");
  expect(secondSession.requirement_text).toBe(IDEA);
  expect(items[2].status).toBe("approved");
  expect(items[2].previous_session_id).toBe(secondSession.session_id);
  expect(items[2].requirement_text).toContain(SUPPLEMENT);
  expect(items[2].decision_package?.body_md).toContain("座位数据超过 30 分钟未更新");
  expect(items[0].decision_package?.body_md).not.toBe(items[2].decision_package?.body_md);
  const repeated = await request.post(`${API}/discussion-sessions/${items[2].session_id}/plan`, {
    headers: leaderHeaders,
  });
  expect(await repeated.json()).toEqual({ run_id: runId });
  const artifactResponse = await request.get(`${API}/runs/${runId}/artifacts`);
  const artifacts = await artifactResponse.json();
  expect(artifacts.plan.tasks[1].depends_on).toEqual(["T1"]);
  const beforeApproval = await request.get(`${API}/runs/${runId}/tasks`);
  expect(await beforeApproval.json()).toEqual([]);
  await spec.getByRole("button", { name: "关闭" }).click();
  await summary.getByRole("link", { name: "查看架构图" }).click();
  const architecture = page.getByTestId("architecture-preview");
  await expect(architecture).toBeVisible();
  await expect(architecture.getByTestId("architecture-canvas").locator(".react-flow__node")).toHaveCount(3);
  // 同向任务依赖并入模块契约边：每对模块一条直线。
  await expect(architecture.getByTestId("architecture-canvas").locator(".react-flow__edge")).toHaveCount(2);
  await expect(architecture.getByText("3 个模块 · 2 条依赖 · 2 条任务依赖")).toBeVisible();
  const canvas = architecture.getByTestId("architecture-canvas");
  await expect(architecture.getByTestId("architecture-legend")).toBeVisible();
  // 默认只有整张架构图与干净线条；点选模块后悬浮详情卡出现、相连边才标字。
  await expect(architecture.getByRole("complementary", { name: "模块详情" })).toHaveCount(0);
  await expect(canvas.getByText("T4←T3")).toHaveCount(0);
  const firstNode = canvas.locator(".react-flow__node").first();
  await firstNode.click({ position: { x: 24, y: 16 } });
  const moduleDetail = architecture.getByRole("complementary", { name: "模块详情" });
  await expect(moduleDetail.getByRole("heading", { name: "座位查询界面" })).toBeVisible();
  await expect(canvas.getByText("T4←T3")).toBeVisible();
  await expect(canvas.getByText("T3←T1")).toHaveCount(0);
  await expect(moduleDetail.getByText("C1", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("discussion-05-architecture.png"), animations: "disabled", fullPage: true });
  await moduleDetail.getByRole("button", { name: "关闭模块详情" }).click();
  await expect(architecture.getByRole("complementary", { name: "模块详情" })).toHaveCount(0);
  await firstNode.click({ position: { x: 24, y: 16 } });
  await expect(moduleDetail.getByRole("button", { name: /接通查询和上报接口/ })).toHaveCount(0);
  await moduleDetail.getByRole("button", { name: /^M2 查询与上报 API/ }).click();
  await moduleDetail.getByRole("button", { name: /接通查询和上报接口/ }).click();
  await expect(page.getByRole("heading", { name: "接通查询和上报接口" })).toBeVisible();
  await page.getByRole("button", { name: "流程图", exact: true }).click();
  const packageNodes = page.locator(".flow-node.package-node");
  await expect(packageNodes).toHaveCount(3);
  await packageNodes.first().click();
  await expect(packageNodes).toHaveCount(0);
  await expect(page.getByRole("button", { name: "← 全部工作包" })).toBeVisible();
  await page.getByRole("button", { name: "← 全部工作包" }).click();
  await expect(packageNodes).toHaveCount(3);
  await expect(page.getByRole("heading", { name: "PLAN基线确认" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("discussion-05-plan.png"), fullPage: true });
  const currentRun = await (await request.get(`${API}/runs/${runId}`)).json();
  const planGate = currentRun.gates.find((gate: any) => gate.status === "pending" && gate.kind === "PLAN基线确认");
  expect(planGate).toBeTruthy();
  const approved = await request.post(`${API}/gates/${planGate.id}/resolve`, {
    data: { decision: "approve", expected_revision: currentRun.revision },
  });
  expect(approved.ok(), await approved.text()).toBeTruthy();
  // schedule 会等待就绪闭包全部执行完（编码+验收+评审+合并）才返回，真实子进程需要几分钟。
  const scheduled = await request.post(`${API}/runs/${runId}/schedule`, { data: {}, timeout: 600000 });
  expect(scheduled.ok(), await scheduled.text()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${API}/runs/${runId}/tasks`)).json())
    .map((task: any) => task.state), { timeout: 120000 }).toEqual(["done", "done", "done", "done"]);
  const completedTasks = await (await request.get(`${API}/runs/${runId}/tasks`)).json();
  for (const task of completedTasks) {
    expect(task.evidence.some((item: any) => item.kind === "merge")).toBeTruthy();
  }
  // 验收报告会真实运行验收命令与回归测试，同样需要数分钟。
  const acceptance = await request.post(`${API}/runs/${runId}/accept`, { timeout: 600000 });
  expect(acceptance.ok(), await acceptance.text()).toBeTruthy();
  const { gate: acceptanceGate } = await acceptance.json();
  expect(acceptanceGate.payload.pass).toBe(true);
  const finalRun = await (await request.get(`${API}/runs/${runId}`)).json();
  const finished = await request.post(`${API}/gates/${acceptanceGate.id}/resolve`, {
    data: { decision: "approve", expected_revision: finalRun.revision },
  });
  expect(finished.ok(), await finished.text()).toBeTruthy();
  expect((await (await request.get(`${API}/runs/${runId}`)).json()).status).toBe("done");
  await page.getByRole("button", { name: /任务计划/ }).click();
  await expect(page.getByTestId("task-plan-preview")).toContainText("已完成 4");
  await page.screenshot({ path: test.info().outputPath("discussion-06-completed.png"), fullPage: true });
  expect(pageErrors).toEqual([]);
});
