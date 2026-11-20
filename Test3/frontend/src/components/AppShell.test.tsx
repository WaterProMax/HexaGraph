import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APP_ROUTE_PATHS } from "../App";
import { AppShell, DEFAULT_NAV_ITEMS, REQUIRED_NAV_KEYS } from "./AppShell";

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