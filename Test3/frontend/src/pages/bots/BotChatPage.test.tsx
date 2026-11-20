import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BotChatPage from "./BotChatPage";

const bot = {
  bot_id: "bot-1",
  display_name: "Water",
  role_template: "coder",
  provider_ref: "dashscope",
  model: "qwen3.8-max-0902",
  slot: "flagship",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [],
  token_budget: 40000,
  status: "active",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderChat() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/bots/bot-1/chat"]}>
        <Routes>
          <Route path="/bots/:id/chat" element={<BotChatPage />} />
          <Route
            path="/bots/:id"
            element={<div data-testid="bot-config-page" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Call = { url: string; body?: any };

function stubApi(
  chat: (body: any) => Response | Promise<Response>,
  botBody: unknown = bot,
  botStatus = 200,
) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, body });
      if (url === "/api/bots/bot-1") return json(botBody, botStatus);
      if (url === "/api/bots/bot-1/chat") return chat(body);
      return json({});
    }),
  );
  return calls;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BotChatPage", () => {
  it("sends the whole history and shows the reply", async () => {
    const calls = stubApi(() =>
      json({ reply: "你好，我是 Water", model: "m" }),
    );
    renderChat();
    const input = await screen.findByLabelText("消息");
    fireEvent.change(input, { target: { value: "你好" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("你好，我是 Water")).toBeTruthy();
    const chat = calls.find((c) => c.url === "/api/bots/bot-1/chat");
    expect(chat?.body).toEqual({
      messages: [{ role: "user", content: "你好" }],
    });

    fireEvent.change(input, { target: { value: "再说一句" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("/chat"))).toHaveLength(2),
    );
    expect(
      calls.filter((c) => c.url.endsWith("/chat"))[1].body.messages,
    ).toHaveLength(3);
  });

  it("renders assistant replies as markdown and user messages as plain text", async () => {
    stubApi(() => json({ reply: "**先写测试**\n\n- 一\n- 二", model: "m" }));
    renderChat();
    fireEvent.change(await screen.findByLabelText("消息"), {
      target: { value: "**不渲染**" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect((await screen.findByText("先写测试")).tagName).toBe("STRONG");
    expect(
      document.querySelectorAll(".bot-chat-row.assistant li"),
    ).toHaveLength(2);
    expect(screen.getByText("**不渲染**")).toBeTruthy();
  });

  it("keeps the conversation across reloads and can clear it", async () => {
    stubApi(() => json({ reply: "收到", model: "m" }));
    const first = renderChat();
    fireEvent.change(await screen.findByLabelText("消息"), {
      target: { value: "记住我" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("收到");
    first.unmount();

    renderChat();
    expect(await screen.findByText("记住我")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "清空对话" }));
    expect(screen.queryByText("记住我")).toBeNull();
    expect(window.localStorage.getItem("hexagraph.botChat.v1:bot-1")).toBe(
      "[]",
    );
  });

  it("puts the message back and shows the error when the model fails", async () => {
    stubApi(() =>
      json({ error_category: "auth", detail: "API 密钥无效" }, 400),
    );
    renderChat();
    const input = (await screen.findByLabelText("消息")) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "你好" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "API 密钥无效",
    );
    expect(input.value).toBe("你好");
    expect(screen.queryByTestId("bot-chat-pending")).toBeNull();
    expect(document.querySelectorAll(".bot-chat-bubble")).toHaveLength(0);
  });

  it("links to the bot's configuration", async () => {
    stubApi(() => json({ reply: "x", model: "m" }));
    renderChat();
    const link = await screen.findByTestId("bot-chat-config");
    expect(link.getAttribute("href")).toBe("/bots/bot-1");
  });

  it("disables the composer for archived bots", async () => {
    stubApi(() => json({}), { ...bot, status: "archived" });
    renderChat();
    expect(
      ((await screen.findByLabelText("消息")) as HTMLTextAreaElement).disabled,
    ).toBe(true);
  });

  it("shows a not-found message for an unknown bot", async () => {
    stubApi(
      () => json({}),
      { error_category: "bot_not_found", detail: "no" },
      404,
    );
    renderChat();
    expect((await screen.findByTestId("bot-chat-error")).textContent).toContain(
      "找不到这个 Bot",
    );
  });
});
