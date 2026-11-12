const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const captures = path.resolve(__dirname, '../../docs/design/screenshots');
const out = process.env.UI_SCREENSHOT_DIR ? path.resolve(process.env.UI_SCREENSHOT_DIR) : captures;
const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5173';
const mockRun = (id = 'visual-spec-run') => ({ id, idea: '做一个帮同学在期末周找到有空位自习室的小程序。', stage: '4', status: 'waiting', gates: [{ id: 'gate-spec', kind: 'SPEC基线确认', status: 'pending' }] });
const artifacts = { idea_card: { approach: '查询空闲教室，查看实时座位与开放时间' }, spec: { features: [{}, {}, {}] }, issues: [], utterances: [] };
async function main() {
  fs.mkdirSync(out, { recursive: true });
  fs.mkdirSync(captures, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.UI_BROWSER_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', err => { errors.push(err.message); console.log('PAGE_ERROR', err.message); });
  page.on('console', msg => { if (msg.type() === 'error') console.log('CONSOLE_ERROR', msg.text()); });
  let runs = [mockRun()];
  let tasks = [];
  const posts = [];
  // Use system fallback fonts for deterministic, offline-friendly screenshots.
  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, route => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('**/api/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const p = url.pathname.replace('/api', '');
    let data = {};
    if (req.method() === 'POST') {
      const body = req.postData() ? req.postDataJSON() : null;
      posts.push({ p, body });
      if (p === '/projects') data = { id: 'visual-project' };
      else if (p === '/projects/visual-project/runs') { runs = [...runs.filter(r => r.id !== 'visual-new-run'), mockRun('visual-new-run')]; data = { run: runs.at(-1) }; }
      else if (p.startsWith('/gates/')) { runs = runs.map(r => ({ ...r, gates: [] })); }
      else if (p.endsWith('/pause')) { runs = runs.map(r => ({ ...r, paused: true })); }
      else if (p.endsWith('/resume')) { runs = runs.map(r => ({ ...r, paused: false })); }
    } else if (p === '/runs') data = runs;
    else if (/\/events$/.test(p)) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': visual test\n\n' });
    else if (p.endsWith('/events/history')) data = [];
    else if (p.endsWith('/artifacts')) data = artifacts;
    else if (p.endsWith('/tasks')) data = tasks;
    else if (p.endsWith('/budget')) data = { used: 18200, limit: 1500000 };
    else if (/^\/runs\/[^/]+$/.test(p)) data = runs.find(r => r.id === p.split('/')[2]) || runs[0];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${baseUrl}/workstation/visual-spec-run`);
  await page.getByRole('heading', { name: 'SPEC基线确认', exact: true }).waitFor();
  await page.waitForTimeout(1000);
  assert.equal(await page.locator('.phase-list > .phase').count(), 4);
  assert.equal(await page.locator('.ws-left .glass-panel').count(), 7);
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-desktop.png') });
  await page.locator('.ws-left').screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-panel.png') });
  const visualTokens = await page.locator('.ws').evaluate(el => {
    const style = getComputedStyle(el);
    const textColor = selector => getComputedStyle(el.querySelector(selector)).color;
    return { ink: style.getPropertyValue('--glass-ink').trim(), secondary: style.getPropertyValue('--glass-secondary').trim(), muted: style.getPropertyValue('--glass-muted').trim(), subtitle: textColor('.flow-node .sub'), state: textColor('.flow-node .state') };
  });
  assert.equal(visualTokens.ink, '#122d42');
  assert.equal(visualTokens.muted, '#405c71');
  assert.equal(visualTokens.subtitle, 'rgb(64, 92, 113)');
  const luminance = hex => {
    const rgb = hex.match(/[a-f0-9]{2}/gi).map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  };
  for (const bg of ['#cce5f4', '#e9f4fb', '#f0f9ff']) {
    const contrast = (luminance(bg) + .05) / (luminance(visualTokens.muted) + .05);
    assert(contrast >= 4.5, `muted contrast ${contrast.toFixed(2)} on ${bg}`);
    console.log(`PASS muted text contrast ${contrast.toFixed(2)}:1 on ${bg}`);
  }
  const toolbarMetrics = async () => page.locator('.topbar, .canvas-toolbar, .dock').evaluateAll(els => els.map(el => ({ name: el.className, width: el.clientWidth, scrollWidth: el.scrollWidth })));
  for (const metric of await toolbarMetrics()) assert(metric.scrollWidth <= metric.width + 1, JSON.stringify(metric));
  await page.locator('.topbar').getByRole('button', { name: '暂停', exact: true }).click();
  await page.locator('.topbar').getByRole('button', { name: '恢复', exact: true }).waitFor();
  await page.locator('.topbar').getByRole('button', { name: '恢复', exact: true }).click();
  await page.locator('.topbar').getByRole('button', { name: '暂停', exact: true }).waitFor();
  assert(posts.some(p => p.p === '/runs/visual-spec-run/pause'));
  assert(posts.some(p => p.p === '/runs/visual-spec-run/resume'));
  const auto = page.getByRole('switch', { name: '自动过关' });
  await auto.focus();
  await page.keyboard.press('Space');
  assert.equal(await auto.getAttribute('aria-checked'), 'true');
  await page.keyboard.press('Space');
  assert.equal(await auto.getAttribute('aria-checked'), 'false');
  await page.locator('.topbar .ant-select-selector').click();
  await page.locator('.glass-select-popup .ant-select-item-option').first().waitFor();
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-selector.png') });
  await page.keyboard.press('Escape');
  const zoom = () => page.locator('.react-flow__viewport').evaluate(el => getComputedStyle(el).transform);
  const zoomBefore = await zoom();
  await page.locator('.react-flow__controls-zoomin').click();
  await page.waitForTimeout(300);
  assert.notEqual(await zoom(), zoomBefore);
  await page.locator('.react-flow__controls-zoomout').click();
  await page.locator('.react-flow__controls-fitview').click();
  for (const label of ['节点详情', '规格产物', '活动']) {
    await page.locator('.canvas-toolbar .chip').filter({ hasText: label }).click();
    assert.equal(await page.locator('.canvas-toolbar .chip').filter({ hasText: label }).getAttribute('aria-pressed'), 'true');
    await page.screenshot({ path: path.join(out, `HexaGraph-Ice-Glass-${label}.png`) });
  }
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '流程图' }).click();
  await page.locator('.dock').getByRole('button', { name: '查看产物', exact: true }).click();
  assert.equal(await page.locator('.canvas-toolbar .chip').filter({ hasText: '规格产物' }).getAttribute('aria-pressed'), 'true');
  await page.locator('.canvas-toolbar .chip').filter({ hasText: '流程图' }).click();
  console.log('PASS contrast tokens, topbar pause/resume, keyboard switch, select popup, zoom/fit, 4 tabs, dock action');
  await page.locator('.ws-left .row').filter({ hasText: '需求规格基线' }).click();
  assert.equal(await page.locator('.ws-left .row.active .code').innerText(), 'SPEC');
  const first = page.locator('.ws-left .row').first();
  await first.focus();
  await page.keyboard.press('Enter');
  assert.equal(await first.getAttribute('aria-pressed'), 'true');
  await page.locator('.ws-left .row').nth(1).focus();
  await page.keyboard.press('Space');
  assert.equal(await page.locator('.ws-left .row').nth(1).getAttribute('aria-pressed'), 'true');
  await page.getByRole('textbox', { name: '裁决理由', exact: true }).fill('视觉回归测试');
  await page.getByRole('button', { name: '批准并推进', exact: true }).click();
  await page.waitForTimeout(300);
  assert(posts.some(p => p.p === '/gates/gate-spec/resolve' && p.body.decision === 'approve' && p.body.payload.reason === '视觉回归测试'));
  runs = [mockRun()];
  await page.reload();
  await page.getByRole('heading', { name: 'SPEC基线确认', exact: true }).waitFor();
  await page.getByRole('button', { name: '驳回重写', exact: true }).click();
  await page.waitForTimeout(300);
  assert(posts.some(p => p.p === '/gates/gate-spec/resolve' && p.body.decision === 'reject'));
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('视觉测试项目');
  await page.getByRole('textbox', { name: '产品想法', exact: true }).fill('视觉测试想法');
  await page.getByRole('button', { name: /^启动/ }).click();
  await page.waitForURL('**/workstation/visual-new-run');
  assert(posts.some(p => p.p === '/projects' && p.body.name === '视觉测试项目'));
  assert(posts.some(p => p.p === '/projects/visual-project/runs' && p.body.idea === '视觉测试想法'));
  await page.locator('.recent-runs a').filter({ hasText: runs[0].idea }).last().click();
  await page.waitForURL('**/workstation/visual-spec-run');
  console.log('PASS grouped modules, click selection, Enter/Space, approve/reject payloads, start, recent navigation (mocked API)');
  const beforeQuickStart = posts.length;
  await page.locator('.composer button').filter({ hasText: '一键推进到执行' }).click();
  await page.waitForURL('**/workstation/visual-new-run');
  assert(posts.slice(beforeQuickStart).some(p => p.p === '/gates/gate-spec/resolve' && p.body.payload.reason === 'Workstation 一键推进基线确认'));
  console.log('PASS quick start retains automatic gate approval semantics (mocked API)');
  runs = [mockRun()];
  for (const width of [1280, 1024, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${baseUrl}/workstation/visual-spec-run`);
    await page.locator('.gate-card').waitFor();
    await page.waitForTimeout(700);
    const metrics = await page.locator('.ws-left').evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth, bottom: el.getBoundingClientRect().bottom, viewport: innerHeight }));
    assert(metrics.scrollWidth <= metrics.width + 1, `panel horizontal overflow at ${width}: ${JSON.stringify(metrics)}`);
    assert(metrics.bottom <= metrics.viewport + 1);
    assert(await page.getByRole('button', { name: '批准并推进', exact: true }).isVisible());
    for (const metric of await toolbarMetrics()) assert(metric.scrollWidth <= metric.width + 1, `${width}px ${JSON.stringify(metric)}`);
    await page.screenshot({ path: path.join(out, `HexaGraph-Ice-Glass-${width}.png`) });
    console.log(`PASS ${width}px: panel ${metrics.width}px, no inner horizontal overflow`);
  }
  await page.setViewportSize({ width: 1600, height: 1100 });
  runs = [];
  await page.goto(`${baseUrl}/workstation`);
  await page.getByText('暂无运行', { exact: true }).waitFor();
  assert.equal(await page.locator('.gate-card').count(), 0);
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-empty.png') });
  console.log('PASS empty state');
  // Failed acceptance must still require an explicit reason.
  runs = [{ ...mockRun(), stage: '8', gates: [{ id: 'gate-spec', status: 'pending', kind: '验收确认', payload: { pass: false } }] }];
  await page.goto(`${baseUrl}/workstation/visual-spec-run`);
  await page.getByRole('heading', { name: '验收确认', exact: true }).waitFor();
  assert(await page.getByRole('button', { name: '批准并推进', exact: true }).isDisabled());
  await page.getByRole('textbox', { name: '裁决理由', exact: true }).fill('需要人工确认的理由');
  assert(await page.getByRole('button', { name: '批准并推进', exact: true }).isEnabled());
  console.log('PASS failed acceptance reason guard');
  runs = [{ ...mockRun(), stage: '7', gates: [] }];
  artifacts.design = { modules: Array.from({ length: 8 }, (_, i) => ({ code: `M${i + 1}`, name: `长模块标题${'布局测试'.repeat(8)}`, responsibility: '副文'.repeat(50) })), interfaces: [] };
  artifacts.plan = { tasks: Array.from({ length: 20 }, (_, i) => ({ code: `T-${String(i + 1).padStart(2, '0')}`, title: `长任务标题${'前端组件测试'.repeat(8)}`, points: 1 })) };
  await page.reload();
  await page.locator('.ws-left .row').filter({ hasText: 'T-20' }).waitFor({ state: 'attached' });
  const longMetrics = await page.locator('.ws-left').evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight, height: el.clientHeight }));
  assert(longMetrics.scrollHeight > longMetrics.height);
  assert(longMetrics.scrollWidth <= longMetrics.width + 1);
  await page.locator('.ws-left .row').filter({ hasText: 'T-20' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-long-list.png') });
  console.log('PASS long titles, 8 modules / 20 tasks, independent scrolling');
  tasks = [{ code: 'T-01', state: 'running', revision: 1, card: { title: '实现自习室查询界面', points: 1, role: 'coder', module: 'M1', kind: 'impl' } }];
  await page.reload();
  await page.locator('.dock-actions .ant-input').waitFor();
  assert(await page.locator('.dock-actions').getByRole('button', { name: '重试', exact: true }).isDisabled());
  assert(await page.locator('.dock-actions').getByRole('button', { name: '暂停', exact: true }).isEnabled());
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-task-controls.png') });
  await page.locator('.dock-actions').getByRole('button', { name: '详情', exact: true }).click();
  await page.getByRole('textbox', { name: '任务控制理由' }).fill('视觉回归，不实际控制任务');
  assert(await page.locator('.canvas-scroll').getByRole('button', { name: '重试', exact: true }).isDisabled());
  await page.screenshot({ path: path.join(out, 'HexaGraph-Ice-Glass-task-details.png') });
  console.log('PASS runtime task dock/detail control states unchanged');
  assert.deepEqual(errors, []);
  console.log('PASS no browser runtime errors');
  for (const name of ['HexaGraph-Ice-Glass-desktop.png', 'HexaGraph-Ice-Glass-panel.png', 'HexaGraph-Ice-Glass-1024.png', 'HexaGraph-Ice-Glass-empty.png']) if (out !== captures) fs.copyFileSync(path.join(out, name), path.join(captures, name));
  await browser.close();
}
main().catch(err => { console.error(err); process.exit(1); });


