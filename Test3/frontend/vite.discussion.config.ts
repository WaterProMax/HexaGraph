import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Discussion E2E only: same app as vite.config.ts, but on 5174 and proxied to the
// dedicated scripted backend on 8766 so it never shares ports with other suites.
export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true, proxy: { "/api": "http://127.0.0.1:8766" } },
});