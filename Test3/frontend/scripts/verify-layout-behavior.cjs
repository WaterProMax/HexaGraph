// Real-browser behaviour checks for the workstation split panel and layered flow graph.
// HTTP is mocked in the browser (scripts/flow-layout-fixtures.cjs); no backend, model API or .env is used.
//
//   npm run dev -- --host 127.0.0.1 --port 5181 --strictPort
//   UI_BASE_URL=http://127.0.0.1:5181 node scripts/verify-layout-behavior.cjs
const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const { mock, dagCards } = require('./flow-layout-fixtures.cjs');

const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5181';
const LAYOUT_KEY = 'hexagraph.workstation.layout.v1';

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  [${detail}]` : ''}`);
}

async function open(browser, size, route, { setup } = {}) {
  const context = await browser.newContext({ viewport: { width: size[0], height: size[1] }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await mock(page);
  if (setup) await setup(page);
  await page.goto(`${baseUrl}${route}`);
  return { context, page, errors };
}

const transformOf = (page) => page.locator('.react-flow__viewport').evaluate((el) => el.style.transform);
const overflowOf = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const leftWidth = (page) => page.locator('.ws-left').evaluate((el) => Math.round(el.getBoundingClientRect().width));
const canvasWidth = (page) => page.locator('.ws-canvas, .ws-main, .graph-flow').first().evaluate((el) => Math.round(el.getBoundingClientRect().width));

async function dragSplitter(page, toX) {
  const box = await page.getByRole('separator', { name: '调整信息栏宽度' }).boundingBox();
  const y = box.y + 220;
  await page.mouse.move(box.x + box.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(toX, y, { steps: 10 });
  await page.mouse.up();
}

/** Screen-space geometry of nodes and sampled edge points, read from the DOM. */
async function geometry(page) {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll('.react-flow__node')].map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.getAttribute('data-id'), x: r.left, y: r.top, w: r.width, h: r.height };
    });
    const edges = [...document.querySelectorAll('.react-flow__edge')].map((el) => {
      const path = el.querySelector('path.react-flow__edge-path');
      const m = path.getScreenCTM();
      const total = path.getTotalLength();
      const points = [];
      for (let d = 0; d <= total; d += 3) {
        const p = path.getPointAtLength(d);
        points.push({ x: m.a * p.x + m.c * p.y + m.e, y: m.b * p.x + m.d * p.y + m.f });
      }
      return { id: el.getAttribute('data-id'), points };
    });
    return { nodes, edges };
  });
}

function analyse(geo, dag) {
  const overlaps = [];
  for (let i = 0; i < geo.nodes.length; i += 1) {
    for (let j = i + 1; j < geo.nodes.length; j += 1) {
      const a = geo.nodes[i];
      const b = geo.nodes[j];
      if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps.push(`${a.id}/${b.id}`);
    }
  }
  const crossings = [];
  for (const edge of geo.edges) {
    const m = edge.id.match(/e-(T-\d+)-(T-\d+)/) || edge.id.match(/e-(MOD-\w+)-(MOD-\w+)/);
    const ends = m ? [m[1], m[2]] : [];
    for (const node of geo.nodes) {
      if (ends.includes(node.id)) continue;
      const hit = edge.points.some(
        (p) => p.x > node.x + 2 && p.x < node.x + node.w - 2 && p.y > node.y + 2 && p.y < node.y + node.h - 2,
      );
      if (hit) crossings.push(`${edge.id} x ${node.id}`);
    }
  }
  const expectedEdges = dag.reduce((sum, card) => sum + card.depends_on.length, 0);
  return { overlaps, crossings, expectedEdges };
}

