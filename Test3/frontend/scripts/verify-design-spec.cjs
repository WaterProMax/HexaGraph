/**
 * 设计规格入口浏览器回归（mock /api/，不打真实模型）。
 *
 * 覆盖：完整闭环；输入缺项；生成失败；任务失败。
 * 依赖：本机 Vite + 可选 Playwright（UI_PLAYWRIGHT_MODULE / UI_BROWSER_PATH）。
 */
const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const out = process.env.UI_SCREENSHOT_DIR
  ? path.resolve(process.env.UI_SCREENSHOT_DIR)
  : path.resolve(__dirname, '../../docs/design/screenshots');
const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5173';

const SPEC = {
  features: [{ code: 'F1', title: '查看空闲座位', priority: 'P0', sources: ['§2'] }],
  scenarios: [{ code: 'S1', title: '找空位' }],
};
const DESIGN = {
  modules: [
    { code: 'M1', name: '座位查询', responsibility: '返回空闲座位', sources: ['F1'], depends_on: [] },
  ],
  interfaces: [{ code: 'C1', provider: 'M1', consumers: [] }],
};
const PLAN = {
  tasks: [
    {
      code: 'T-01',
      title: '实现座位查询',
      kind: 'impl',
      module: 'M1',
      sources: ['F1'],
      description: '实现座位查询',
      depends_on: [],
      acceptance: [{ cmd: ['pytest'], pass_criteria: 'ok', from_criterion: 'F1' }],
      role: 'coder',
      points: 2,
      priority: 'P0',
    },
    {
      code: 'T-02',
      title: '前后端联调',
      kind: 'impl',
      module: 'M1',
      sources: ['F1'],
      description: '联调',
      depends_on: ['T-01'],
      acceptance: [{ cmd: ['pytest'], pass_criteria: 'ok', from_criterion: 'F1' }],
      role: 'coder',
      points: 2,
      priority: 'P0',
    },
  ],
};

