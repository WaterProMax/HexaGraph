import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../api/client";
import type { TaskAssignment } from "../../api/types";
import { TaskAssignmentBoard, type AssignmentBoardTask } from "./TaskAssignmentBoard";
import type { TeamMember } from "./TeamStrip";

/**
 * A2/A3: the classroom dispatch board on the project main path. The overlay
 * annotates responsibility only — execution and role memory stay role-scoped.
 */

const members: TeamMember[] = [
  { bot_id: "bot-leader", display_name: "Alice Leader", role_template: "developer", status: "active", role_in_project: "dev", is_leader: true },
  { bot_id: "bot-a", display_name: "Member A", role_template: "developer", status: "active", role_in_project: "dev", is_leader: false },
  { bot_id: "bot-b", display_name: "Member B", role_template: "tester", status: "active", role_in_project: "dev", is_leader: false },
];

const assignmentOf = (botId: string, name: string): TaskAssignment => ({
  assignee_bot_id: botId,
  assignee_display_name: name,
  assigned_by_bot_id: "bot-leader",
  assigned_at: "2026-11-26T10:00:00+00:00",
  revision: 1,
});

const tasks: AssignmentBoardTask[] = [
  { code: "T-01", title: "实现登录", role: "coder", dependsOn: [], status: "ready", revision: 3, assignment: null },
  { code: "T-02", title: "接通验收", role: "tester", dependsOn: ["T-01"], status: "pending", revision: 2, assignment: assignmentOf("bot-b", "Member B") },
];

