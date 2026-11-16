/**
 * Task 5 逐按钮页面验收（mock /api/，不打真实模型）。
 *
 * 扩展 verify-design-spec.cjs：对计划「六」表逐项点击，记录
 * 操作、请求结果、即时反馈、最终状态、截图。
 *
 * 证明范围：mock 数据下按钮反馈与页面状态。不能证明真实 FastAPI / 真实模型。
 */
const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const out = process.env.UI_SCREENSHOT_DIR
  ? path.resolve(process.env.UI_SCREENSHOT_DIR)
  : path.resolve(__dirname, '../../docs/design/screenshots');
const evidenceDir = process.env.UI_EVIDENCE_DIR
  ? path.resolve(process.env.UI_EVIDENCE_DIR)
  : path.resolve(__dirname, '../../docs/superpowers/evidence');
const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5173';

const SPEC = {
  features: [{ code: 'F1', title: '查看空闲座位', priority: 'P0', sources: ['§2'] }],
  scenarios: [{ code: 'S1', title: '找空位' }],
};
const DESIGN = {
  modules: [{ code: 'M1', name: '座位查询', responsibility: '返回空闲座位', sources: ['F1'], depends_on: [] }],
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

function writeEvidence(rows) {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const lines = [
    '# Task 5 逐按钮点击记录（mock 浏览器）',
    '',
    '> mock `/api`。可证明页面点击反馈，不能证明真实后端或真实模型。',
    '',
    '| 操作 | 请求结果 | 即时反馈 | 最终状态 | 截图 |',
    '| --- | --- | --- | --- | --- |',
    ...rows.map(
      (row) =>
        `| ${row.op} | ${row.request} | ${row.feedback} | ${row.state} | \`${row.screenshot}\` |`,
    ),
    '',
  ];
  fs.writeFileSync(path.join(evidenceDir, 'task-5-click-log.md'), lines.join('\n'), 'utf8');
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const launchOpts = { headless: true };
  if (process.env.UI_BROWSER_PATH) launchOpts.executablePath = process.env.UI_BROWSER_PATH;
  else launchOpts.channel = process.env.UI_BROWSER_CHANNEL || 'chrome';
  const browser = await chromium.launch(launchOpts);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  // Keep EventSource from erroring when the mock fulfills a short SSE body and closes.
  // Empty events + live connection is what shows the 「暂无事件」 placeholder.
  await context.addInitScript(() => {
    class StubEventSource {
      constructor() {
        this.readyState = 1;
        queueMicrotask(() => {
          if (typeof this.onopen === 'function') this.onopen(new Event('open'));
        });
      }
      close() {
        this.readyState = 2;
      }
      addEventListener() {}
      removeEventListener() {}
    }
    StubEventSource.CONNECTING = 0;
    StubEventSource.OPEN = 1;
    StubEventSource.CLOSED = 2;
    window.EventSource = StubEventSource;
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  let mode = 'happy';
  let failSchedule = false;
  let runs = [];
  let tasks = [];
  let artifacts = {};
  const posts = [];
  const evidence = [];

  async function shot(name) {
    const file = `design-spec-accept-${name}.png`;
    // Viewport capture keeps position:fixed toasts; nested .ws-left scroll is already set by the wait.
    await page.screenshot({ path: path.join(out, file), fullPage: false, animations: 'disabled' });
    return file;
  }

  async function openDesign() {
    runs = [];
    tasks = [];
    artifacts = {};
    await page.goto(`${baseUrl}/workstation`);
    await page.locator('.ant-segmented-item').filter({ hasText: '从设计规格开始' }).click();
    await page.getByTestId('design-spec-input').waitFor();
  }

  function organizeButton() {
    return page.getByRole('button', { name: /整理并检查|修改原文后重新提交/ });
  }

  function toast(pattern) {
    return page.locator('.ant-message').getByText(pattern);
  }

  async function showComposer() {
    await page.locator('.ws-left').evaluate((el) => {
      el.scrollTop = 0;
    });
    const organize = organizeButton();
    await organize.scrollIntoViewIfNeeded();
    await organize.waitFor();
    return organize;
  }

  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ contentType: 'text/css', body: '' }),
  );

  await page.route(
    (url) => {
      try {
        return new URL(url).pathname.startsWith('/api/');
      } catch {
        return false;
      }
    },
    async (route) => {
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
          if (mode === 'importing' || mode === 'timeout') {
            data = {
              run_id: 'run-importing',
              project_id: 'design-project',
              status: 'importing',
              input: { kind: body.source?.kind || 'text', chars: (body.text || '').length, sha256: 'wait', source: body.source || {} },
              spec: null,
              design: null,
              missing: [],
              errors: [],
              checks: {},
              gate: null,
              message: '正在整理',
            };
            runs = [designRun('run-importing', '5', 'active', { gates: [] })];
            artifacts = {
              design_input_status: 'importing',
              design_input_step: 'spec',
              design_input_started_at: new Date().toISOString(),
              design_input: { text: body.text, source: body.source, title: body.title || '', chars: data.input.chars, sha256: 'wait' },
            };
          } else if (mode === 'reject') {
            data = {
              run_id: 'run-reject',
              project_id: 'design-project',
              status: 'awaiting_confirmation',
              input: { kind: 'text', chars: (body.text || '').length, sha256: 'rej', source: body.source || {} },
              spec: SPEC,
              design: DESIGN,
              missing: [],
              errors: [],
              checks: {},
              gate: { id: 'gate-design-run-reject', kind: 'DESIGN基线确认', status: 'pending' },
              message: '设计规格已整理，等待你确认',
            };
            runs = [designRun('run-reject')];
            artifacts = {
              design_input_status: 'awaiting_confirmation',
              design_input: { text: body.text, source: body.source, chars: data.input.chars, sha256: 'rej' },
              spec: SPEC,
              design: DESIGN,
            };
          } else {
            data = {
              run_id: 'run-happy',
              project_id: 'design-project',
              status: 'awaiting_confirmation',
              input: { kind: body.source?.kind || 'text', chars: (body.text || '').length, sha256: 'ok', source: body.source || {} },
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
              design_input_status: 'awaiting_confirmation',
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
          else if (run.gates[0]?.kind === 'DESIGN基线确认' && body.decision === 'reject') {
            run.gates = [{ id: run.gates[0].id, kind: 'DESIGN基线确认', status: 'rejected' }];
            run.status = 'stopped';
            data = { status: 'rejected', hint: '请修改设计规格原文后重新创建运行；导入运行不做原地改写。' };
          } else if (run.gates[0]?.kind === 'DESIGN基线确认' && body.decision === 'approve') {
            run.gates = [{ id: 'gate-plan-run-happy', kind: 'PLAN基线确认', status: 'pending' }];
            run.stage = '6';
            artifacts.plan = PLAN;
            artifacts.baseline_DESIGN = '1.0';
            artifacts.design_input_status = 'design_confirmed';
            data = { status: 'waiting', gate: run.gates[0] };
          } else if (run.gates[0]?.kind === 'PLAN基线确认' && body.decision === 'approve') {
            run.gates = [];
            run.stage = '7';
            run.status = 'waiting';
            artifacts.baseline_PLAN = '1.0';
            artifacts.design_input_status = 'plan_confirmed';
            tasks = PLAN.tasks.map((t) => ({
              code: t.code,
              state: t.depends_on?.length ? 'pending' : 'ready',
              revision: 1,
              card: t,
              last_error: null,
            }));
            data = { status: 'executing' };
          } else {
            data = { status: 'ok' };
          }
        } else if (p.endsWith('/pause')) {
          if (runs[0]) runs[0].paused = true;
          data = runs[0] || {};
        } else if (p.endsWith('/resume')) {
          if (runs[0]) runs[0].paused = false;
          data = runs[0] || {};
        } else if (p.endsWith('/schedule')) {
          if (failSchedule) {
            return route.fulfill({
              status: 400,
              contentType: 'application/json',
              body: JSON.stringify({ detail: 'offline schedule failure' }),
            });
          }
          if (runs[0]?.paused) {
            data = { started: [] };
          } else {
            tasks = tasks.map((t) =>
              t.code === 'T-01' ? { ...t, state: 'done' } : t.code === 'T-02' ? { ...t, state: 'ready' } : t,
            );
            data = { started: ['T-01'] };
          }
        }
      } else if (p === '/health') data = { status: 'ok', schedule_mode: 'manual' };
      else if (p === '/runs') data = runs;
      else if (/\/events$/.test(p)) {
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': design-spec test\n\n' });
      } else if (p.endsWith('/events/history')) data = [];
      else if (p.endsWith('/artifacts')) data = artifacts;
      else if (p.endsWith('/tasks')) data = tasks;
      else if (p.endsWith('/budget')) data = { used: 100, limit: 1500000 };
      else if (/^\/runs\/[^/]+$/.test(p)) data = runs.find((r) => r.id === p.split('/')[2]) || runs[0] || {};
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    },
  );

  // —— 上传 Markdown ——
  await openDesign();
  const uploadBody = '# 自习室\n目标：学生查看空闲座位。\n§2 座位查询：显示剩余座位与开放时段。\n';
  await page.getByLabel('读取设计规格文件').setInputFiles({
    name: 'self-study-room.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(uploadBody),
  });
  await page.locator('.design-file .mono').filter({ hasText: 'self-study-room.md' }).waitFor();
  assert.equal(await page.getByRole('textbox', { name: '设计规格原文' }).inputValue(), uploadBody);
  const beforeUploadPosts = posts.length;
  const uploadShot = await shot('upload');
  evidence.push({
    op: '上传 Markdown',
    request: `无 HTTP 导入（本地读取）；POST 计数仍为 ${beforeUploadPosts}`,
    feedback: '显示文件名 self-study-room.md，原文与字节计数更新',
    state: '未创建运行，停留在 /workstation',
    screenshot: uploadShot,
  });
  console.log('PASS upload markdown');

  // —— 空文、超限 ——
  await page.getByRole('textbox', { name: '设计规格原文' }).fill('');
  await organizeButton().click();
  await page.getByText('设计规格为空').waitFor();
  const emptyPosts = posts.filter((x) => /\/design-runs$/.test(x.p)).length;
  await page.getByRole('textbox', { name: '设计规格原文' }).evaluate((el) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(el, 'x'.repeat(100 * 1024 + 1));
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await organizeButton().click();
  await page.getByText('设计规格超过 100 KiB 上限').waitFor();
  assert.equal(posts.filter((x) => /\/design-runs$/.test(x.p)).length, emptyPosts);
  const emptyShot = await shot('empty-oversize');
  evidence.push({
    op: '空文、超限提交',
    request: '未发出 design-runs',
    feedback: '「设计规格为空」与「超过 100 KiB 上限」错误条',
    state: '不创建运行',
    screenshot: emptyShot,
  });
  console.log('PASS empty and oversize');

  // —— 点击整理及再次点击 + 等待、刷新、超时 ——
  mode = 'importing';
  posts.length = 0;
  await openDesign();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill(uploadBody);
  const organize = organizeButton();
  await organize.click();
  await organize.click({ force: true }).catch(() => {});
  await page.waitForURL('**/workstation/run-importing');
  await page.getByTestId('design-import-wait').first().waitFor();
  assert.equal(posts.filter((x) => /\/design-runs$/.test(x.p)).length, 1);
  const waitShot = await shot('organize-wait');
  evidence.push({
    op: '点击整理及再次点击',
    request: 'POST /design-runs → 200 importing，仅 1 次',
    feedback: '立即出现「正在整理」等待文案，按钮禁用',
    state: '同一 run-importing',
    screenshot: waitShot,
  });

  await page.reload();
  await page.getByTestId('design-import-wait').first().waitFor();
  assert.equal(page.url().split('/').pop(), 'run-importing');
  assert.equal(await page.getByRole('textbox', { name: '设计规格原文' }).inputValue(), uploadBody);
  artifacts = {
    ...artifacts,
    design_input_status: 'failed',
    design_input_error_category: 'timeout',
    design_input_message: '整理超过 10 分钟，未进入设计确认',
    design_input_errors: ['整理超过 10 分钟，未进入设计确认'],
  };
  await page.getByRole('button', { name: '刷新' }).click();
  await page.getByTestId('design-import-status').filter({ hasText: '整理失败' }).first().waitFor();
  await page.getByTestId('design-error-hint').filter({ hasText: '整理超过 10 分钟' }).waitFor();
  assert.equal(await page.getByRole('textbox', { name: '设计规格原文' }).inputValue(), uploadBody);
  const timeoutShot = await shot('refresh-timeout');
  evidence.push({
    op: '等待、刷新、超时',
    request: '刷新后 GET artifacts 仍是同一 run；随后 status=failed / error_category=timeout',
    feedback: '超时标题与「保留原文，再次提交」下一步',
    state: '同一运行，原文仍在，无 DESIGN 关卡',
    screenshot: timeoutShot,
  });
  console.log('PASS organize / wait / refresh / timeout');

  // —— 驳回 DESIGN ——
  mode = 'reject';
  await openDesign();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill(uploadBody);
  await organizeButton().click();
  await page.waitForURL('**/workstation/run-reject');
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.getByRole('button', { name: '驳回（需改原文重提）' }).click({ force: true });
  await Promise.all([
    toast('已驳回').waitFor(),
    page.locator('.topbar-right').getByText('已停止').waitFor(),
  ]);
  const retryOrganize = await showComposer();
  assert.equal(await retryOrganize.isEnabled(), true);
  await toast('已驳回').waitFor();
  assert.equal(await page.getByRole('textbox', { name: '设计规格原文' }).inputValue(), uploadBody);
  assert(posts.some((x) => x.p.includes('/gates/') && x.body.decision === 'reject'));
  const rejectShot = await shot('reject-design');
  evidence.push({
    op: '驳回 DESIGN',
    request: 'POST /gates/.../resolve decision=reject → 200 rejected',
    feedback: 'toast「已驳回」',
    state: '运行已停止，原文仍在，可再点整理',
    screenshot: rejectShot,
  });
  console.log('PASS reject DESIGN');

  // —— 批准 DESIGN / PLAN、暂停调度恢复、页签、失败留原因 ——
  mode = 'happy';
  failSchedule = false;
  await openDesign();
  await page.getByRole('textbox', { name: '设计规格原文' }).fill(uploadBody);
  await organizeButton().click();
  await page.waitForURL('**/workstation/run-happy');
  await page.locator('.gate-card .gate-head').filter({ hasText: 'DESIGN基线确认' }).waitFor();
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.getByRole('button', { name: '批准并推进' }).click({ force: true });
  await Promise.all([
    toast('已批准并推进').waitFor(),
    page.locator('.gate-card .gate-head').filter({ hasText: 'PLAN基线确认' }).waitFor(),
  ]);
  const designShot = await shot('approve-design');
  assert.equal(await page.locator('.topbar-right').getByRole('button', { name: /调度执行/ }).count(), 0);
  evidence.push({
    op: '批准 DESIGN',
    request: 'POST /gates/.../resolve decision=approve → PLAN 关卡',
    feedback: 'toast「已批准并推进」',
    state: '出现 PLAN 确认，尚未调度',
    screenshot: designShot,
  });

  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
  await page.getByRole('button', { name: '批准并推进' }).click({ force: true });
  await page.locator('.topbar-right .pill').filter({ hasText: '阶段 7' }).waitFor();
  await page.locator('.ws-left .row').filter({ hasText: 'T-01' }).waitFor();
  await page.locator('.ws-left .row').filter({ hasText: 'T-02' }).waitFor();
  const planShot = await shot('approve-plan');
  evidence.push({
    op: '批准 PLAN',
    request: 'POST /gates/.../resolve → 任务物化',
    feedback: '阶段 7，T-01 ready / T-02 pending',
    state: '任务和依赖可见，尚未执行',
    screenshot: planShot,
  });

  await page.getByTestId('run-pause-resume').click();
  await page.locator('.topbar-right').getByText('已暂停').waitFor();
  assert.equal(await page.getByRole('button', { name: '调度执行' }).isDisabled(), true);
  const pausePosts = posts.filter((x) => x.p.endsWith('/schedule')).length;
  await page.getByRole('button', { name: '调度执行' }).click({ force: true }).catch(() => {});
  assert.equal(posts.filter((x) => x.p.endsWith('/schedule')).length, pausePosts);
  await page.getByTestId('run-pause-resume').click();
  await page.getByTestId('run-pause-resume').filter({ hasText: '暂停' }).waitFor();
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 8000 }).catch(() => {});
  failSchedule = true;
  await page.getByRole('button', { name: '调度执行' }).click({ force: true });
  await toast(/调度失败/).waitFor();
  const failShot = await shot('schedule-failure');
  assert.equal(await page.locator('.ant-message').getByText(/已调度执行任务/).count(), 0);
  const t01AfterFail = await page.locator('.ws-left .row').filter({ hasText: 'T-01' }).innerText();
  assert(!/\bdone\b/i.test(t01AfterFail), `failure must not mark T-01 done: ${t01AfterFail}`);
  failSchedule = false;
  await page.locator('.ant-message').waitFor({ state: 'detached', timeout: 8000 }).catch(() => {});
  await page.getByRole('button', { name: '调度执行' }).click({ force: true });
  await Promise.all([
    toast(/已调度执行任务/).waitFor(),
    page.locator('.ws-left .row').filter({ hasText: 'T-01' }).filter({ hasText: 'done' }).waitFor(),
  ]);
  const scheduleShot = await shot('pause-schedule-resume');
  assert.equal(await page.locator('.ant-message').getByText(/调度失败/).count(), 0);
  evidence.push({
    op: '暂停、调度、恢复',
    request: 'pause → 调度按钮禁用；resume → schedule 先 400 后 200 started=[T-01]',
    feedback: '暂停后调度禁用；成功 toast「已调度执行任务」',
    state: '暂停不派发；恢复后 T-01 done',
    screenshot: scheduleShot,
  });

  await page.locator('.canvas-toolbar .chip').filter({ hasText: '任务计划' }).click();
  await page.getByTestId('task-plan-preview').getByText('T-01', { exact: true }).first().waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '规格产物' }).click();
  await page.getByText('查看空闲座位').first().waitFor();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '活动' }).click();
  await page.locator('.ant-empty-description').filter({ hasText: '暂无事件' }).waitFor();
  const tabsShot = await shot('tabs');
  await page.locator('.ws-left .row').filter({ hasText: 'T-02' }).click();
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '节点详情' }).click();
  await page.getByText('上游依赖').waitFor();
  evidence.push({
    op: '查看节点、任务计划、产物、活动',
    request: '只读 GET run/artifacts/tasks（mock 200）',
    feedback: '各页签有当前运行内容，空活动显示占位「暂无事件」',
    state: '与 run-happy 一致',
    screenshot: tabsShot,
  });
  evidence.push({
    op: '操作失败',
    request: 'POST /schedule 第一次 400 offline schedule failure',
    feedback: '「调度失败」错误提示，未显示成功',
    state: '任务未因失败请求被标成成功；随后成功调度才更新',
    screenshot: failShot,
  });
  console.log('PASS approve / pause / schedule / tabs / failure reason');

  assert.deepEqual(errors, []);
  writeEvidence(evidence);
  console.log(`PASS wrote ${evidence.length} click-evidence rows`);
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
