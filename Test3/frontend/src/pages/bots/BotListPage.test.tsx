import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import BotListPage from "./BotListPage";

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

function stubFetch(handler: Handler) {
  const calls: Array<{ url: string; method: string; body: any }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method || "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
      return handler(url, init);
    }),
  );
  return calls;
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

const skillList = {
  items: [{ skill_id: "review", version: "1.0.0", description_md: "", allowed_tool_refs: [] }],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/bots" element={<BotListPage />} />
        <Route path="/bots/new" element={<BotListPage mode="create" />} />
        <Route path="/bots/:id" element={<BotListPage mode="edit" />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BotListPage states", () => {
  it("shows the loading state while the list is pending", async () => {
    stubFetch((url) => {
      if (url === "/api/bots") return new Promise<Response>(() => undefined);
      return json({ items: [] });
    });
    renderAt("/bots");
    expect(screen.getByTestId("bots-loading")).toBeTruthy();
  });

  it("shows the empty state for an empty list", async () => {
    stubFetch((url) => (url === "/api/bots" ? json({ items: [] }) : json({ items: [], slots: {} })));
    renderAt("/bots");
    expect(await screen.findByTestId("bots-empty")).toBeTruthy();
    expect(screen.getByTestId("bots-empty").textContent).toContain("还没有 Bot");
  });

  it("shows the error state with the network message", async () => {
    stubFetch((url) => {
      if (url === "/api/bots") return Promise.reject(new Error("network down"));
      return json({ items: [] });
    });
    renderAt("/bots");
    const error = await screen.findByTestId("bots-error");
    expect(error.textContent).toContain("network down");
  });

  it("shows the forbidden state on 403", async () => {
    stubFetch((url) => {
      if (url === "/api/bots") return json({ error_category: "forbidden", detail: "no" }, 403);
      return json({ items: [] });
    });
    renderAt("/bots");
    expect(await screen.findByTestId("bots-forbidden")).toBeTruthy();
  });

  it("renders the list when bots exist", async () => {
    stubFetch((url) => {
      if (url === "/api/bots")
        return json({
          items: [
            {
              bot_id: "bot-1",
              display_name: "Leader A",
              role_template: "coder",
              provider_ref: "dashscope",
              model: "m1",
              slot: "coder",
              secret_ref: "DASHSCOPE_API_KEY",
              tool_policy: [],
              skill_bindings: [{ skill_id: "review", pinned_version: "1.0.0" }],
              token_budget: 40000,
              status: "active",
            },
          ],
        });
      if (url === "/api/skills") return json(skillList);
      return json({ slots: { coder: { model: "m1" } } });
    });
    renderAt("/bots");
    expect(await screen.findByRole("link", { name: /Leader A/ })).toBeTruthy();
  });
});

describe("BotListPage create flow", () => {
  it("posts the real BotCreate body to /api/bots", async () => {
    const calls = stubFetch((url, init) => {
      if (url === "/api/bots" && init?.method === "POST")
        return json({ bot_id: "bot-new", display_name: "Leader A", status: "active" }, 201);
      if (url === "/api/bots") return json({ items: [] });
      if (url === "/api/skills") return json(skillList);
      return json({ slots: { coder: { model: "m1" } } });
    });
    renderAt("/bots/new");
    await screen.findByTestId("bot-form");
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "Leader A" } });
    fireEvent.change(screen.getByLabelText("模型槽位"), { target: { value: "coder" } });
    await screen.findByRole("option", { name: "review@1.0.0" });
    fireEvent.change(screen.getByLabelText("Skill 版本"), { target: { value: "review@1.0.0" } });
    fireEvent.click(screen.getByRole("button", { name: "添加绑定" }));
    fireEvent.click(screen.getByRole("button", { name: "创建 Bot" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const post = calls.find((call) => call.method === "POST")!;
    expect(post.url).toBe("/api/bots");
    expect(post.body.display_name).toBe("Leader A");
    expect(post.body.model).toBe("m1");
    expect(post.body.skill_bindings).toEqual([{ skill_id: "review", pinned_version: "1.0.0" }]);
    expect(post.body).not.toHaveProperty("bot_id");
  });
});
describe("Bot workspace route", () => {
  it("opens the tabbed workspace on /bots/:id", async () => {
    stubFetch((url) => {
      if (url === "/api/bots/bot-1")
        return json({
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
        });
      if (url === "/api/bots") return json({ items: [] });
      if (url === "/api/skills") return json({ items: [] });
      return json({ slots: { flagship: { model: "qwen-max" } } });
    });
    renderAt("/bots/bot-1");
    expect(await screen.findByTestId("bot-workspace")).toBeTruthy();
    expect(screen.getByTestId("bot-tab-config")).toBeTruthy();
    expect(screen.getByTestId("bot-tab-memory")).toBeTruthy();
    expect(screen.getByTestId("bot-tab-projects")).toBeTruthy();
    expect(screen.getByTestId("bot-form")).toBeTruthy();
  });
});
