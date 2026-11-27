import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APP_ROUTE_PATHS } from "../App";
import { AppShell, DEFAULT_NAV_ITEMS, REQUIRED_NAV_KEYS } from "./AppShell";
import { BOT_AVATAR_STORAGE_KEY, readAvatarPresets, writeAvatarPreset } from "../lib/botAvatar";

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
  window.localStorage.clear();
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
        const body = String(input).startsWith("/api/projects") ? [{ id: "p1", name: "Alpha" }] : [];
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

describe("project archive menu", () => {
  it("archives from the right-click menu and hides the project", async () => {
    let archived = false;
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.startsWith("/api/projects") && method === "GET") {
          return new Response(JSON.stringify([{ id: "p1", name: "Alpha", archived }]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url === "/api/projects/p1/archive") {
          archived = true;
          calls.push("POST /api/projects/p1/archive");
          return new Response(JSON.stringify({ id: "p1", name: "Alpha", archived: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    renderShell();

    const projectLink = await screen.findByRole("link", { name: /Alpha/ });
    fireEvent.contextMenu(projectLink, { clientX: 90, clientY: 260 });
    const archiveItem = await screen.findByRole("menuitem", { name: /归档项目/ });
    expect(archiveItem.className).toContain("danger");
    fireEvent.click(archiveItem);

    await waitFor(() => expect(calls).toContain("POST /api/projects/p1/archive"));
    await waitFor(() => expect(screen.queryByRole("link", { name: /Alpha/ })).toBeNull());
    expect(screen.queryByTestId("sidebar-archived-toggle")).toBeNull();
  });
});

describe("bot context menu", () => {
  it("edits the bot icon and archives only after confirmation", async () => {
    const calls: string[] = [];
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url === "/api/bots" && method === "GET") {
          return json({
            items: [{ bot_id: "bot-1", display_name: "Leader A", role_template: "leader", status: "active" }],
          });
        }
        if (url === "/api/bots/bot-1/archive") {
          calls.push("POST /api/bots/bot-1/archive");
          return json({ bot_id: "bot-1", status: "archived" });
        }
        return json([]);
      }),
    );
    renderShell();

    const row = await screen.findByRole("link", { name: /Leader A/ });
    fireEvent.contextMenu(row, { clientX: 120, clientY: 220 });
    const editItem = await screen.findByRole("menuitem", { name: /编辑图标/ });
    const archiveItem = screen.getByRole("menuitem", { name: /归档 Bot/ });
    expect(archiveItem.className).toContain("danger");

    fireEvent.click(editItem);
    const picker = await screen.findByTestId("sidebar-icon-picker");
    fireEvent.click(picker.querySelector('[data-icon="rocket"]') as HTMLButtonElement);
    fireEvent.click(picker.querySelector('[data-color="#ef4444"]') as HTMLButtonElement);
    expect(readAvatarPresets()["bot-1"]).toMatchObject({ icon: "rocket", color: "#ef4444" });
    fireEvent.click(within(picker).getByRole("button", { name: "完成" }));
    expect(screen.queryByTestId("sidebar-icon-picker")).toBeNull();

    fireEvent.contextMenu(await screen.findByRole("link", { name: /Leader A/ }), { clientX: 120, clientY: 220 });
    fireEvent.click(await screen.findByRole("menuitem", { name: /归档 Bot/ }));
    expect(await screen.findByText(/归档后该 Bot 不再参与新运行/)).toBeTruthy();
    expect(calls).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
    await waitFor(() => expect(calls).toContain("POST /api/bots/bot-1/archive"));
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
    expect(screen.queryByText("周明")).toBeNull();
    expect(screen.getByTestId("sidebar-new-bot").getAttribute("href")).toBe("/bots/new");
    expect(screen.getByTestId("sidebar-manage-bots").getAttribute("href")).toBe("/bots");
  });

  it("shows a compact avatar rail when collapsed", async () => {
    stubBotList(botItems);
    renderShell();
    await screen.findByRole("link", { name: /Leader A/ });
    fireEvent.click(screen.getByRole("button", { name: "收起导航" }));
    const rail = await screen.findByTestId("sidebar-bot-rail");
    expect(within(rail).getByRole("link", { name: "Leader A · Leader" }).getAttribute("href")).toBe("/bots/bot-1/chat");
    expect(within(rail).queryByRole("link", { name: "周明 · 产品经理" })).toBeNull();
    expect(within(rail).queryByRole("link", { name: "Bot 管理" })).toBeNull();
    expect(within(rail).queryByRole("link", { name: "新建 Bot" })).toBeNull();
    const projects = screen.getByTestId("sidebar-project-list");
    expect(within(projects).queryByTestId("sidebar-new-project")).toBeNull();
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
