import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Projects from "./Projects";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/new" element={<Projects />} />
          <Route
            path="/projects/:projectId"
            element={<div data-testid="project-page">project page</div>}
          />
          <Route
            path="/bots"
            element={<div data-testid="bots-page">bots</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Projects create dialog", () => {
  it("renders only the create dialog, with no project list", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json([])),
    );
    renderAt("/projects/new");
    expect(screen.getByRole("dialog", { name: "创建项目" })).toBeTruthy();
    expect(screen.queryByText("全部项目")).toBeNull();
    expect(screen.queryByText("打开工作台")).toBeNull();
  });

  it("enables creation when the project name is filled", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json([])),
    );
    renderAt("/projects/new");
    const button = screen.getByRole("button", {
      name: "创建项目",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(
      screen.getByPlaceholderText("例如：自习室空位查询小程序"),
      { target: { value: "座位查询" } },
    );
    expect(button.disabled).toBe(false);
  });

  it("creates the project and opens its workstation, not the run page", async () => {
    const calls: Array<{ url: string; method: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method || "GET" });
        if (url === "/api/projects" && init?.method === "POST")
          return json({ id: "proj-9", name: "座位查询" }, 201);
        return json([]);
      }),
    );
    renderAt("/projects/new");
    fireEvent.change(
      screen.getByPlaceholderText("例如：自习室空位查询小程序"),
      { target: { value: "座位查询" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "创建项目" }));
    expect(await screen.findByTestId("project-page")).toBeTruthy();
    await waitFor(() =>
      expect(calls).toEqual([{ url: "/api/projects", method: "POST" }]),
    );
  });

  it("closes back to bots with the ✕ button and with Escape", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json([])),
    );
    const { unmount } = renderAt("/projects/new");
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.getByTestId("bots-page")).toBeTruthy();
    unmount();
    renderAt("/projects/new");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByTestId("bots-page")).toBeTruthy();
  });
});
