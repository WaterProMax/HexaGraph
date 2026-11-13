import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.pw.ts',
  testIgnore: '**/integration/**',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5173', browserName: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'on', screenshot: 'on' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --strictPort', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
});
