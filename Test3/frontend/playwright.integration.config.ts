import { defineConfig } from '@playwright/test';
import config from './playwright.config';

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: '**/integration/*.pw.ts',
  timeout: 60000,
  outputDir: 'test-results/integration',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/integration', open: 'never' }]],
  webServer: [
    { command: 'python e2e/scripted-server.py', url: 'http://127.0.0.1:8765/api/health', reuseExistingServer: false, timeout: 60000 },
    { command: 'npm run dev -- --host 127.0.0.1 --strictPort', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
});
