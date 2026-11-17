const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5173';
const out = path.resolve(process.env.UI_SCREENSHOT_DIR || path.join(__dirname, '../../docs/design/screenshots/flow-edge-readability'));
const shouldAssert = process.env.FLOW_EDGE_ASSERT === '1';
const runId = 'flow-edge-visual';
const run = {
  id: runId,
  idea: '做一个帮同学在期末周找到有空位自习室的小程序。',
  stage: '7',
  status: 'running',
  paused: false,
  gates: [],
};
const cards = [
  { code: 'T-01', title: '实现座位查询接口', depends_on: [], role: 'coder', kind: 'impl', module: 'M1', points: 2 },
  { code: 'T-02', title: '实现座位状态展示', depends_on: ['T-01'], role: 'coder', kind: 'impl', module: 'M1', points: 2 },
];
const artifacts = {
  idea_card: { approach: '查询空闲教室，查看实时座位与开放时间' },
  spec: { features: [{ code: 'F1', title: '查看空闲座位' }] },
  design: { modules: [{ code: 'M1', name: '座位查询', responsibility: '查询与展示实时座位状态' }], interfaces: [] },
  plan: { tasks: cards, capacity: 40 },
};
const tasks = [
  { code: 'T-01', state: 'done', revision: 1, card: cards[0] },
  { code: 'T-02', state: 'ready', revision: 1, card: cards[1] },
];

