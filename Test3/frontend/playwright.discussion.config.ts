import { defineConfig } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

/**
 * Real frontend + real offline backend for the multi-bot discussion flow.
 * Ports 8766 / 5174 stay clear of the other integration suite (8765 / 5173).
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/integration/discussion-flow.pw.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90000,
  expect: { timeout: 15000 },
  outputDir: 'test-results/discussion',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/discussion', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    browserName: 'chromium',
    // 本机默认用系统 Edge（无需下载 Playwright 自带 Chromium）；其它机器可用
    // PLAYWRIGHT_CHANNEL 覆盖，或设为空串回退到 Playwright 自带浏览器。
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'msedge',
    viewport: { width: 1440, height: 1000 },
    trace: 'on',
    screenshot: 'on',
  },
  webServer: [
    {
      // uv 用后端项目环境运行脚本，避免依赖裸 python（PATH 上的系统 Python 往往没有后端依赖）。
      command: 'uv run --project ../backend python e2e/discussion-server.py',
      url: 'http://127.0.0.1:8766/api/health',
      reuseExistingServer: process.env.HEXAGRAPH_E2E_EXTERNAL_BACKEND === '1',
      timeout: 60000,
    },
    {
      command: 'npm run dev -- --config vite.discussion.config.ts --host 127.0.0.1 --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
