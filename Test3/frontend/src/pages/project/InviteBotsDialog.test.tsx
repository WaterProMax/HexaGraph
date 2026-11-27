import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotInstance } from "../../api/types";
import { InviteBotsDialog } from "./InviteBotsDialog";
import type { TeamMember } from "./TeamStrip";

function bot(id: string, name: string, role: string, status: BotInstance["status"] = "active"): BotInstance {
  return {
    bot_id: id,
    display_name: name,
    role_template: role,
    provider_ref: "dashscope",
    model: "qwen-plus",
    slot: "flagship",
    secret_ref: "DASHSCOPE_API_KEY",
    tool_policy: [],
    skill_bindings: [],
    token_budget: 40000,
    status,
  };
}

const bots = [
  bot("bot-a", "Leader A", "leader"),
  bot("bot-b", "Water", "backend"),
  bot("bot-c", "Tester C", "qa"),
  bot("bot-old", "Old", "pm", "archived"),
];

const leaderMember: TeamMember = {
  bot_id: "bot-a",
  display_name: "Leader A",
  role_template: "leader",
  status: "active",
  role_in_project: "leader",
  is_leader: true,
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
      return handler?.(call) ?? new Response(JSON.stringify({}), { status: 201, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

function renderDialog(overrides: Partial<React.ComponentProps<typeof InviteBotsDialog>> = {}) {
  const props = {
    projectId: "p1",
    members: [] as TeamMember[],
    allBots: bots,
    onClose: vi.fn(),
    onChanged: vi.fn(),
    ...overrides,
  };
  render(
    <MemoryRouter>
      <InviteBotsDialog {...props} />
    </MemoryRouter>,
  );
  return props;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("InviteBotsDialog", () => {
  it("lists only active bots that are not yet members, with Chinese role titles", () => {
    renderDialog({ members: [leaderMember] });
    expect(screen.queryByLabelText("邀请 Leader A")).toBeNull();
    expect(screen.queryByLabelText("邀请 Old")).toBeNull();
    expect(screen.getByLabelText("邀请 Water")).toBeTruthy();
    expect(screen.getByLabelText("邀请 Tester C")).toBeTruthy();
    expect(screen.getByTestId("invite-dialog").textContent).toContain("后端工程师");
  });

  it("disables submit until a bot is selected and supports select all", () => {
    renderDialog();
    const submit = screen.getByTestId("invite-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("全选"));
    expect(submit.disabled).toBe(false);
    expect(submit.textContent).toBe("邀请 3 个 Bot");
    fireEvent.click(screen.getByLabelText("全选"));
    expect(submit.textContent).toBe("邀请 0 个 Bot");
  });

  it("posts every selected bot with its own role and marks the chosen leader", async () => {
    const calls = stubFetch();
    const props = renderDialog();
    fireEvent.click(screen.getByLabelText("邀请 Water"));
    fireEvent.click(screen.getByLabelText("邀请 Tester C"));
    fireEvent.click(screen.getByLabelText("将 Water 设为 Leader"));
    fireEvent.click(screen.getByTestId("invite-submit"));
    await waitFor(() => expect(props.onClose).toHaveBeenCalled());
    const posts = calls.filter((call) => call.method === "POST");
    expect(posts.map((call) => call.url)).toEqual(["/api/projects/p1/memberships", "/api/projects/p1/memberships"]);
    expect(posts.map((call) => call.body)).toEqual([
      { bot_id: "bot-b", role_in_project: "backend", is_leader: true },
      { bot_id: "bot-c", role_in_project: "qa", is_leader: false },
    ]);
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("only allows a single leader and hides the option when the project has one", () => {
    renderDialog();
    fireEvent.click(screen.getByLabelText("邀请 Water"));
    fireEvent.click(screen.getByLabelText("邀请 Tester C"));
    fireEvent.click(screen.getByLabelText("将 Water 设为 Leader"));
    fireEvent.click(screen.getByLabelText("将 Tester C 设为 Leader"));
    expect((screen.getByLabelText("将 Water 设为 Leader") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("将 Tester C 设为 Leader") as HTMLInputElement).checked).toBe(true);
    cleanup();
    renderDialog({ members: [leaderMember] });
    fireEvent.click(screen.getByLabelText("邀请 Water"));
    expect(screen.queryByLabelText("将 Water 设为 Leader")).toBeNull();
  });

  it("keeps failed bots in the list with a reason and does not close", async () => {
    stubFetch((call) => {
      if (call.body?.bot_id === "bot-c") {
        return new Response(JSON.stringify({ error_category: "membership_exists", detail: "x" }), {
          status: 409,
          headers: { "content-type": "application/json" },
        });
      }
      return undefined;
    });
    const props = renderDialog();
    fireEvent.click(screen.getByLabelText("全选"));
    fireEvent.click(screen.getByTestId("invite-submit"));
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("1 个 Bot 邀请失败");
    expect(screen.getByRole("status").textContent).toContain("已经是项目成员");
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("shows an empty state with a link to create a bot", () => {
    renderDialog({ members: [leaderMember], allBots: [bots[0]] });
    expect(screen.getByTestId("invite-empty").textContent).toContain("没有可邀请的 Bot");
    expect(screen.getByRole("link", { name: "去新建 Bot" }).getAttribute("href")).toBe("/bots/new");
  });

  it("closes on Escape", () => {
    const props = renderDialog();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalled();
  });
});
