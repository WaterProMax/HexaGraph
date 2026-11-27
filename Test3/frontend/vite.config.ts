import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The E2E harness may need to avoid ports already taken by a local dev stack
// (`playwright.integration.config.ts` passes these through). Defaults are the
// documented 5173 → 8765 pair, so a normal `npm run dev` is unchanged.
declare const process: { env: Record<string, string | undefined> };
const apiTarget = process.env.TEST3_E2E_API_TARGET || "http://127.0.0.1:8765";
const webPort = Number(process.env.TEST3_E2E_WEB_PORT || 5173);

export default defineConfig({
  plugins: [react()],
  server: { port: webPort, proxy: { "/api": apiTarget } },
  test: { environment: "jsdom" },
});