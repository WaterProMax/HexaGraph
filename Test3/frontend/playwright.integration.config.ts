import { defineConfig } from '@playwright/test';
import config from './playwright.config';

declare const process: { env: Record<string, string | undefined> };

/**
 * Offline scripted suite. Ports default to the documented 8765 / 5173 pair; a
 * local dev stack may already own them, so both can be moved together through
 * TEST3_E2E_API_PORT / TEST3_E2E_WEB_PORT without changing any spec.
 */
const API_PORT = process.env.TEST3_E2E_API_PORT || '8765';
const WEB_PORT = process.env.TEST3_E2E_WEB_PORT || '5173';
const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: '**/integration/*.pw.ts',
  timeout: 60000,
  outputDir: 'test-results/integration',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/integration', open: 'never' }]],
  use: { ...config.use, baseURL: WEB_ORIGIN },
  webServer: [
    {
      command: `python e2e/scripted-server.py`,
      url: `${API_ORIGIN}/api/health`,
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        TEST3_E2E_API_PORT: API_PORT,
        TEST3_E2E_WEB_PORT: WEB_PORT,
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --strictPort`,
      url: WEB_ORIGIN,
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        TEST3_E2E_API_TARGET: API_ORIGIN,
        TEST3_E2E_WEB_PORT: WEB_PORT,
      },
    },
  ],
});