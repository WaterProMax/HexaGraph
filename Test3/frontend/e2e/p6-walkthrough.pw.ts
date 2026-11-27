import { expect, test } from "@playwright/test";

/**
 * P6 UI-A1 walkthrough against an HTTP mock. Real React pages and the real API
 * client run; no backend, no paid model call.
 *
 * Screenshot paths are relative to the Playwright working directory
 * (Test3/frontend); Playwright creates the target directory.
 */
const SHOTS = "../docs/plans/screenshots";

const project = { id: "proj-1", name: "自习室座位", profile: "python-pytest" };
const run = { id: "run-1", project_id: "proj-1", status: "running", stage: "3", revision: 2, paused: false, idea: "自习室座位", gates: [], event_count: 0 };

const tasks = [
  { code: "T-01", state: "done", card: { title: "实现登录" } },
  { code: "T-02", state: "running", card: { title: "接通验收" } },
];

const grantStale = {
  grant_id: "g-1",
  run_id: "run-1",
  execution_profile: "granted_v1",
  task_codes: ["T-01", "T-02"],
  approved_baseline_hashes: { PLAN: "a", DecisionPackage: "b" },
  repo_remote: "origin",
  repo_owner: "WaterProMax",
  repo_name: "HexaGraph",
  base_branch: "teamwork-001",
  feature_branch: "feat-p6",
  allowed_tool_refs: [],
  status: "stale",
  github_pr_url: null,
  created_at: "2026-11-20T00:00:00+00:00",
};

const defect = {
  defect_id: "d-1",
  run_id: "run-1",
  task_code: "T-02",
  module_id: "M1",
  related_requirement_id: null,
  evidence_uris: ["file://logs/t02.log"],
  status: "open",
  detail: "缺边界用例",
};

const bot = {
  bot_id: "bot-1",
  display_name: "Leader A",
  role_template: "coder",
  provider_ref: "dashscope",
  model: "qwen-max",
  slot: "flagship",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [{ skill_id: "review", pinned_version: "1.0.0" }],
  token_budget: 40000,
  status: "active",
};

type MockState = { bots: any[]; forbidBots: boolean; failBots: boolean };

async function mockApi(page: import("@playwright/test").Page, state: MockState) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const apiPath = url.pathname.slice(4);
    const method = req.method();
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data });

    if (apiPath === "/health") return json({ status: "ok", schedule_mode: "manual" });
    if (apiPath === "/runs") return json([run]);
    if (apiPath === "/runs/run-1") return json(run);
    if (apiPath === "/runs/run-1/tasks") return json(tasks);
    if (apiPath === "/runs/run-1/execution-grants") return json({ items: [grantStale] });
    if (apiPath === "/runs/run-1/defects") return json({ items: [defect] });
    if (apiPath === "/runs/run-1/events") return route.fulfill({ contentType: "text/event-stream", body: ": ping\n\n" });
    if (apiPath === "/runs/run-1/events/history") return json([]);
    if (apiPath === "/projects") return json([project]);
    if (apiPath === "/config/models") return json({ provider: "dashscope", slots: { flagship: { model: "qwen-max" }, coder: { model: "qwen-plus" } } });
    if (apiPath === "/config/models/test" && method === "POST") return json({ ok: true, note: "probe-ok" });
    if (apiPath === "/skills/import" && method === "POST")
      return json({ skill_id: "acme-review", version: "abc1234", description_md: "", allowed_tool_refs: [] }, 201);
    if (apiPath === "/skills") return json({ items: [{ skill_id: "review", version: "1.0.0", description_md: "", allowed_tool_refs: [] }] });
    if (apiPath === "/bots" && method === "POST") {
      const body = JSON.parse(req.postData() || "{}");
      const created = { ...bot, ...body, bot_id: `bot-${state.bots.length + 1}`, status: "active" };
      state.bots.push(created);
      return json(created, 201);
    }
    if (apiPath === "/bots") {
      if (state.forbidBots) return json({ error_category: "forbidden", detail: "no" }, 403);
      if (state.failBots) return json({ error_category: "validation_error", detail: "network down" }, 500);
      return json({ items: state.bots });
    }
    if (apiPath === "/projects/proj-1/memberships")
      return json({ items: [{ project_id: "proj-1", bot_id: "bot-1", role_in_project: "dev", is_leader: true }] });
    if (apiPath.startsWith("/projects/proj-1/discussion-sessions")) return json({ items: [] });
    return json({});
  });
}

test.describe.configure({ mode: "serial" });