async function main() {
  const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const executablePath = process.env.UI_BROWSER_PATH || (fs.existsSync(macChrome) ? macChrome : undefined);
  const browser = await chromium.launch({ executablePath, headless: true });

  // ---- 20-task DAG at 1440x900: geometry, read-only, viewport memory, splitter ----
  {
    const { context, page, errors } = await open(browser, [1440, 900], '/workstation/layout-dag');
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(900);
    const geo = await geometry(page);
    const { overlaps, crossings, expectedEdges } = analyse(geo, dagCards);
    check('dag: 20 task nodes rendered', geo.nodes.length === 20, `${geo.nodes.length}`);
    check('dag: edges equal real depends_on count (no fake fan-in)', geo.edges.length === expectedEdges, `${geo.edges.length}/${expectedEdges}`);
    check('dag: nodes do not overlap', overlaps.length === 0, overlaps.join(','));
    check('dag: no edge passes through a node', crossings.length === 0, crossings.slice(0, 4).join(','));
    check('dag: no S-PLAN / stage node in the main graph', (await page.locator('.react-flow__node[data-id^="S-"]').count()) === 0);
    check('dag: stage overview shows 7 stages', (await page.locator('[data-testid="stage-overview"] .stage-step').count()) === 7);

    const t0 = await transformOf(page);
    const zoom0 = Number((t0.match(/scale\(([\d.]+)\)/) || [])[1]);
    check('dag: initial zoom stays readable (>= 0.6)', zoom0 >= 0.6, `zoom=${zoom0}`);

    await page.waitForTimeout(100);
    const t1 = await transformOf(page);

    // hover + select + poll + splitter drag keep the viewport
    await page.locator('.react-flow__node').nth(4).hover();
    await page.waitForTimeout(300);
    await page.locator('.react-flow__node').nth(4).click();
    await page.waitForTimeout(3500); // > refetchInterval
    check('dag: selecting a node shows its full title in the dock', (await page.locator('.dock .title').innerText()).includes('超长名称'));
    check('dag: hover/select/poll do not move the viewport', (await transformOf(page)) === t1);

    await dragSplitter(page, 700);
    await page.waitForTimeout(500);
    const wide = await leftWidth(page);
    check('splitter: drag widens the info column within bounds', wide > 320 && wide <= 560, `${wide}px`);
    check('splitter: canvas keeps >= 480px', (await canvasWidth(page)) >= 480, `${await canvasWidth(page)}px`);
    check('dag: splitter drag does not refit the viewport', (await transformOf(page)) === t1, `${t1} -> ${await transformOf(page)}`);

    await dragSplitter(page, 0);
    check('splitter: drag far left clamps at 280', (await leftWidth(page)) === 280, `${await leftWidth(page)}px`);
    await dragSplitter(page, 1430);
    check('splitter: drag far right clamps at 560', (await leftWidth(page)) === 560, `${await leftWidth(page)}px`);

    // user pans -> viewport must then survive everything, including reload-free structure polls
    await page.mouse.move(900, 700);
    await page.mouse.down();
    await page.mouse.move(800, 640, { steps: 6 });
    await page.mouse.up();
    const panned = await transformOf(page);
    check('viewport: pane drag pans the view', panned !== t1);
    await page.waitForTimeout(3500);
    await dragSplitter(page, 500);
    await page.locator('.react-flow__node').nth(2).click();
    await page.waitForTimeout(500);
    check('viewport: user pan survives poll, splitter drag and select', (await transformOf(page)) === panned);
    await page.getByRole('button', { name: '重置视口' }).click();
    await page.waitForTimeout(700);
    check('viewport: 重置视口 refits', (await transformOf(page)) !== panned);

    // persistence + keyboard
    const saved = await page.evaluate((key) => JSON.parse(localStorage.getItem(key) || 'null'), LAYOUT_KEY);
    check('splitter: width saved under hexagraph.workstation.layout.v1', saved && saved.width >= 280 && saved.width <= 560, JSON.stringify(saved));
    check('splitter: retired static classroom key untouched', (await page.evaluate(() => localStorage.getItem('hexagraph.static-classroom-demo.v1'))) === null);
    const before = await leftWidth(page);
    await page.reload();
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(500);
    check('splitter: refresh restores the width', (await leftWidth(page)) === before, `${before} -> ${await leftWidth(page)}`);

    const separator = page.getByRole('separator', { name: '调整信息栏宽度' });
    await separator.focus();
    await page.keyboard.press('Home');
    await page.waitForTimeout(150);
    check('splitter: Home resets to 320px', (await leftWidth(page)) === 320, `${await leftWidth(page)}px`);
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    check('splitter: ArrowRight adds 16px', (await leftWidth(page)) === 336, `${await leftWidth(page)}px`);
    await page.keyboard.press('Shift+ArrowLeft');
    await page.waitForTimeout(150);
    check('splitter: Shift+ArrowLeft removes 64px', (await leftWidth(page)) === 280, `${await leftWidth(page)}px`);
    await separator.dblclick();
    await page.waitForTimeout(150);
    check('splitter: double-click resets', (await leftWidth(page)) === 320, `${await leftWidth(page)}px`);

    // collapse / expand
    await page.getByRole('button', { name: '收起信息栏' }).click();
    await page.waitForTimeout(300);
    check('layout: collapsing hides the info column', (await page.locator('.ws-left').isVisible()) === false);
    await page.getByRole('button', { name: '展开信息栏' }).click();
    await page.waitForTimeout(300);
    check('layout: expanding restores it', (await leftWidth(page)) === 320);
    check('dag: no page-level horizontal scroll', (await overflowOf(page)) <= 0, `${await overflowOf(page)}px`);
    check('dag: no uncaught page errors', errors.length === 0, errors.join(' | '));
    await context.close();
  }

  // ---- read-only graph: pressing and dragging a node pans, never moves the node ----
  {
    const { context, page } = await open(browser, [1440, 900], '/workstation/layout-dag');
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(800);
    const offset = async () => {
      const [a, b] = await page.locator('.react-flow__node').evaluateAll((els) => els.slice(0, 2).map((el) => el.getBoundingClientRect()));
      return { dx: Math.round(b.left - a.left), dy: Math.round(b.top - a.top) };
    };
    const before = await offset();
    const first = await page.locator('.react-flow__node').first().boundingBox();
    await page.mouse.move(first.x + 40, first.y + 30);
    await page.mouse.down();
    await page.mouse.move(first.x + 200, first.y + 160, { steps: 6 });
    await page.mouse.up();
    const after = await offset();
    check('dag: nodes are not draggable (relative positions unchanged)', before.dx === after.dx && before.dy === after.dy, JSON.stringify([before, after]));
    const handles = await page.locator('.react-flow__handle').evaluateAll((els) => els.every((el) => !el.classList.contains('connectable')));
    check('dag: handles are not connectable', handles);
    await context.close();
  }

  // ---- page overflow + node geometry at other sizes ----
  for (const size of [[1280, 800], [1920, 1080]]) {
    const { context, page } = await open(browser, size, '/workstation/layout-dag');
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(800);
    const { overlaps, crossings } = analyse(await geometry(page), dagCards);
    check(`dag ${size.join('x')}: no overlap / no edge through node`, overlaps.length === 0 && crossings.length === 0);
    check(`dag ${size.join('x')}: no horizontal page scroll`, (await overflowOf(page)) <= 0, `${await overflowOf(page)}px`);
    await context.close();
  }

  // ---- narrow viewports: auto-collapsed nav + drawer ----
  for (const size of [[1000, 760], [720, 760]]) {
    const { context, page } = await open(browser, size, '/workstation/layout-dag');
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(600);
    check(`narrow ${size.join('x')}: no horizontal page scroll`, (await overflowOf(page)) <= 0, `${await overflowOf(page)}px`);
    check(`narrow ${size.join('x')}: graph keeps >= 480px`, (await canvasWidth(page)) >= 480, `${await canvasWidth(page)}px`);
    check(`narrow ${size.join('x')}: sidebar auto-collapsed`, (await page.locator('.sidebar, .app-sidebar, aside.sb').first().evaluate((el) => el.getBoundingClientRect().width).catch(() => 0)) < 120);
    const toggle = page.getByRole('button', { name: /信息栏/ }).first();
    const docked = await page.locator('.ws-left').isVisible();
    check(`narrow ${size.join('x')}: ${size[0] >= 900 ? 'info column stays docked when canvas keeps >= 480px' : 'info column hidden until requested'}`, docked === (size[0] >= 900));
    if (docked) {
      await toggle.click();
      await page.waitForTimeout(300);
      check(`narrow ${size.join('x')}: toggle folds the docked column`, (await page.locator('.ws-left').isVisible()) === false);
      await toggle.click();
      await page.waitForTimeout(300);
      check(`narrow ${size.join('x')}: toggle brings it back`, await page.locator('.ws-left').isVisible());
    } else {
      await toggle.click();
      await page.waitForTimeout(300);
      check(`narrow ${size.join('x')}: info column opens as drawer`, await page.locator('.ws-left').isVisible());
      check(`narrow ${size.join('x')}: drawer does not squeeze the graph`, (await canvasWidth(page)) >= 480, `${await canvasWidth(page)}px`);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      check(`narrow ${size.join('x')}: Escape closes the drawer`, (await page.locator('.ws-left').isVisible()) === false);
    }
    await context.close();
  }

  // ---- design gate: module graph, waiting != failure ----
  {
    const { context, page } = await open(browser, [1440, 900], '/workstation/layout-design-gate');
    await page.locator('.react-flow__node').first().waitFor();
    await page.waitForTimeout(500);
    const ids = await page.locator('.react-flow__node').evaluateAll((els) => els.map((el) => el.getAttribute('data-id')));
    check('design gate: 5 module nodes, no PLAN node', ids.length === 5 && ids.every((id) => id.startsWith('MOD-')), ids.join(','));
    check('design gate: only the declared M1->M3 edge', (await page.locator('.react-flow__edge').count()) === 1);
    const tone = await page.getByTestId('run-status-line').getAttribute('class');
    check('design gate: waiting is tone-awaiting, not error', tone.includes('tone-awaiting') && !tone.includes('tone-error'), tone);
    check('design gate: approve / reject actions still present', (await page.getByRole('button', { name: '批准并推进' }).count()) === 1);
    const geo = analyse(await geometry(page), []);
    check('design gate: modules do not overlap', geo.overlaps.length === 0);
    await context.close();
  }

  // ---- needs_input: error visible, missing list 3 + expand, raw text collapsed but editable ----
  {
    const { context, page } = await open(browser, [1440, 900], '/workstation/layout-needs-input');
    await page.getByTestId('design-spec-preview').waitFor();
    await page.waitForTimeout(500);
    check('needs_input: graph area shows an error state, not an empty success', (await page.getByTestId('graph-empty').getAttribute('class')).includes('tone-error'));
    check('needs_input: status line is an error', (await page.getByTestId('run-status-line').getAttribute('class')).includes('tone-error'));
    const hint = page.getByTestId('design-error-hint');
    check('needs_input: shows 3 of 6 missing items', !(await hint.innerText()).includes('未定义候补队列长度') && (await hint.innerText()).includes('未说明预约保留时长'));
    await page.getByRole('button', { name: /共 6 项，展开全部/ }).click();
    check('needs_input: expands to all 6', (await hint.innerText()).includes('缺少离线场景验收条件'));
    const raw = page.getByLabel('设计规格原文');
    check('needs_input: raw text is collapsed after import', (await raw.isVisible()) === false);
    await page.getByRole('button', { name: '去改原文' }).click();
    await page.waitForTimeout(300);
    check('needs_input: 去改原文 opens and focuses the text', (await raw.isVisible()) && (await raw.evaluate((el) => el === document.activeElement)));
    await raw.fill('目标：我改了原文。');
    await page.waitForTimeout(3500);
    check('needs_input: typing survives polling (dirty protection)', (await raw.inputValue()) === '目标：我改了原文。');
    await page.getByText('高级').first().click();
    check('needs_input: full sha256 only under 高级', (await page.getByText('9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d').isVisible()));
    await context.close();
  }

  // ---- retired static classroom route explains itself and never mounts a demo ----
  {
    const { context, page, errors } = await open(browser, [1440, 900], '/workstation/static-classroom');
    await page.getByTestId('retired-feature').waitFor();
    check('retired static classroom: explicit offline notice', (await page.getByTestId('retired-feature').innerText()).includes('已下线'));
    check('retired static classroom: no demo storage key written', (await page.evaluate(() => localStorage.getItem('hexagraph.static-classroom-demo.v1'))) === null);
    check('retired static classroom: no horizontal scroll', (await overflowOf(page)) <= 0);
    check('retired static classroom: no uncaught page errors', errors.length === 0, errors.join(' | '));
    await context.close();
  }

  await browser.close();
  console.log(failures === 0 ? '\nALL BEHAVIOUR CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