function renderBoard(overrides: Partial<Parameters<typeof TaskAssignmentBoard>[0]> = {}) {
  return render(
    <TaskAssignmentBoard
      runId="run-1"
      tasks={tasks}
      members={members}
      actorBotId="bot-leader"
      actorIsLeader
      {...overrides}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TaskAssignmentBoard dispatch (A2)", () => {
  it("lets the Leader pick a member and PUTs with the task revision and actor header", async () => {
    const assign = vi.spyOn(api, "assignTask").mockResolvedValue({
      code: "T-01",
      state: "ready",
      revision: 4,
      assignment: assignmentOf("bot-a", "Member A"),
    } as any);
    renderBoard();

    const select = screen.getByTestId("assignment-select-T-01") as HTMLSelectElement;
    expect(select.disabled).toBe(false);
    const options = Array.from(select.options).map((option) => option.value);
    expect(options).toContain("bot-a");
    expect(options).toContain("bot-leader"); // the Leader may assign to themselves
    fireEvent.change(select, { target: { value: "bot-a" } });

    await waitFor(() => expect(assign).toHaveBeenCalledWith(
      "run-1",
      "T-01",
      { assignee_bot_id: "bot-a", expected_revision: 3 },
      "bot-leader",
    ));
    await waitFor(() => expect(screen.getByTestId("assignment-assignee-T-01").textContent).toContain("Member A"));
  });

  it("is read-only by default and for non-Leaders; no write request is sent", () => {
    const assign = vi.spyOn(api, "assignTask");
    const view = renderBoard({ actorIsLeader: undefined });
    expect((screen.getByTestId("assignment-select-T-01") as HTMLSelectElement).disabled).toBe(true);
    view.rerender(
      <TaskAssignmentBoard runId="run-1" tasks={tasks} members={members} actorBotId="bot-a" actorIsLeader={false} />,
    );
    const select = screen.getByTestId("assignment-select-T-01") as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    fireEvent.change(select, { target: { value: "bot-a" } });
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows a Chinese conflict notice on 409 and refreshes the server assignment", async () => {
    vi.spyOn(api, "assignTask").mockRejectedValue(new ApiError("revision mismatch", { status: 409, category: "revision_conflict" }));
    const refresh = vi.spyOn(api, "tasks").mockResolvedValue([
      { code: "T-01", state: "ready", revision: 5, assignment: assignmentOf("bot-b", "Member B") },
      { code: "T-02", state: "pending", revision: 2, assignment: assignmentOf("bot-b", "Member B") },
    ] as any);
    renderBoard();

    fireEvent.change(screen.getByTestId("assignment-select-T-01"), { target: { value: "bot-a" } });

    await waitFor(() => expect(screen.getByTestId("assignment-error").textContent).toContain("冲突"));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith("run-1"));
    await waitFor(() => expect(screen.getByTestId("assignment-assignee-T-01").textContent).toContain("Member B"));
  });

  it("marks unassigned tasks honestly and explains the role/assignee split", () => {
    renderBoard();
    expect(screen.getByTestId("assignment-assignee-T-01").textContent).toContain("尚未派发");
    const note = screen.getByTestId("assignment-semantics-note");
    expect(note.textContent).toContain("角色");
    expect(note.textContent).toContain("记忆");
    expect(note.textContent).toContain("密钥");
    expect(screen.getByTestId("assignment-unassigned-count").textContent).toContain("1");
  });

  it("ignores a late response after the run changed", async () => {
    let resolveOld: (value: unknown) => void = () => {};
    vi.spyOn(api, "assignTask").mockImplementation(
      () => new Promise((resolve) => { resolveOld = resolve; }) as any,
    );
    const view = renderBoard();
    fireEvent.change(screen.getByTestId("assignment-select-T-01"), { target: { value: "bot-a" } });

    view.rerender(
      <TaskAssignmentBoard
        runId="run-2"
        tasks={[{ code: "T-01", title: "实现登录", role: "coder", dependsOn: [], status: "ready", revision: 9, assignment: null }]}
        members={members}
        actorBotId="bot-leader"
        actorIsLeader
      />,
    );
    resolveOld({ code: "T-01", state: "ready", revision: 4, assignment: assignmentOf("bot-a", "Member A") });
    await waitFor(() => expect(screen.getByTestId("assignment-assignee-T-01").textContent).toContain("尚未派发"));
  });

  it("is read-only once the run is done or terminated", () => {
    for (const runStatus of ["done", "terminated"]) {
      const view = renderBoard({ runStatus });
      expect((screen.getByTestId("assignment-select-T-01") as HTMLSelectElement).disabled).toBe(true);
      view.unmount();
    }
  });

  it("shows the plan-first empty state instead of fake tasks", () => {
    renderBoard({ tasks: [] });
    expect(screen.getByTestId("assignment-empty").textContent).toContain("确认需求规格并完成设计规格确认后");
    expect(screen.queryByTestId("assignment-select-T-01")).toBeNull();
  });
});

describe("TaskAssignmentBoard team visibility (A3)", () => {
  it("shows the Leader and members next to the board with a way back to the group chat", () => {
    const onShowDiscussion = vi.fn();
    renderBoard({ onShowDiscussion });
    const team = screen.getByTestId("assignment-team");
    expect(team.textContent).toContain("Alice Leader");
    expect(team.textContent).toContain("Member A");
    expect(team.textContent).toContain("Leader");
    fireEvent.click(screen.getByTestId("assignment-back-to-discussion"));
    expect(onShowDiscussion).toHaveBeenCalledTimes(1);
  });

  it("guides to the existing invite/manage dialogs when members or a Leader are missing", () => {
    const onInvite = vi.fn();
    const onManage = vi.fn();
    const createSession = vi.spyOn(api, "createDiscussionSession");
    renderBoard({
      members: [members[1]],
      actorBotId: "bot-a",
      actorIsLeader: false,
      onInvite,
      onManage,
    });
    expect(screen.getByTestId("assignment-team-guidance").textContent).toContain("先邀请 Bot");
    fireEvent.click(screen.getByTestId("assignment-invite"));
    expect(onInvite).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("assignment-manage"));
    expect(onManage).toHaveBeenCalledTimes(1);
    // The board never creates a second chat on its own.
    expect(createSession).not.toHaveBeenCalled();
  });
});