test("P6 UI-A1 walkthrough", async ({ page }) => {
  const state: MockState = { bots: [], forbidBots: false, failBots: false };
  await mockApi(page, state);

  // 1. Sidebar has a Bot section and a project section.
  await page.goto("/workstation");
  const nav = page.getByRole("navigation", { name: "浏览" });
  await expect(nav).toHaveCount(0);
  await expect(page.getByTestId("sidebar-new-bot")).toHaveAttribute("href", "/bots/new");
  const projects = page.getByTestId("sidebar-project-list");
  await expect(projects.getByTestId("sidebar-new-project")).toHaveAttribute("href", "/projects/new");
  await expect(nav.getByRole("link", { name: "模型槽位" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/p6-t01-sidebar.png`, fullPage: true });

  await projects.getByTestId("sidebar-new-project").click();
  await expect(page.getByRole("dialog", { name: "创建项目" })).toBeVisible();

  // 2. No top-level Model/Skill/Market/Cron navigation.
  await expect(nav.getByRole("link", { name: "Model" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Skill" })).toHaveCount(0);
  await expect(page.getByText("Market")).toHaveCount(0);
  await expect(page.getByText("Cron")).toHaveCount(0);
  const hrefs = await nav.locator("a").evaluateAll((nodes) => nodes.map((node) => (node as HTMLAnchorElement).getAttribute("href") || ""));
  expect(hrefs).not.toContain("/models");
  expect(hrefs).not.toContain("/skills");

  // 3. /bots empty, then create a bot with a skill pin.
  await page.goto("/bots");
  await expect(page.getByTestId("bots-empty")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p6-t02-empty.png`, fullPage: true });

  await page.getByTestId("sidebar-new-bot").click();
  await expect(page.getByTestId("bot-form")).toBeVisible();
  const form = page.getByTestId("bot-form");
  await form.getByLabel("显示名").fill("Leader A");
  await form.getByRole("button", { name: "下一步" }).click();
  await form.getByLabel("模型", { exact: true }).selectOption("qwen-max");
  await form.getByRole("button", { name: "下一步" }).click();
  await form.getByLabel("GitHub 地址").fill("https://github.com/acme/skills/tree/main/review");
  await form.getByRole("button", { name: /添\s*加/ }).click();
  await expect(form.getByText("acme-review@abc1234")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p6-t02-create.png`, fullPage: true });
  await page.getByRole("button", { name: "创建 Bot" }).click();
  await expect(page.getByRole("link", { name: /Leader A/ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p6-t02-ready.png`, fullPage: true });

  // 4. Project workstation tree with progress (the tree now lives on the 活动 tab;
  // 详情 / 任务图 are full-width views with a header task picker instead).
  await page.goto("/projects/proj-1");
  // The project lands on 项目讨论 now; switch to the task workspace first.
  await page.getByRole("button", { name: "开发任务" }).click();
  await page.getByTestId("tab-activity").click();
  const tree = page.getByTestId("task-tree");
  await expect(tree.getByText("T-01")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "T-01 进度" })).toHaveAttribute("aria-valuenow", "100");
  await expect(page.getByRole("progressbar", { name: "T-02 进度" })).toHaveAttribute("aria-valuenow", "40");
  await expect(page.getByTestId("grant-banner")).toContainText("基线");

  // 5. All four tabs switch.
  for (const tab of ["details", "monitor", "activity", "graph"]) {
    await page.getByTestId(`tab-${tab}`).click();
    await expect(page.getByTestId(`panel-${tab}`)).toBeVisible();
  }
  await page.getByTestId("tab-details").click();
  await page.screenshot({ path: `${SHOTS}/p6-t03-workstation.png`, fullPage: true });

  // 6. Splitter still drags (only the 活动 tab keeps the side tree + splitter).
  await page.getByTestId("tab-activity").click();
  const handle = page.getByTestId("ws-splitter");
  const before = Number(await handle.getAttribute("aria-valuenow"));
  const box = await handle.boundingBox();
  if (!box) throw new Error("splitter has no box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  const after = Number(await handle.getAttribute("aria-valuenow"));
  expect(after).toBeGreaterThan(before);

  // 7. baseline_stale banner.
  await expect(page.getByTestId("grant-banner")).toContainText("baseline_stale");
  await expect(page.getByTestId("grant-banner")).toContainText("重新审批");
  await page.screenshot({ path: `${SHOTS}/p6-t04-banner.png`, fullPage: true });

  // 8. Defect click locates its task.
  await page.getByTestId("tab-monitor").click();
  await page.getByTestId("defect-T-02").click();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-02");
  await page.screenshot({ path: `${SHOTS}/p6-t04-defect-locate.png`, fullPage: true });
});

test("P6 error and permission states are explicit", async ({ page }) => {
  const state: MockState = { bots: [], forbidBots: true, failBots: false };
  await mockApi(page, state);
  await page.goto("/bots");
  await expect(page.getByTestId("bots-forbidden")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p6-t05-forbidden.png`, fullPage: true });

  state.forbidBots = false;
  state.failBots = true;
  await page.goto("/bots?retry=1");
  await expect(page.getByTestId("bots-error")).toBeVisible();
});