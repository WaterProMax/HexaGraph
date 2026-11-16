/* 设计规格页面 + 真实 FastAPI HTTP 闭环；不拦截 /api，不调用真实模型。 */
const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5173';
const apiBase = process.env.API_BASE_URL || 'http://127.0.0.1:8765/api';
const out = process.env.UI_SCREENSHOT_DIR
  ? path.resolve(process.env.UI_SCREENSHOT_DIR)
  : path.resolve(__dirname, '../../docs/design/screenshots');

async function api(pathname) {
  const response = await fetch(`${apiBase}${pathname}`);
  const body = await response.text();
  assert.equal(response.ok, true, `GET ${pathname}: ${response.status} ${body}`);
  return JSON.parse(body);
}

async function waitForTasks(runId, expectedState, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let tasks = [];
  while (Date.now() < deadline) {
    tasks = await api(`/runs/${runId}/tasks`);
    if (tasks.length === 2 && tasks.every((task) => task.state === expectedState)) return tasks;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`task states did not become ${expectedState}: ${JSON.stringify(tasks.map((t) => [t.code, t.state]))}`);
}

async function approveGate(page, kind) {
  await page.locator('.gate-card .gate-head').filter({ hasText: kind }).waitFor();
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.locator('.gate-card .gate-actions .ant-btn-primary').click({ force: true });
}

async function createDesign(page, text) {
  await page.goto(`${baseUrl}/workstation`);
  await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill(text);
  await page.getByRole('button', { name: '整理并检查', exact: true }).click();
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const launchOpts = { headless: true };
  if (process.env.UI_BROWSER_PATH) launchOpts.executablePath = process.env.UI_BROWSER_PATH;
  else launchOpts.channel = process.env.UI_BROWSER_CHANNEL || 'chrome';
  const browser = await chromium.launch(launchOpts);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await createDesign(page, '# 自习室\n目标：学生查看空闲座位。\n§2 座位查询：显示剩余座位与开放时段。');
  await page.waitForURL(/\/workstation\/[0-9a-f-]{36}$/);
  const runId = page.url().split('/').pop();
  await page.getByTestId('design-import-status').filter({ hasText: '等待 DESIGN 确认' }).waitFor();
  let run = await api(`/runs/${runId}`);
  assert.equal(run.origin, 'design_spec');
  assert.equal(run.stage, '5');
  assert.equal(run.gates[0].kind, 'DESIGN基线确认');

  await approveGate(page, 'DESIGN基线确认');
  await page.locator('.gate-card .gate-head').filter({ hasText: 'PLAN基线确认' }).waitFor();
  let artifacts = await api(`/runs/${runId}/artifacts`);
  assert.equal(artifacts.design_input_status, 'design_confirmed');
  assert.deepEqual(artifacts.plan.tasks.map((task) => task.code), ['T-01', 'T-02']);
  assert.deepEqual(artifacts.plan.tasks[1].depends_on, ['T-01']);

  await approveGate(page, 'PLAN基线确认');
  await page.locator('.topbar-right .pill').filter({ hasText: '阶段 7' }).waitFor();
  let tasks = await api(`/runs/${runId}/tasks`);
  assert.deepEqual(tasks.map((task) => task.code), ['T-01', 'T-02']);
  assert.equal(tasks[0].state, 'ready');
  assert.equal(tasks[1].state, 'pending');
  assert.deepEqual(tasks[1].card.depends_on, ['T-01']);

  await page.getByTestId('run-pause-resume').click();
  await page.locator('.topbar-right').getByText('已暂停').waitFor();
  assert.equal(await page.getByRole('button', { name: '调度执行' }).isDisabled(), true);
  const paused = await api(`/runs/${runId}`);
  assert.equal(paused.paused, true);
  const pausedTasks = await api(`/runs/${runId}/tasks`);
  assert.equal(pausedTasks[0].state, 'ready');
  await page.getByTestId('run-pause-resume').click();
  await page.getByTestId('run-pause-resume').filter({ hasText: '暂停' }).waitFor();
  assert.equal((await api(`/runs/${runId}`)).paused, false);

  await page.locator('.topbar-right').getByRole('button', { name: /调度执行/ }).click({ force: true });
  tasks = await waitForTasks(runId, 'done');
  for (const task of tasks) {
    await page.locator('.ws-left .row').filter({ hasText: task.code }).filter({ hasText: task.state }).waitFor();
  }
  await page.locator('.ws-left .row').filter({ hasText: 'T-02' }).click();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '任务计划' }).click();
  await page.getByTestId('task-plan-preview').getByText('T-01', { exact: true }).first().waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '规格产物' }).click();
  await page.getByText('T-01', { exact: true }).first().waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '活动' }).click();
  await page.locator('.canvas-scroll').waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '节点详情' }).click();
  const details = await page.locator('.canvas-scroll').innerText();
  assert(details.includes('上游依赖') && details.includes('T-01'));

  await page.reload();
  assert.equal(page.url().split('/').pop(), runId);
  await page.getByTestId('design-import-status').filter({ hasText: 'PLAN 已确认' }).waitFor();
  await waitForTasks(runId, 'done');
  run = await api(`/runs/${runId}`);
  assert.equal(run.id, runId);
  await page.screenshot({ path: path.join(out, 'design-spec-http-happy.png') });
  console.log(`PASS real HTTP happy path + refresh: ${runId}`);

  await createDesign(page, '目标：学生查看空位；缺少并发与验收细则。');
  await page.waitForURL((url) => /\/workstation\/[0-9a-f-]{36}$/.test(url.pathname) && !url.pathname.endsWith(runId));
  const missingRunId = page.url().split('/').pop();
  await page.getByTestId('design-import-status').filter({ hasText: '缺少必要内容' }).waitFor();
  assert.equal(await page.locator('.gate-card').count(), 0);
  assert.deepEqual(await api(`/runs/${missingRunId}/tasks`), []);
  const stages = await api(`/runs/${missingRunId}/stages`);
  assert.deepEqual(stages.history, []);
  await page.reload();
  await page.getByTestId('design-import-status').filter({ hasText: '缺少必要内容' }).waitFor();
  assert.equal(await page.locator('.gate-card').count(), 0);
  assert.deepEqual(await api(`/runs/${missingRunId}/tasks`), []);
  await page.screenshot({ path: path.join(out, 'design-spec-http-missing.png') });
  console.log(`PASS real HTTP missing-input path + refresh: ${missingRunId}`);

  assert.deepEqual(errors, []);
  console.log('PASS no browser runtime errors; all confirmations and scheduling used the page');
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
