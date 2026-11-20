import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TeamStrip, type TeamMember } from "./TeamStrip";

const members: TeamMember[] = [
  { bot_id: "bot-a", display_name: "Leader A", role_template: "leader", status: "active", role_in_project: "lead", is_leader: true },
  { bot_id: "bot-b", display_name: "周明", role_template: "pm", status: "active", role_in_project: "dev", is_leader: false },
];

afterEach(cleanup);

describe("TeamStrip", () => {
  it("shows the leader and members with an actor selector", () => {
    render(<TeamStrip members={members} actorBotId="bot-b" onActorChange={vi.fn()} onManage={vi.fn()} />);
    const strip = screen.getByTestId("team-strip");
    expect(strip.textContent).toContain("Leader");
    const select = screen.getByTestId("actor-bot-select") as HTMLSelectElement;
    expect(select.value).toBe("bot-b");
    expect(Array.from(select.options).map((option) => option.value)).toEqual(["bot-a", "bot-b"]);
  });

  it("reports actor changes and opens management", () => {
    const onActorChange = vi.fn();
    const onManage = vi.fn();
    render(<TeamStrip members={members} actorBotId="bot-a" onActorChange={onActorChange} onManage={onManage} />);
    fireEvent.change(screen.getByTestId("actor-bot-select"), { target: { value: "bot-b" } });
    expect(onActorChange).toHaveBeenCalledWith("bot-b");
    fireEvent.click(screen.getByTestId("manage-members"));
    expect(onManage).toHaveBeenCalled();
  });

  it("handles an empty team", () => {
    render(<TeamStrip members={[]} actorBotId="" onActorChange={vi.fn()} onManage={vi.fn()} />);
    expect(screen.getByTestId("team-strip").textContent).toContain("尚未加入 Bot");
    expect(screen.queryByTestId("actor-bot-select")).toBeNull();
  });
});