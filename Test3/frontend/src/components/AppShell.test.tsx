import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APP_ROUTE_PATHS } from "../App";
import { AppShell, DEFAULT_NAV_ITEMS, REQUIRED_NAV_KEYS } from "./AppShell";
import { BOT_AVATAR_STORAGE_KEY, writeAvatarPreset } from "../lib/botAvatar";

function renderShell(navItems = DEFAULT_NAV_ITEMS, currentPath = "/bots") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[currentPath]}>
        <AppShell navItems={navItems} currentPath={currentPath}>
          <div data-testid="shell-content">content</div>
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AppShell navigation", () => {
  it("exposes Bot, Project and Settings by href", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "浏览" });
    expect(within(nav).getByRole("link", { name: "Bot" }).getAttribute("href")).toBe("/bots");
    expect(within(nav).getByRole("link", { name: "项目" }).getAttribute("href")).toBe("/projects");
    expect(within(nav).getByRole("link", { name: "模型槽位" }).getAttribute("href")).toBe("/settings");
    for (const key of REQUIRED_NAV_KEYS) {
      expect(DEFAULT_NAV_ITEMS.some((item) => item.key === key)).toBe(true);
    }
  });

  it("accepts custom navigation beyond the three required entries", () => {
    renderShell([...DEFAULT_NAV_ITEMS, { key: "inbox", label: "收件箱", to: "/inbox" }], "/inbox");
    const nav = screen.getByRole("navigation", { name: "浏览" });
    expect(within(nav).getByRole("link", { name: "Bot" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "项目" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "模型槽位" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "收件箱" }).getAttribute("href")).toBe("/inbox");
  });

  it("keeps the collapsible desktop shell", () => {
    renderShell();
    const toggle = screen.getByRole("button", { name: "收起导航" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "展开导航" }).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("route table", () => {
  it("has no top-level /models, /skills, Market or Cron routes", () => {
    const paths = [...APP_ROUTE_PATHS] as string[];
    expect(paths).not.toContain("/models");
    expect(paths).not.toContain("/skills");
    expect(paths.some((p) => p.startsWith("/models"))).toBe(false);
    expect(paths.some((p) => p.startsWith("/skills"))).toBe(false);
    expect(paths).toEqual(expect.arrayContaining(["/bots", "/projects", "/settings"]));
  });

  it("keeps the retired landing routes", () => {
    const paths = [...APP_ROUTE_PATHS] as string[];
    expect(paths).toContain("/workstation/static-classroom");
    expect(paths).toContain("/deepseek/:id?");
  });
});
describe("assistant list in the shell", () => {
  const botItems = [
    { bot_id: "bot-1", display_name: "Leader A", role_template: "leader", status: "active" },
    { bot_id: "bot-2", display_name: "周明", role_template: "pm", status: "archived" },
  ];

  function stubBotList(items: unknown[]) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/bots") {
          return new Response(JSON.stringify({ items }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
  }

  it("lists bots with avatar rows and a new-bot link", async () => {
    stubBotList(botItems);
    renderShell();
    const list = await screen.findByTestId("sidebar-bot-list");
    const row = await screen.findByRole("link", { name: /Leader A/ });
    expect(row.getAttribute("href")).toBe("/bots/bot-1");
    expect(list.textContent).toContain("leader");
    expect(screen.getByTestId("sidebar-new-bot").getAttribute("href")).toBe("/bots/new");
  });

  it("shows a compact avatar rail when collapsed", async () => {
    stubBotList(botItems);
    renderShell();
    await screen.findByRole("link", { name: /Leader A/ });
    fireEvent.click(screen.getByRole("button", { name: "收起导航" }));
    const rail = await screen.findByTestId("sidebar-bot-rail");
    expect(within(rail).getByRole("link", { name: "Leader A · leader" }).getAttribute("href")).toBe("/bots/bot-1");
    expect(within(rail).getByRole("link", { name: "周明 · pm" })).toBeTruthy();
    // Browse links survive the collapse.
    const nav = screen.getByRole("navigation", { name: "浏览" });
    expect(within(nav).getByRole("link", { name: "Bot" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "项目" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "模型槽位" })).toBeTruthy();
  });

  it("refreshes an avatar when the picker writes a preset", async () => {
    stubBotList(botItems);
    renderShell();
    const row = await screen.findByRole("link", { name: /Leader A/ });
    expect(row.querySelector("[data-testid='bot-avatar']")?.textContent).toBe("LA");
    writeAvatarPreset("bot-1", { emoji: "🦊" });
    await vi.waitFor(() => {
      expect(
        screen.getByRole("link", { name: /Leader A/ }).querySelector("[data-testid='bot-avatar']")?.textContent,
      ).toBe("🦊");
    });
    window.localStorage.removeItem(BOT_AVATAR_STORAGE_KEY);
  });

  it("shows the sidebar empty hint without using the page-level testid", async () => {
    stubBotList([]);
    renderShell();
    expect(await screen.findByTestId("sidebar-bots-empty")).toBeTruthy();
    expect(screen.queryByTestId("bots-empty")).toBeNull();
  });
});
