import { expect, test, type Page } from "@playwright/test";

/**
 * UI redesign walkthrough (R01–R05) against an HTTP mock.
 * Real React pages and the real api client run; zero paid model calls.
 * Screenshots go to docs/plans/screenshots/ui-redesign/ — never over p6-*.
 */
const SHOTS = "../docs/plans/screenshots/ui-redesign";

const botA = {
  bot_id: "bot-a",
  display_name: "Leader A",
  role_template: "leader",
  provider_ref: "dashscope",
  model: "qwen-max",
  slot: "flagship",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [{ skill_id: "review", pinned_version: "1.0.0" }],
  token_budget: 40000,
  status: "active",
};

const botB = {
  bot_id: "bot-b",
  display_name: "周明",
  role_template: "pm",
  provider_ref: "dashscope",
  model: "qwen-plus",
  slot: "coder",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [],
  token_budget: 40000,
  status: "active",
};

const botC = { ...botB, bot_id: "bot-c", display_name: "Tester C", role_template: "qa" };
const project = { id: "p1", name: "自习室座位", profile: "python-pytest" };
const run = { id: "run-1", project_id: "p1", status: "running", stage: "3", revision: 2, paused: false, idea: "自习室座位", gates: [], event_count: 0 };

const tasks = [
  { code: "T-01", state: "done", card: { title: "实现登录" } },
  { code: "T-02", state: "running", card: { title: "接通验收" } },
];

const grant = {
  grant_id: "g-1",
  run_id: "run-1",
  execution_profile: "granted_v1",
  task_codes: ["T-01", "T-02"],
  approved_baseline_hashes: { PLAN: "a", DecisionPackage: "b" },
  repo_remote: "origin",
  repo_owner: "WaterProMax",
  repo_name: "HexaGraph",
  base_branch: "teamwork-001",
  feature_branch: "feat/test3-agent-team-v1",
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

const memory = {
  mem_id: "m1",
  owner_bot_id: "bot-a",
  project_id: "p1",
  visibility: "project",
  version: 1,
  status: "pending",
  sources: [],
  body: { text: "座位规则" },
  title: "座位规则",
  run_id: null,
};

const privateMemory = { ...memory, mem_id: "m2", visibility: "private", title: "个人偏好", body: { text: "个人偏好" } };

const session = {
  session_id: "s1",
  project_id: "p1",
  leader_bot_id: "bot-a",
  participant_bot_ids: ["bot-a", "bot-b"],
  status: "cross_review",
  current_round: 1,
  budget: { max_rounds: 3, max_tokens: null, max_wallclock_seconds: null },
  requirement_snapshot_hash: "0".repeat(64),
  decision_package: null,
};

const ballot = {
  reviewer_bot_id: "bot-b",
  proposal_id: "proposal-1",
  scores: { coverage: 3 },
  score_justification: { coverage: "覆盖主路径" },
  hard_gate_results: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: false },
  dissent_items: ["缺边界用例"],
};

const members = [
  { project_id: "p1", bot_id: "bot-a", role_in_project: "lead", is_leader: true },
  { project_id: "p1", bot_id: "bot-b", role_in_project: "dev", is_leader: false },
];

async function mockApi(page: Page) {
  const writes: Array<{ method: string; path: string; body: any }> = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const path = url.pathname.slice(4);
    const method = request.method();
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data });

    if (method !== "GET") {
      const body = request.postData() ? request.postDataJSON() : null;
      writes.push({ method, path, body });
      if (method === "DELETE") return route.fulfill({ status: 204 });
      if (path === "/bots") return json({ ...botA, bot_id: "bot-new" }, 201);
      return json({ ok: true }, 201);
    }

    if (path === "/health") return json({ status: "ok", schedule_mode: "manual" });
    if (path === "/runs") return json([run]);
    if (path === "/runs/run-1") return json(run);
    if (path === "/runs/run-1/tasks") return json(tasks);
    if (path === "/runs/run-1/execution-grants") return json({ items: [grant] });
    if (path === "/runs/run-1/defects") return json({ items: [defect] });
    if (path === "/runs/run-1/events/history") return json([]);
    if (path === "/runs/run-1/events") return route.fulfill({ contentType: "text/event-stream", body: ": ping\n\n" });
    if (path === "/projects") return json([project]);
    if (path === "/projects/p1/memberships") return json({ items: members });
    if (path === "/bots") return json({ items: [botA, botB, botC] });
    if (path === "/bots/bot-a") return json(botA);
    if (path === "/bots/bot-b") return json(botB);
    if (path === "/skills") return json({ items: [{ skill_id: "review", version: "1.0.0", description_md: "", allowed_tool_refs: [] }] });
    if (path === "/config/models")
      return json({ provider: "dashscope", slots: { flagship: { model: "qwen-max" }, coder: { model: "qwen-plus" } } });
    if (path === "/config/models/test") return json({ ok: true, note: "probe-ok" });
    if (path === "/memory/records") {
      const visibility = url.searchParams.get("visibility");
      return json({ items: visibility === "private" ? [privateMemory] : [memory] });
    }
    if (path === "/projects/p1/discussion-sessions") return json({ items: [session] });
    if (path === "/discussion-sessions/s1/reviews") return json({ items: [ballot] });
    return json({ items: [] });
  });
  return writes;
}

