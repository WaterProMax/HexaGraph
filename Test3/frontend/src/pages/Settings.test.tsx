import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const slots = { flagship: { model: "qwen-max" }, coder: { model: "qwen-coder" } };

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/settings"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function stubFetch(probe: () => Response) {
  const calls: Array<{ url: string; method: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method || "GET" });
      if (url === "/api/config/models") {
        return new Response(JSON.stringify({ slots }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/runs") {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/config/models/test") return probe();
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Settings page", () => {
  it("still renders the existing model slots and probes with POST /api/config/models/test", async () => {
    const calls = stubFetch(
      () => new Response(JSON.stringify({ ok: true, note: "probe-ok" }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    renderSettings();
    expect(await screen.findByRole("heading", { name: "模型槽位" })).toBeTruthy();
    expect(await screen.findByText(/"qwen-max"/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "测试连通" }));
    expect(await screen.findByText(/probe-ok/)).toBeTruthy();
    const probe = calls.find((call) => call.url === "/api/config/models/test");
    expect(probe?.method).toBe("POST");
  });

  it("keeps the page usable when the probe fails", async () => {
    const calls = stubFetch(
      () =>
        new Response(JSON.stringify({ error_category: "validation_error", detail: "no key" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
    );
    renderSettings();
    await screen.findByRole("heading", { name: "模型槽位" });
    fireEvent.click(screen.getByRole("button", { name: "测试连通" }));
    await waitFor(() => expect(calls.some((call) => call.url === "/api/config/models/test")).toBe(true));
    expect(screen.getByRole("heading", { name: "模型槽位" })).toBeTruthy();
  });
});