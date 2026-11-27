import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectMemoryPanel } from "./ProjectMemoryPanel";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

const memory = {
  mem_id: "m1",
  owner_bot_id: "bot-1",
  project_id: "p1",
  visibility: "project",
  version: 1,
  status: "pending",
  sources: [],
  body: { text: "座位规则" },
  title: "座位规则",
  run_id: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProjectMemoryPanel", () => {
  it("reads project memory with the current actor", async () => {
    const calls: Array<{ url: string; headers: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), headers: init?.headers });
        return json({ items: [memory] });
      }),
    );
    render(<ProjectMemoryPanel projectId="p1" actorBotId="bot-1" isLeader={false} />);
    expect(await screen.findByText("座位规则")).toBeTruthy();
    const call = calls.find((item) => item.url.startsWith("/api/memory/records"));
    expect(call?.url).toBe("/api/memory/records?project_id=p1&visibility=project");
    expect((call?.headers as Record<string, string>)["X-Bot-Id"]).toBe("bot-1");
  });

  it("shows the forbidden state separately from the workstation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ error_category: "memory_forbidden", detail: "no" }, 403)));
    render(<ProjectMemoryPanel projectId="p1" actorBotId="bot-x" isLeader={false} />);
    expect(await screen.findByTestId("project-memory-forbidden")).toBeTruthy();
  });

  it("lets a leader publish a pending memory", async () => {
    const calls: Array<{ url: string; method: string; body: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), method: init?.method || "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
        if (String(input).endsWith("/publish")) return json({ ...memory, status: "published" });
        return json({ items: [memory] });
      }),
    );
    render(<ProjectMemoryPanel projectId="p1" actorBotId="bot-1" isLeader />);
    fireEvent.click(await screen.findByTestId("publish-memory-m1"));
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const publish = calls.find((call) => call.method === "POST")!;
    expect(publish.url).toBe("/api/memory/records/m1/publish");
    expect(publish.body).toEqual({ expected_version: 1 });
  });

  it("hides the publish action from non-leaders", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ items: [memory] })));
    render(<ProjectMemoryPanel projectId="p1" actorBotId="bot-1" isLeader={false} />);
    expect(await screen.findByText("座位规则")).toBeTruthy();
    expect(screen.queryByTestId("publish-memory-m1")).toBeNull();
  });
});