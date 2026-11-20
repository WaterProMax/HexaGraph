import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotInstance } from "../../api/types";
import { ManageMembersDialog } from "./ManageMembersDialog";
import type { TeamMember } from "./TeamStrip";

const members: TeamMember[] = [
  { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active", role_in_project: "lead", is_leader: true },
  { bot_id: "bot-b", display_name: "周明", role_template: "pm", status: "active", role_in_project: "dev", is_leader: false },
];

const candidate: BotInstance = {
  bot_id: "bot-c",
  display_name: "Tester C",
  role_template: "qa",
  provider_ref: "dashscope",
  model: "qwen-plus",
  slot: "coder",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [],
  token_budget: 40000,
  status: "active",
};

type Call = { method: string; url: string; body: any };

function stubFetch(handler?: (call: Call) => Response | undefined) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method || "GET",
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      };
      calls.push(call);
      const custom = handler?.(call);
      if (custom) return custom;
      return new Response(null, { status: 204 });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ManageMembersDialog", () => {
  it("adds a bot with the chosen role", async () => {
    const calls = stubFetch();
    render(
      <ManageMembersDialog
        projectId="p1"
        members={members}
        allBots={[candidate]}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("添加 Bot"), { target: { value: "bot-c" } });
    fireEvent.change(screen.getByLabelText("项目角色"), { target: { value: "qa" } });
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const post = calls.find((call) => call.method === "POST")!;
    expect(post.url).toBe("/api/projects/p1/memberships");
    expect(post.body).toEqual({ bot_id: "bot-c", role_in_project: "qa", is_leader: false });
  });

  it("removes a member through DELETE", async () => {
    const calls = stubFetch();
    render(
      <ManageMembersDialog projectId="p1" members={members} allBots={[]} onClose={vi.fn()} onChanged={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "移出 周明" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/projects/p1/memberships/bot-b" });
  });

  it("transfers leadership with delete-then-add and keeps the old leader", async () => {
    const calls = stubFetch();
    render(
      <ManageMembersDialog projectId="p1" members={members} allBots={[]} onClose={vi.fn()} onChanged={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "将 周明 设为 Leader" }));
    await waitFor(() => expect(calls.length).toBe(4));
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      "DELETE /api/projects/p1/memberships/bot-a",
      "POST /api/projects/p1/memberships",
      "DELETE /api/projects/p1/memberships/bot-b",
      "POST /api/projects/p1/memberships",
    ]);
    expect(calls[1].body).toEqual({ bot_id: "bot-a", role_in_project: "lead", is_leader: false });
    expect(calls[3].body).toEqual({ bot_id: "bot-b", role_in_project: "dev", is_leader: true });
  });

  it("surfaces the backend error category and reloads", async () => {
    const onChanged = vi.fn();
    stubFetch((call) =>
      call.method === "POST"
        ? new Response(JSON.stringify({ error_category: "leader_already_set", detail: "no" }), {
            status: 409,
            headers: { "Content-Type": "application/json" },
          })
        : undefined,
    );
    render(
      <ManageMembersDialog projectId="p1" members={members} allBots={[candidate]} onClose={vi.fn()} onChanged={onChanged} />,
    );
    fireEvent.change(screen.getByLabelText("添加 Bot"), { target: { value: "bot-c" } });
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }));
    expect(await screen.findByText(/leader_already_set/)).toBeTruthy();
    expect(onChanged).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<ManageMembersDialog projectId="p1" members={members} allBots={[]} onClose={onClose} onChanged={vi.fn()} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});