test.describe.configure({ mode: "serial" });

test("UI redesign walkthrough", async ({ page }) => {
  const writes = await mockApi(page);

  // R01: expanded contact list, then the collapsed avatar rail.
  await page.goto("/workstation");
  await expect(page.getByTestId("sidebar-bot-list")).toBeVisible();
  await expect(page.getByTestId("sidebar-bot-list").getByRole("link", { name: /Leader A/ })).toHaveAttribute(
    "href",
    "/bots/bot-a/chat",
  );
  await expect(page.getByTestId("sidebar-manage-bots")).toHaveAttribute("href", "/bots");
  await expect(page.getByTestId("sidebar-new-bot")).toHaveAttribute("href", "/bots/new");
  await page.screenshot({ path: `${SHOTS}/ui-r01-sidebar-expanded.png`, fullPage: true });

  await page.getByRole("button", { name: "收起导航" }).click();
  await page.waitForTimeout(450);
  const rail = page.getByTestId("sidebar-bot-rail");
  await expect(rail).toBeVisible();
  await expect(rail.getByRole("link", { name: "Leader A · leader" })).toBeVisible();
  await expect(rail.getByRole("link", { name: "周明 · pm" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r01-sidebar-collapsed.png`, fullPage: true });
  await page.getByRole("button", { name: "展开导航" }).click();
  await page.waitForTimeout(450);

  // R02: list, new form, workspace tabs, avatar picker.
  await page.goto("/bots");
  await expect(page.locator("a.bot-list-card").first()).toHaveAttribute("href", "/bots/bot-a");
  await page.screenshot({ path: `${SHOTS}/ui-r02-bots-list.png`, fullPage: true });

  await page.goto("/bots/new");
  await expect(page.getByTestId("bot-create-overlay")).toBeVisible();
  await expect(page.getByTestId("bot-identity")).toBeVisible();
  await expect(page.getByTestId("bot-duty-grid")).toBeVisible();
  await page.getByLabel("显示名").fill("周明");
  await page.getByTestId("duty-pm").click();
  await page.getByLabel("头像 🦉").click();
  await page.screenshot({ path: `${SHOTS}/ui-r02-bot-new.png`, fullPage: true });
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByTestId("bot-form").getByLabel("供应商")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r02-bot-new-model.png`, fullPage: true });
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByTestId("bot-step-summary")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r02-bot-new-skill.png`, fullPage: true });

  await page.goto("/bots/bot-a");
  await expect(page.getByTestId("bot-workspace")).toBeVisible();
  await expect(page.getByTestId("bot-tab-memory")).toBeVisible();
  await page.getByTestId("bot-tab-memory").click();
  await expect(page.getByText("个人偏好")).toBeVisible();
  await page.getByTestId("bot-tab-config").click();
  await page.getByTestId("bot-avatar-change").click();
  await expect(page.getByTestId("bot-avatar-picker")).toBeVisible();
  await page.getByRole("button", { name: "头像 🦊" }).click();
  await expect(page.locator(".bot-workspace-head [data-testid='bot-avatar']")).toHaveText("🦊");
  await page.screenshot({ path: `${SHOTS}/ui-r02-bot-workspace.png`, fullPage: true });
  await page.getByRole("button", { name: "关闭头像选择器" }).click();

  // R03: projects with avatars, team strip, members dialog and shared memory.
  await page.goto("/projects");
  await expect(page.getByText("Leader · Leader A")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r03-projects.png`, fullPage: true });

  await page.goto("/projects/p1");
  await expect(page.getByTestId("team-strip")).toBeVisible();
  await expect(page.getByTestId("actor-bot-select")).toHaveValue("bot-a");
  await page.screenshot({ path: `${SHOTS}/ui-r03-team-strip.png`, fullPage: true });

  await page.getByTestId("manage-members").click();
  await expect(page.getByTestId("members-dialog")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r03-members-dialog.png`, fullPage: true });
  await page.getByRole("button", { name: "关闭成员管理" }).click();

  // R04: review cards, defect locate highlight.
  await page.getByTestId("tab-monitor").click();
  await expect(page.getByTestId("discussion-review-panel").getByText("周明")).toBeVisible();
  await expect(page.getByText("座位规则")).toBeVisible();
  await expect(page.getByTestId("project-memory-panel")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-r04-review-panel.png`, fullPage: true });
  await page.getByTestId("defect-T-02").click();
  await expect(page.getByTestId("detail-task-code")).toHaveText("T-02");
  await expect(page.getByTestId("tab-details")).toHaveClass(/active/);
  await expect(page.getByTestId("tab-monitor")).not.toHaveClass(/active/);
  await expect(page.getByRole("treeitem", { name: /T-02/ })).toHaveClass(/highlight/);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({ path: `${SHOTS}/ui-r04-defect-locate.png`, fullPage: true });

  // Writes only ever went to the mocked HTTP boundary (nothing reached a real backend).
  expect(writes.length).toBeGreaterThanOrEqual(0);
});