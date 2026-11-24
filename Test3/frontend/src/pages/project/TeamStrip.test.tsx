import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TeamStrip, type TeamMember } from "./TeamStrip";

const members: TeamMember[] = [
  { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active", role_in_project: "lead", is_leader: true },
  { bot_id: "bot-b", display_name: "周明", role_template: "pm", status: "active", role_in_project: "dev", is_leader: false },
];

afterEach(cleanup);

describe("TeamStrip", () => {
  it("shows the leader and member avatars without an identity switcher", () => {
    render(<TeamStrip members={members} onInvite={vi.fn()} onManage={vi.fn()} />);
    const strip = screen.getByTestId("team-strip");
    const leader = strip.querySelector(".team-member.is-leader");
    expect(leader).toBeTruthy();
    expect(leader?.querySelector(".bot-avatar")).toBeTruthy();
    expect(strip.textContent).not.toContain("Leader");
    expect(screen.queryByTestId("actor-bot-select")).toBeNull();
    expect(strip.textContent).not.toContain("当前操作身份");
  });

  it("opens invite and management from the strip", () => {
    const onManage = vi.fn();
    const onInvite = vi.fn();
    render(<TeamStrip members={members} onInvite={onInvite} onManage={onManage} />);
    fireEvent.click(screen.getByTestId("manage-members"));
    expect(onManage).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("invite-bots"));
    expect(onInvite).toHaveBeenCalled();
  });

  it("handles an empty team", () => {
    render(<TeamStrip members={[]} onInvite={vi.fn()} onManage={vi.fn()} />);
    expect(screen.getByTestId("team-strip").textContent).not.toContain("尚未加入 Bot");
    expect(screen.getByRole("button", { name: "邀请 Bot" })).toBeTruthy();
    expect(screen.queryByTestId("actor-bot-select")).toBeNull();
  });
});
