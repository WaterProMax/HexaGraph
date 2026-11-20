import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManageMembersDialog } from "./ManageMembersDialog";
import type { TeamMember } from "./TeamStrip";

const members: TeamMember[] = [
  { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active", role_in_project: "lead", is_leader: true },
  { bot_id: "bot-b", display_name: "周明", role_template: "pm", status: "active", role_in_project: "dev", is_leader: false },
];

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

function renderDialog(overrides: Partial<React.ComponentProps<typeof ManageMembersDialog>> = {}) {
  const props = {
    projectId: "p1",
    members,
    onClose: vi.fn(),
    onInvite: vi.fn(),
    onChanged: vi.fn(),
    ...overrides,
  };
  render(<ManageMembersDialog {...props} />);
  return props;
}

describe("ManageMembersDialog", () => {
  it("lists members with Chinese role titles and a Leader badge, without a Leader action on the leader", () => {
    renderDialog();
    const dialog = screen.getByTestId("members-dialog");
    expect(dialog.textContent).toContain("2 人");
    expect(dialog.textContent).toContain("Leader A");
    expect(screen.queryByRole("button", { name: "将 Leader A 设为 Leader" })).toBeNull();
    expect(screen.getByRole("button", { name: "将 周明 设为 Leader" })).toBeTruthy();
    expect(screen.queryByLabelText("添加 Bot")).toBeNull();
  });

  it("removes a member through DELETE", async () => {
    const calls = stubFetch();
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "移出 周明" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/projects/p1/memberships/bot-b" });
  });

  it("transfers leadership with delete-then-add and keeps the old leader", async () => {
    const calls = stubFetch();
    renderDialog();
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

  it("surfaces a readable error and reloads when a call fails", async () => {
    stubFetch((call) =>
      call.method === "DELETE"
        ? new Response(JSON.stringify({ error_category: "membership_not_found", detail: "no" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          })
        : undefined,
    );
    const props = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "移出 周明" }));
    expect((await screen.findByRole("alert")).textContent).toContain("该成员已不在项目里");
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("hands over to the invite dialog for adding more bots", () => {
    const props = renderDialog();
    fireEvent.click(screen.getByTestId("members-invite-more"));
    expect(props.onInvite).toHaveBeenCalled();
  });

  it("shows an empty state when there are no members", () => {
    renderDialog({ members: [] });
    expect(screen.getByTestId("members-empty").textContent).toContain("还没有成员");
  });

  it("closes on Escape", () => {
    const props = renderDialog();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalled();
  });
});
