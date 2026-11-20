import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BotFilesPanel } from "./BotFilesPanel";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const file = (id: string, filename: string, chars: number) => ({
  file_id: id,
  filename,
  chars,
  created_at: "2026-11-20T00:00:00Z",
});

type Call = { url: string; method: string; body?: any };

function stubApi(
  handler: (call: Call) => Response | Promise<Response>,
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call: Call = {
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      return handler(call);
    }),
  );
  return calls;
}

const library = {
  items: [file("f1", "spec.md", 1200), file("f2", "notes.txt", 300)],
  used_chars: 1500,
  budget_chars: 29491,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openPanel() {
  fireEvent.click(screen.getByRole("button", { name: "资料文件" }));
  return screen.findByTestId("bot-files-panel");
}

function pick(files: File[]) {
  fireEvent.change(screen.getByTestId("bot-files-input"), {
    target: { files },
  });
}

describe("BotFilesPanel", () => {
  it("loads the library when opened and shows files with usage", async () => {
    const calls = stubApi(() => json(library));
    render(<BotFilesPanel botId="bot-1" />);
    expect(calls).toHaveLength(0);

    const panel = await openPanel();
    expect(await within(panel).findByText("spec.md")).toBeTruthy();
    expect(within(panel).getByText("notes.txt")).toBeTruthy();
    expect(screen.getByTestId("bot-files-usage").textContent).toBe(
      "已用 1,500 / 29,491 字符",
    );
    expect(calls).toEqual([
      { url: "/api/bots/bot-1/files", method: "GET", body: undefined },
    ]);
  });

  it("shows an empty state", async () => {
    stubApi(() => json({ items: [], used_chars: 0, budget_chars: 29491 }));
    render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    expect(await screen.findByText("还没有资料文件")).toBeTruthy();
  });

  it("uploads a text file as JSON and refreshes the list and usage", async () => {
    const calls = stubApi((call) => {
      if (call.method === "POST") {
        return json(
          {
            file: file("f3", "api.md", 5),
            items: [...library.items, file("f3", "api.md", 5)],
            used_chars: 1505,
            budget_chars: 29491,
          },
          201,
        );
      }
      return json(library);
    });
    render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    await screen.findByText("spec.md");

    pick([new File(["hello"], "api.md", { type: "text/markdown" })]);
    expect(await screen.findByText("api.md")).toBeTruthy();
    expect(screen.getByTestId("bot-files-usage").textContent).toBe(
      "已用 1,505 / 29,491 字符",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toBe("/api/bots/bot-1/files");
    expect(post?.body).toEqual({ filename: "api.md", content: "hello" });
  });

  it("rejects unsupported formats without calling the server", async () => {
    const calls = stubApi(() => json(library));
    render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    await screen.findByText("spec.md");

    pick([new File(["%PDF"], "paper.pdf", { type: "application/pdf" })]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("paper.pdf");
    expect(alert.textContent).toContain("暂不支持该格式");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's message when the budget is exceeded", async () => {
    stubApi((call) =>
      call.method === "POST"
        ? json(
            {
              error_category: "file_budget_exceeded",
              detail: "超出这个 Bot 的资料上限：已用 1500，这个文件 40000，上限 29491 字符",
            },
            409,
          )
        : json(library),
    );
    render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    await screen.findByText("spec.md");

    pick([new File(["x"], "big.txt")]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("big.txt");
    expect(alert.textContent).toContain("超出这个 Bot 的资料上限");
    expect(screen.getByTestId("bot-files-usage").textContent).toBe(
      "已用 1,500 / 29,491 字符",
    );
  });

  it("deletes a file and lowers the usage", async () => {
    const calls = stubApi((call) =>
      call.method === "DELETE" ? new Response(null, { status: 204 }) : json(library),
    );
    render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    await screen.findByText("spec.md");

    fireEvent.click(screen.getByRole("button", { name: "删除 spec.md" }));
    await waitFor(() => expect(screen.queryByText("spec.md")).toBeNull());
    expect(screen.getByText("notes.txt")).toBeTruthy();
    expect(screen.getByTestId("bot-files-usage").textContent).toBe(
      "已用 300 / 29,491 字符",
    );
    expect(calls.find((c) => c.method === "DELETE")?.url).toBe(
      "/api/bots/bot-1/files/f1",
    );
  });

  it("closes on Escape and stays disabled for archived bots", async () => {
    stubApi(() => json(library));
    const view = render(<BotFilesPanel botId="bot-1" />);
    await openPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("bot-files-panel")).toBeNull());

    view.rerender(<BotFilesPanel botId="bot-1" disabled />);
    expect(
      (screen.getByRole("button", { name: "资料文件" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