function designRun(id, stage = '5', status = 'waiting', extra = {}) {
  return {
    id,
    idea: '设计规格导入',
    stage,
    status,
    origin: 'design_spec',
    provenance: {
      generation: 'preset',
      generation_label: '预置测试输出（scripted）',
      execution: 'simulated',
      execution_label: '模拟执行（预置工具调用）',
    },
    gates: extra.gates ?? [{ id: `gate-design-${id}`, kind: 'DESIGN基线确认', status: 'pending' }],
    paused: false,
    ...extra,
  };
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const launchOpts = { headless: true };
  if (process.env.UI_BROWSER_PATH) {
    launchOpts.executablePath = process.env.UI_BROWSER_PATH;
  } else if (process.env.UI_BROWSER_CHANNEL) {
    launchOpts.channel = process.env.UI_BROWSER_CHANNEL;
  } else {
    // macOS / CI 优先用本机 Chrome，避免额外下载 Playwright 浏览器包。
    launchOpts.channel = 'chrome';
  }
  const browser = await chromium.launch(launchOpts);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  let mode = 'happy'; // happy | missing | failed_gen | task_fail
  let runs = [];
  let tasks = [];
  let artifacts = {};
  let designCreateBody = null;
  const posts = [];

  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ contentType: 'text/css', body: '' }),
  );

  // 只拦截后端 /api/*，不要误伤 /src/api/client.ts 等前端模块。
  await page.route((url) => {
    try {
      return new URL(url).pathname.startsWith('/api/');
    } catch {
      return false;
    }
  }, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^\/api/, '');
    let data = {};

    if (req.method() === 'POST') {
      const body = req.postData() ? req.postDataJSON() : null;
      posts.push({ p, body });

      if (p === '/projects') {
        data = { id: 'design-project' };
      } else if (/\/design-runs$/.test(p)) {
        designCreateBody = body;
        if (mode === 'missing') {
          data = {
            run_id: 'run-missing',
            project_id: 'design-project',
            status: 'needs_input',
            input: { kind: 'text', chars: (body.text || '').length, sha256: 'abc', source: body.source || {} },
            spec: null,
            design: null,
            missing: ['未给出并发上限', '缺少可检查的验收条件'],
            errors: [],
            checks: {},
            gate: null,
            provenance: { generation: 'preset', generation_label: '预置测试输出（scripted）' },
            message: '设计规格缺少必要内容，未进入任务分解',
          };
          runs = [
            designRun('run-missing', '5', 'stopped', {
              gates: [],
            }),
          ];
          artifacts = {
            design_input: { text: body.text, source: body.source, chars: data.input.chars, sha256: 'abc' },
            design_input_missing: data.missing,
            provenance: data.provenance,
          };
        } else if (mode === 'failed_gen') {
          data = {
            run_id: 'run-failed',
            project_id: 'design-project',
            status: 'failed',
            input: { kind: 'text', chars: (body.text || '').length, sha256: 'def', source: body.source || {} },
            spec: null,
            design: null,
            missing: [],
            errors: ['设计规格整理失败: model timeout'],
            checks: {},
            gate: null,
            provenance: { generation: 'preset', generation_label: '预置测试输出（scripted）' },
            message: '设计规格整理失败: model timeout',
          };
          runs = [designRun('run-failed', '5', 'stopped', { gates: [] })];
          artifacts = {
            design_input: { text: body.text, source: body.source, chars: data.input.chars, sha256: 'def' },
            design_input_errors: data.errors,
            provenance: data.provenance,
          };
        } else {
          data = {
            run_id: 'run-happy',
            project_id: 'design-project',
            status: 'awaiting_confirmation',
            input: { kind: 'text', chars: (body.text || '').length, sha256: 'ok', source: body.source || {} },
            spec: SPEC,
            design: DESIGN,
            missing: [],
            errors: [],
            checks: { spec: [], design: [] },
            gate: { id: 'gate-design-run-happy', kind: 'DESIGN基线确认', status: 'pending' },
            provenance: {
              generation: 'preset',
              generation_label: '预置测试输出（scripted）',
              execution: 'simulated',
              execution_label: '模拟执行（预置工具调用）',
            },
            message: '设计规格已整理，等待你确认',
          };
          runs = [designRun('run-happy')];
          artifacts = {
            design_input: { text: body.text, source: body.source, chars: data.input.chars, sha256: 'ok' },
            spec: SPEC,
            design: DESIGN,
            provenance: data.provenance,
          };
          tasks = [];
        }
      } else if (p.startsWith('/gates/') && p.endsWith('/resolve')) {
        const run = runs[0];
        if (!run) data = {};
        else if (run.gates[0]?.kind === 'DESIGN基线确认' && body.decision === 'approve') {
          run.gates = [{ id: 'gate-plan-run-happy', kind: 'PLAN基线确认', status: 'pending' }];
          run.stage = '6';
          artifacts.plan = PLAN;
          artifacts.baseline_DESIGN = '1.0';
          data = { status: 'waiting', gate: run.gates[0] };
        } else if (run.gates[0]?.kind === 'PLAN基线确认' && body.decision === 'approve') {
          run.gates = [];
          run.stage = '7';
          run.status = 'executing';
          artifacts.baseline_PLAN = '1.0';
          tasks = PLAN.tasks.map((t) => ({
            code: t.code,
            state: t.depends_on?.length ? 'pending' : 'ready',
            revision: 1,
            card: t,
            last_error: mode === 'task_fail' && t.code === 'T-01' ? '验收失败' : null,
          }));
          if (mode === 'task_fail') {
            tasks = tasks.map((t) =>
              t.code === 'T-01' ? { ...t, state: 'failed', last_error: '验收失败：断言未通过' } : t,
            );
          }
          data = { status: 'executing' };
        } else {
          data = { status: 'ok' };
        }
      } else if (p.endsWith('/schedule')) {
        if (mode !== 'task_fail') {
          tasks = tasks.map((t) =>
            t.code === 'T-01' ? { ...t, state: 'done' } : t.code === 'T-02' ? { ...t, state: 'ready' } : t,
          );
        }
        data = { started: mode === 'task_fail' ? [] : ['T-01'] };
      }
    } else if (p === '/runs') data = runs;
    else if (/\/events$/.test(p)) {
      if (mode === 'task_fail' && url.pathname.includes('run-happy')) {
        // 故意让 SSE 失败：返回非 event-stream，触发前端断开提示（活动页再验）。
        return route.fulfill({ status: 500, contentType: 'text/plain', body: 'sse down' });
      }
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': design-spec test\n\n' });
    } else if (p.endsWith('/events/history')) data = [];
    else if (p.endsWith('/artifacts')) data = artifacts;
    else if (p.endsWith('/tasks')) data = tasks;
    else if (p.endsWith('/budget')) data = { used: 100, limit: 1500000 };
    else if (/^\/runs\/[^/]+$/.test(p)) data = runs.find((r) => r.id === p.split('/')[2]) || runs[0] || {};
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });

  // —— 1. 完整闭环 ——
  mode = 'happy';
  await page.goto(`${baseUrl}/workstation`);
  await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill(
    '# 自习室\n目标：学生查看空闲座位。\n§2 座位查询：显示剩余座位与开放时段。',
  );
  await page.getByRole('button', { name: '整理并检查', exact: true }).click();
  await page.waitForURL('**/workstation/run-happy');
  await page.getByTestId('design-spec-preview').waitFor();
  assert(posts.some((x) => /\/design-runs$/.test(x.p) && x.body.text.includes('自习室')));
  await page.locator('.gate-card .gate-head').filter({ hasText: 'DESIGN基线确认' }).waitFor();
  // 跳过阶段应显示「不适用」
  assert((await page.locator('.row[data-status="skipped"]').count()) >= 1);
  // message.success 浮层可能挡住点击；等浮层消失或强制点批准。
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.locator('.gate-card .gate-actions .ant-btn-primary').click({ force: true });
  await page.locator('.gate-card .gate-head').filter({ hasText: 'PLAN基线确认' }).waitFor();
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.locator('.gate-card .gate-actions .ant-btn-primary').click({ force: true });
  await page.locator('.topbar-right .pill').filter({ hasText: '阶段 7' }).waitFor({ timeout: 10000 });
  await page.locator('.topbar-right').getByRole('button', { name: /调度执行/ }).click({ force: true });
  await page.waitForTimeout(400);
  assert(posts.some((x) => x.p.includes('/schedule')));
  await page.screenshot({ path: path.join(out, 'design-spec-happy.png') });
  console.log('PASS happy path: design import → DESIGN → PLAN → schedule');

  // —— 2. 输入缺项 ——
  mode = 'missing';
  posts.length = 0;
  await page.goto(`${baseUrl}/workstation`);
  await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill('目标：学生查看空位。');
  await page.getByRole('button', { name: '整理并检查', exact: true }).click();
  await page.waitForURL('**/workstation/run-missing');
  await page.getByText('缺少必要内容', { exact: false }).waitFor();
  assert.equal(await page.getByRole('heading', { name: 'DESIGN基线确认', exact: true }).count(), 0);
  await page.screenshot({ path: path.join(out, 'design-spec-missing.png') });
  console.log('PASS missing input stops before planning');

  // —— 3. 生成失败 ——
  mode = 'failed_gen';
  await page.goto(`${baseUrl}/workstation`);
  await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill('目标：学生查看空位。');
  await page.getByRole('button', { name: '整理并检查', exact: true }).click();
  await page.waitForURL('**/workstation/run-failed');
  await page.getByTestId('design-spec-preview').getByText(/model timeout/).waitFor();
  assert.equal(await page.locator('.gate-card .gate-head').filter({ hasText: 'DESIGN基线确认' }).count(), 0);
  await page.screenshot({ path: path.join(out, 'design-spec-failed-gen.png') });
  console.log('PASS generation failure surfaces error');

  // —— 4. 任务失败 + SSE 异常 ——
  mode = 'happy';
  await page.goto(`${baseUrl}/workstation`);
  await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill('# 自习室\n目标与验收齐全。');
  await page.getByRole('button', { name: '整理并检查', exact: true }).click();
  await page.waitForURL('**/workstation/run-happy');
  mode = 'task_fail';
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.locator('.gate-card .gate-actions .ant-btn-primary').click({ force: true });
  await page.locator('.gate-card .gate-head').filter({ hasText: 'PLAN基线确认' }).waitFor();
  await page.locator('.gate-card .gate-actions .ant-btn-primary').click({ force: true });
  await page.locator('.ws-left .row').filter({ hasText: 'T-01' }).waitFor();
  await page.locator('.ws-left .row').filter({ hasText: 'T-01' }).click();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '节点详情' }).click();
  await page.getByTestId('wait-reason').filter({ hasText: /验收失败/ }).waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '活动' }).click();
  await page.getByTestId('events-connection-error').waitFor();
  await page.screenshot({ path: path.join(out, 'design-spec-task-fail.png') });
  console.log('PASS task failure detail + SSE disconnect alert');

  assert.ok(designCreateBody && designCreateBody.text);
  assert.deepEqual(errors, []);
  console.log('PASS no browser runtime errors');
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
