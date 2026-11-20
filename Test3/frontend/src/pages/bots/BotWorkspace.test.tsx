import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BotInstance } from "../../api/types";
import { BOT_AVATAR_STORAGE_KEY } from "../../lib/botAvatar";
import { BotWorkspace } from "./BotWorkspace";

const bot: BotInstance = {
  bot_id: "bot-1",
  display_name: "Leader A",
  role_template: "leader",
  provider_ref: "dashscope",
  model: "qwen-max",
  slot: "flagship",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [],
  token_budget: 40000,
  status: "active",
};

const providers = [{ slot: "flagship", model: "qwen-max" }];

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function renderWorkspace() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BotWorkspace
          bot={bot}
          providerOptions={providers}
                    loadState="ready"
          onSave={vi.fn()}
          onArchive={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("BotWorkspace", () => {
  it("renders the bot header and config tab with the existing form", () => {
    renderWorkspace();
    expect(screen.getByTestId("bot-workspace")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Leader A" })).toBeTruthy();
    expect(screen.getByTestId("bot-panel-config")).toBeTruthy();
    expect(screen.getByTestId("bot-form")).toBeTruthy();
  });

  it("loads private memory with the bot as X-Bot-Id", async () => {
    const calls: Array<{ url: string; headers: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), headers: init?.headers });
        return json({ items: [{ mem_id: "m1", owner_bot_id: "bot-1", project_id: null, visibility: "private", version: 1, status: "pending", sources: [], body: {}, title: "偏好", run_id: null }] });
      }),
    );
    renderWorkspace();
    fireEvent.click(screen.getByTestId("bot-tab-memory"));
    expect(await screen.findByText("偏好")).toBeTruthy();
    const call = calls.find((item) => item.url.startsWith("/api/memory/records"));
    expect(call?.url).toBe("/api/memory/records?owner_bot_id=bot-1&visibility=private");
    expect((call?.headers as Record<string, string>)["X-Bot-Id"]).toBe("bot-1");
  });

  it("shows the forbidden state for memory 403", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ error_category: "memory_forbidden", detail: "no" }, 403)));
    renderWorkspace();
    fireEvent.click(screen.getByTestId("bot-tab-memory"));
    expect(await screen.findByTestId("bot-memory-forbidden")).toBeTruthy();
  });

  it("applies a picked emoji to the header avatar and storage", async () => {
    renderWorkspace();
    fireEvent.click(screen.getByTestId("bot-avatar-change"));
    fireEvent.click(await screen.findByRole("button", { name: "头像 🦊" }));
    await waitFor(() => expect(screen.getAllByTestId("bot-avatar")[0].textContent).toBe("🦊"));
    const stored = JSON.parse(window.localStorage.getItem(BOT_AVATAR_STORAGE_KEY) || "{}");
    expect(stored["bot-1"].emoji).toBe("🦊");
  });
});