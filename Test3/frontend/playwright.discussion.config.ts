import { defineConfig } from '@playwright/test';

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
  outputDir: 'test-results/discussion',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/discussion', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    trace: 'on',
    screenshot: 'on',
  },
  webServer: [
    {
      command: 'python e2e/discussion-server.py',
      url: 'http://127.0.0.1:8766/api/health',
      reuseExistingServer: false,
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