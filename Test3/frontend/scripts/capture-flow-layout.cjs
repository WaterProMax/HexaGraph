// Before/after screenshots for the workstation split panel and layered flow graph.
// HTTP is mocked in the browser; no backend, model API or .env is touched.
//
//   npm run dev -- --host 127.0.0.1 --port 5181 --strictPort
//   UI_BASE_URL=http://127.0.0.1:5181 FLOW_LAYOUT_PHASE=before node scripts/capture-flow-layout.cjs
const { chromium } = require(process.env.UI_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');

const baseUrl = process.env.UI_BASE_URL || 'http://127.0.0.1:5181';
const phase = process.env.FLOW_LAYOUT_PHASE || 'after';
const out = path.resolve(
  process.env.UI_SCREENSHOT_DIR || path.join(__dirname, '../../docs/design/screenshots/flow-layout', phase),
);

const { mock } = require('./flow-layout-fixtures.cjs');

async function shot(page, name) {
  await page.waitForTimeout(700);
  const file = path.join(out, `${name}.png`);
  await page.screenshot({ path: file });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`${file}  page-horizontal-overflow=${overflow}px`);
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const executablePath = process.env.UI_BROWSER_PATH || (fs.existsSync(macChrome) ? macChrome : undefined);
  const browser = await chromium.launch({ executablePath, headless: true });
  const sizes = [[1280, 800], [1440, 900], [1920, 1080]];
  for (const [w, h] of sizes) {
    const context = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    await mock(page);
    await page.goto(`${baseUrl}/workstation/layout-dag`);
    await page.locator('.react-flow__node').first().waitFor();
    await shot(page, `dag-${w}x${h}`);
    if (w === 1440) {
      await page.goto(`${baseUrl}/workstation/layout-design-gate`);
      await page.locator('.react-flow__node').first().waitFor();
      await shot(page, `design-gate-${w}x${h}`);
      await page.goto(`${baseUrl}/workstation/layout-needs-input`);
      await page.getByTestId('design-spec-preview').waitFor();
      await shot(page, `needs-input-${w}x${h}`);
      if (phase === 'after') {
        await page.getByRole('button', { name: /展开全部/ }).first().click();
        await shot(page, `needs-input-expanded-${w}x${h}`);
        await page.goto(`${baseUrl}/workstation/layout-dag`);
        await page.locator('.react-flow__node').first().waitFor();
        await page.getByRole('button', { name: '收起信息栏' }).click();
        await shot(page, `dag-panel-collapsed-${w}x${h}`);
        await page.getByRole('button', { name: '展开信息栏' }).click();
        const splitter = page.getByRole('separator', { name: '调整信息栏宽度' });
        const box = await splitter.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + 200);
        await page.mouse.down();
        await page.mouse.move(box.x + 180, box.y + 200, { steps: 8 });
        await page.mouse.up();
        await shot(page, `dag-panel-widened-${w}x${h}`);
        await splitter.focus();
        await page.keyboard.press('Enter');
      }
    }
    await context.close();
  }
  for (const [w, h] of [[1000, 760], [720, 760]]) {
    const context = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    await mock(page);
    await page.goto(`${baseUrl}/workstation/layout-dag`);
    await page.locator('.react-flow__node').first().waitFor();
    await shot(page, `narrow-${w}x${h}`);
    if (phase === 'after' && w < 1000) {
      await page.getByRole('button', { name: /信息栏/ }).first().click();
      await shot(page, `narrow-drawer-open-${w}x${h}`);
    }
    await context.close();
  }
  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    await mock(page);
    await page.goto(`${baseUrl}/workstation/static-classroom`);
    await page.getByTestId('static-classroom-demo').waitFor();
    await shot(page, 'static-classroom-1440x900');
    await context.close();
  }
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
