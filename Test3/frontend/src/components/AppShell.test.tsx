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
  it("has no separate browse group: Bot and project sections replace it", () => {
    renderShell();
    expect(screen.queryByRole("navigation", { name: "浏览" })).toBeNull();
    expect(screen.queryByRole("link", { name: "工作台" })).toBeNull();
    expect(screen.queryByRole("link", { name: "模型槽位" })).toBeNull();
    expect(screen.getByTestId("sidebar-bot-list").textContent).toContain("Bot");
    expect(screen.queryByText("助手")).toBeNull();
    expect(REQUIRED_NAV_KEYS).toHaveLength(0);
  });

  it("still renders custom navigation when provided", () => {
    renderShell([...DEFAULT_NAV_ITEMS, { key: "inbox", label: "收件箱", to: "/inbox" }], "/inbox");
    const nav = screen.getByRole("navigation", { name: "浏览" });
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
    expect(paths).not.toContain("/settings");
    expect(paths).not.toContain("/models");
    expect(paths).not.toContain("/skills");
    expect(paths.some((p) => p.startsWith("/models"))).toBe(false);
    expect(paths.some((p) => p.startsWith("/skills"))).toBe(false);
    expect(paths).toEqual(expect.arrayContaining(["/bots", "/projects"]));
  });

  it("keeps the retired landing routes", () => {
    const paths = [...APP_ROUTE_PATHS] as string[];
    expect(paths).toContain("/workstation/static-classroom");
    expect(paths).toContain("/deepseek/:id?");
  });
});
describe("project section in the shell", () => {
  it("lists projects under their own heading with a create link", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const body = String(input) === "/api/projects" ? [{ id: "p1", name: "Alpha" }] : [];
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    renderShell();
    const section = await screen.findByTestId("sidebar-project-list");
    expect(within(section).getByTestId("sidebar-new-project").getAttribute("href")).toBe("/projects/new");
    expect((await within(section).findByRole("link", { name: /Alpha/ })).getAttribute("href")).toBe("/projects/p1");
    expect(screen.queryByText("最近运行")).toBeNull();
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
    expect(row.getAttribute("href")).toBe("/bots/bot-1/chat");
    expect(list.textContent).toContain("leader");
    expect(screen.getByTestId("sidebar-new-bot").getAttribute("href")).toBe("/bots/new");
    expect(screen.getByTestId("sidebar-manage-bots").getAttribute("href")).toBe("/bots");
  });

  it("shows a compact avatar rail when collapsed", async () => {
    stubBotList(botItems);
    renderShell();
    await screen.findByRole("link", { name: /Leader A/ });
    fireEvent.click(screen.getByRole("button", { name: "收起导航" }));
    const rail = await screen.findByTestId("sidebar-bot-rail");
    expect(within(rail).getByRole("link", { name: "Leader A · leader" }).getAttribute("href")).toBe("/bots/bot-1/chat");
    expect(within(rail).getByRole("link", { name: "周明 · pm" })).toBeTruthy();
    expect(within(rail).getByRole("link", { name: "Bot 管理" }).getAttribute("href")).toBe("/bots");
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