async function edgeMetrics(page, id) {
  return page.locator(`.react-flow__edge[data-id="${id}"]`).evaluate(edge => {
    const path = edge.querySelector('.react-flow__edge-path');
    if (!path) throw new Error(`Missing edge path: ${edge.dataset.id}`);
    const style = getComputedStyle(path);
    const markerRef = path.getAttribute('marker-end') || style.markerEnd;
    const markerId = markerRef && decodeURIComponent(markerRef.match(/#([^\)]+)/)?.[1] || '').replace(/["']/g, '');
    const marker = markerId ? document.getElementById(markerId) : null;
    const markerPath = marker?.querySelector('path, polyline');
    return {
      className: edge.getAttribute('class') || '',
      stroke: style.stroke,
      strokeWidth: Number.parseFloat(style.strokeWidth),
      strokeDasharray: style.strokeDasharray,
      opacity: Number(style.opacity),
      markerColor: markerPath ? getComputedStyle(markerPath).fill : '',
      markerWidth: marker?.getAttribute('markerWidth') || '',
      markerHeight: marker?.getAttribute('markerHeight') || '',
    };
  });
}

function assertReadable(edge, label) {
  assert.equal(edge.stroke, 'rgb(82, 115, 140)', `${label} stroke`);
  assert(edge.strokeWidth >= 2 && edge.strokeWidth <= 3, `${label} width: ${edge.strokeWidth}`);
  assert(['', 'none'].includes(edge.strokeDasharray), `${label} must be solid: ${edge.strokeDasharray}`);
  assert.equal(edge.markerColor, edge.stroke, `${label} arrow colour`);
  assert(Number(edge.markerWidth) >= 18 && Number(edge.markerHeight) >= 18, `${label} arrow size`);
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const executablePath = process.env.UI_BROWSER_PATH || (fs.existsSync(macChrome) ? macChrome : undefined);
  const browser = await chromium.launch({ executablePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => { errors.push(error.message); console.log('PAGE_ERROR', error.message); });
  page.on('console', message => { if (message.type() === 'error') console.log('CONSOLE_ERROR', message.text()); });
  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, route => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('**/favicon.ico', route => route.fulfill({ status: 204, body: '' }));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const pathname = url.pathname.replace('/api', '');
    let data = {};
    if (pathname === '/runs') data = [run];
    else if (pathname.endsWith('/events/history')) data = [];
    else if (/\/events$/.test(pathname)) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': visual test\n\n' });
    else if (pathname.endsWith('/artifacts')) data = artifacts;
    else if (pathname.endsWith('/tasks')) data = tasks;
    else if (pathname.endsWith('/budget')) data = { used: 0, limit: 1500000 };
    else if (pathname === `/runs/${runId}`) data = run;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });

  await page.goto(`${baseUrl}/workstation/${runId}`);
  await page.locator('.react-flow__edge[data-id="e-S-IDEA-S-DISC"] .react-flow__edge-path').waitFor({ state: 'attached' });
  await page.locator('.react-flow__edge[data-id="e-T-01-T-02"] .react-flow__edge-path').waitFor({ state: 'attached' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(out, 'stage-flow.png') });

  const stageEdge = await edgeMetrics(page, 'e-S-IDEA-S-DISC');
  const taskEdge = await edgeMetrics(page, 'e-T-01-T-02');
  if (shouldAssert) {
    assertReadable(stageEdge, 'STAGE-0 → STAGE-1..3');
    assertReadable(taskEdge, 'T-01 → T-02');
    const layout = await page.locator('.ws').evaluate(ws => {
      const rows = Array.from(ws.querySelectorAll('.ws-left .phase-items .row'));
      const phase = ws.querySelector('.ws-left .phase');
      const group = ws.querySelector('.flow-group');
      const node = ws.querySelector('.react-flow__node[data-id="S-DISC"] .flow-node');
      const subtitle = ws.querySelector('.react-flow__node[data-id="S-IDEA"] .sub');
      const left = ws.querySelector('.ws-left');
      return {
        topbarHeight: ws.querySelector('.topbar').getBoundingClientRect().height,
        duplicatedMeta: ws.querySelectorAll('.ws-left .phase-items .row-meta').length,
        maxRowHeight: Math.max(...rows.map(row => row.getBoundingClientRect().height)),
        phaseBackground: getComputedStyle(phase).backgroundColor,
        groupShadow: getComputedStyle(group).boxShadow,
        nodeBorderWidth: getComputedStyle(node).borderTopWidth,
        defaultSubtitleVisibility: getComputedStyle(subtitle).visibility,
        selectedNodeHeight: node.offsetHeight,
        leftOverflow: left.scrollWidth - left.clientWidth,
      };
    });
    assert(layout.topbarHeight <= 60, `quiet topbar height: ${layout.topbarHeight}`);
    assert.equal(layout.duplicatedMeta, 0, 'compact rows omit duplicate raw-state metadata');
    assert(layout.maxRowHeight <= 32, `compact row height: ${layout.maxRowHeight}`);
    assert.equal(layout.phaseBackground, 'rgba(0, 0, 0, 0)');
    assert.equal(layout.groupShadow, 'none');
    assert.equal(layout.nodeBorderWidth, '1px');
    assert.equal(layout.defaultSubtitleVisibility, 'hidden');
    assert(layout.leftOverflow <= 1, `left panel overflow: ${layout.leftOverflow}`);
    await page.locator('.react-flow__node[data-id="S-DISC"]').click();
    await page.waitForTimeout(100);
    assert.equal(
      await page.locator('.react-flow__node[data-id="S-DISC"] .flow-node').evaluate(node => node.offsetHeight),
      layout.selectedNodeHeight,
      'selected subtitle must not resize the node',
    );
    const incoming = await edgeMetrics(page, 'e-S-IDEA-S-DISC');
    const outgoing = await edgeMetrics(page, 'e-S-DISC-S-SPEC');
    const unrelated = await edgeMetrics(page, 'e-T-01-T-02');
    assert(incoming.className.includes('flow-edge--connected'), 'incoming edge highlighted');
    assert(outgoing.className.includes('flow-edge--connected'), 'outgoing edge highlighted');
    assert.equal(incoming.stroke, 'rgb(0, 102, 250)');
    assert.equal(incoming.strokeWidth, 3);
    assert(unrelated.className.includes('flow-edge--dimmed'), 'unrelated edge dimmed');
    assert.equal(unrelated.opacity, 0.18);
    await page.screenshot({ path: path.join(out, 'stage-flow-selected.png') });

    await page.locator('.react-flow__node[data-id="S-SPEC"]').hover();
    await page.waitForTimeout(100);
    const hovered = await edgeMetrics(page, 'e-S-DISC-S-SPEC');
    assert(hovered.className.includes('flow-edge--connected'), 'hover highlights predecessor edge');
    console.log('PASS compact rows, quiet topbar, light graph surfaces, stable node dimensions, no left-panel overflow');
    console.log('PASS stage edge stroke/arrow, selected predecessor/successor highlighting, unrelated-edge dimming, hover highlighting');
  }

  await page.goto(`${baseUrl}/runs/${runId}/tasks`);
  await page.locator('.react-flow__edge[data-id="T-01-T-02"] .react-flow__edge-path').waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(out, 'task-dependencies.png') });
  if (shouldAssert) {
    assertReadable(await edgeMetrics(page, 'T-01-T-02'), 'task dependency graph T-01 → T-02');
    await page.locator('.react-flow__node[data-id="T-02"]').click();
    await page.waitForTimeout(100);
    const selected = await edgeMetrics(page, 'T-01-T-02');
    assert(selected.className.includes('flow-edge--connected'), 'task dependency selected highlight');
    assert.equal(selected.stroke, 'rgb(0, 102, 250)');
    console.log('PASS task dependency shared edge style and selected highlighting');
  }
  assert.deepEqual(errors, []);
  console.log(`PASS no browser runtime errors; screenshots: ${out}`);
  await browser.close();
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
