import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  DiscussionTimelineItem,
  ReviewBallot,
} from "../../../api/types";
import type { TeamMember } from "../TeamStrip";
import { DiscussionView } from "./DiscussionView";

const apiMock = vi.hoisted(() => ({
  discussionProposals: vi.fn(),
  pauseDiscussion: vi.fn(),
  resumeDiscussion: vi.fn(),
  terminateDiscussion: vi.fn(),
  planDiscussion: vi.fn(),
}));

vi.mock("../../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/client")>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const hookState = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("./useDiscussionSession", () => ({
  useDiscussionSession: () => hookState.current,
}));

type HookState = {
  loading: boolean;
  error: string;
  session: DiscussionSession | null;
  sessions: DiscussionSession[];
  messages: DiscussionMessage[];
  timeline: DiscussionTimelineItem[];
  reviews: ReviewBallot[];
  connection: "idle" | "connecting" | "live" | "error";
  refresh: () => void;
};

const MEMBERS: TeamMember[] = [
  {
    bot_id: "bot-a",
    display_name: "林可",
    role_template: "leader",
    status: "active",
    role_in_project: "lead",
    is_leader: true,
  },
  {
    bot_id: "bot-b",
    display_name: "周明",
    role_template: "reviewer",
    status: "active",
    role_in_project: "dev",
    is_leader: false,
  },
];

const BOTS: BotInstance[] = [
  {
    bot_id: "bot-a",
    display_name: "林可",
    role_template: "leader",
    provider_ref: "dashscope",
    model: "qwen-plus",
    slot: "planner",
    secret_ref: "DASHSCOPE_API_KEY",
    tool_policy: [],
    skill_bindings: [],
    token_budget: null,
    status: "active",
  },
  {
    bot_id: "bot-b",
    display_name: "周明",
    role_template: "reviewer",
    provider_ref: "dashscope",
    model: "qwen-plus",
    slot: "reviewer",
    secret_ref: "DASHSCOPE_API_KEY",
    tool_policy: [],
    skill_bindings: [],
    token_budget: null,
    status: "active",
  },
];

const DECISION_PACKAGE = {
  decision_id: "decision-1",
  session_id: "s1",
  requirement_snapshot_hash: "hash",
  proposal_ids: ["prop-1"],
  dissent_items: [],
  hard_gate_summary: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: true },
  body_md: "# 需求规格\n\n正文第一段",
  sha256: "abcdef1234567890",
};

function makeSession(overrides: Partial<DiscussionSession> = {}): DiscussionSession {
  return {
    session_id: "s1",
    project_id: "proj-1",
    leader_bot_id: "bot-a",
    participant_bot_ids: ["bot-a", "bot-b"],
    status: "cross_review",
    current_round: 1,
    budget: {
      max_rounds: 3,
      max_tokens: null,
      max_wallclock_seconds: null,
      score_gap_threshold: 5,
    },
    requirement_snapshot_hash: "hash",
    decision_package: null,
    requirement_text: "做一个学习室预约页面",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-20T10:00:00Z",
    ...overrides,
  };
}

function proposalMessage(seq: number, proposalId: string): DiscussionMessage {
  return {
    session_id: "s1",
    seq,
    kind: "proposal",
    bot_id: "bot-b",
    round: 1,
    payload: { proposal_id: proposalId, chars: 20, truncated: false, round: 1 },
    created_at: "2026-11-20T10:00:00Z",
  };
}

const refresh = vi.fn();
const onInvite = vi.fn();

function setHookState(overrides: Partial<HookState> = {}): HookState {
  const state: HookState = {
    loading: false,
    error: "",
    session: null,
    sessions: [],
    messages: [],
    timeline: [],
    reviews: [],
    connection: "idle",
    refresh,
    ...overrides,
  };
  hookState.current = state as unknown as Record<string, unknown>;
  return state;
}

function element() {
  return (
    <MemoryRouter>
      <DiscussionView
        projectId="proj-1"
        actorBotId="bot-a"
        members={MEMBERS}
        bots={BOTS}
        onInvite={onInvite}
      />
    </MemoryRouter>
  );
}

function renderView() {
  return render(element());
}

function stageBarStage(): string | null {
  return screen.getByTestId("disc-stage-bar").getAttribute("data-stage");
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.discussionProposals.mockResolvedValue({ items: [] });
  apiMock.pauseDiscussion.mockResolvedValue(makeSession({ paused: true }));
  apiMock.resumeDiscussion.mockResolvedValue(makeSession());
  apiMock.terminateDiscussion.mockResolvedValue(makeSession({ status: "terminated" }));
});

afterEach(cleanup);

describe("DiscussionView stage routing", () => {
  it("shows the stage bar and the idea composer when there is no session", () => {
    setHookState();
    renderView();

    expect(stageBarStage()).toBe("idea");
    expect(screen.getByLabelText("一句话想法")).toBeTruthy();
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(screen.queryByTestId("disc-score-panel")).toBeNull();
  });

  it("shows the loading text instead of the composer while the first load runs", () => {
    setHookState({ loading: true });
    renderView();

    expect(screen.getByText("正在加载讨论…")).toBeTruthy();
    expect(screen.queryByLabelText("一句话想法")).toBeNull();
  });

  it("shows the Chinese load error without dropping the stage bar", () => {
    setHookState({ error: "网络中断" });
    renderView();

    expect(screen.getByTestId("disc-error").textContent).toBe("讨论加载失败：网络中断");
    expect(screen.getByTestId("disc-stage-bar")).toBeTruthy();
  });

  it("shows the two-column chat and score panel for independent discussion", () => {
    const session = makeSession({ status: "round1_independent" });
    setHookState({
      session,
      sessions: [session],
      timeline: [{ type: "divider", key: "d1", text: "第 1 次讨论" }],
    });
    renderView();

    expect(stageBarStage()).toBe("independent");
    expect(screen.getByTestId("disc-layout")).toBeTruthy();
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(screen.getByTestId("disc-score-panel")).toBeTruthy();
    expect(screen.queryByLabelText("一句话想法")).toBeNull();
  });

  it("shows the chat and score panel for a revision round labelled as 修改方案", () => {
    const session = makeSession({ status: "round_n_revise", current_round: 2 });
    setHookState({
      session,
      sessions: [session],
      timeline: [{ type: "divider", key: "d1", text: "第 2 次讨论" }],
    });
    renderView();

    expect(stageBarStage()).toBe("revise");
    const bar = screen.getByTestId("disc-stage-bar");
    const items = within(bar).getAllByRole("listitem");
    expect(items[1].getAttribute("aria-current")).toBe("step");
    expect(within(bar).getByTestId("disc-stage-subtitle").textContent).toBe("第 2 轮 · 修改方案");
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(screen.getByTestId("disc-score-panel")).toBeTruthy();
  });

  it("shows a non-blocking hint when the live connection failed", () => {
    const session = makeSession({ status: "cross_review" });
    setHookState({ session, sessions: [session], connection: "error" });
    renderView();

    expect(screen.getByTestId("disc-connection-hint").textContent).toContain("实时连接不可用");
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
  });
});

describe("DiscussionView approval", () => {
  function approvalState() {
    const session = makeSession({
      status: "converged_pending_human",
      current_round: 2,
      decision_package: DECISION_PACKAGE,
    });
    return { session, state: setHookState({ session, sessions: [session] }) };
  }

  it("opens the approval dialog once, keeps the banner, and does not reopen after closing", () => {
    const { session } = approvalState();
    const { rerender } = renderView();

    expect(screen.getByTestId("disc-approval-banner")).toBeTruthy();
    expect(screen.getByTestId("disc-approval-dialog")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByTestId("disc-approval-dialog")).toBeNull();
    expect(screen.getByTestId("disc-approval-banner")).toBeTruthy();

    // A refresh hands back a new session object with the same id: no auto reopen.
    const refreshed = { ...session };
    setHookState({ session: refreshed, sessions: [refreshed] });
    rerender(element());
    expect(screen.queryByTestId("disc-approval-dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "查看并审批" }));
    expect(screen.getByTestId("disc-approval-dialog")).toBeTruthy();
  });

  it("auto-opens again after leaving and re-entering the approval stage", () => {
    const { session } = approvalState();
    const { rerender } = renderView();
    expect(screen.getByTestId("disc-approval-dialog")).toBeTruthy();

    const approved = makeSession({ status: "approved", decision_package: DECISION_PACKAGE });
    setHookState({ session: approved, sessions: [session, approved] });
    rerender(element());
    expect(screen.queryByTestId("disc-approval-dialog")).toBeNull();

    const next = makeSession({
      session_id: "s2",
      status: "converged_pending_human",
      decision_package: { ...DECISION_PACKAGE, session_id: "s2" },
      previous_session_id: "s1",
    });
    setHookState({ session: next, sessions: [session, approved, next] });
    rerender(element());
    expect(screen.getByTestId("disc-approval-dialog")).toBeTruthy();
  });
});

describe("DiscussionView approved spec", () => {
  it("shows a failed plan state and replaces it with the plan links after retry", async () => {
    const session = makeSession({ status: "approved", decision_package: DECISION_PACKAGE });
    apiMock.planDiscussion.mockRejectedValueOnce(new Error("模型暂不可用"))
      .mockResolvedValueOnce({ run_id: "planned-run" });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(await screen.findByText("生成失败，等待重试")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重新生成任务计划" }));
    const link = await screen.findByRole("link", { name: "查看任务编排" });
    expect(link.getAttribute("href")).toBe("/workstation/planned-run");
    expect(apiMock.planDiscussion).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("生成失败，等待重试")).toBeNull();
  });

  it("shows the spec preview, the waiting placeholder and opens the spec viewer", () => {
    const body = "# 需求规格\n\n" + "覆盖主流程与边界条件。".repeat(40);
    const session = makeSession({
      status: "approved",
      decision_package: { ...DECISION_PACKAGE, body_md: body },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    const summary = screen.getByTestId("disc-spec-summary");
    expect(summary.textContent).toContain("abcdef12");
    expect(within(summary).getByText(/Leader 正在拆解/)).toBeTruthy();
    expect(summary.textContent).not.toContain("#");
    expect(summary.textContent).toContain("覆盖主流程与边界条件。");
    expect(screen.getByTestId("disc-chat")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "查看需求规格" }));
    expect(screen.getByTestId("disc-spec-dialog")).toBeTruthy();
  });
});

describe("DiscussionView terminated", () => {
  it("keeps the timeline and scores but disables the controls", () => {
    const session = makeSession({ status: "terminated" });
    setHookState({
      session,
      sessions: [session],
      timeline: [{ type: "divider", key: "d1", text: "第 1 次讨论" }],
    });
    renderView();

    expect(stageBarStage()).toBe("terminated");
    expect(screen.getByText("讨论已终止")).toBeTruthy();
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(screen.getByTestId("disc-score-panel")).toBeTruthy();
    expect((screen.getByRole("button", { name: "暂停" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "终止" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("DiscussionView controls", () => {
  it("pauses through the API and then refreshes", async () => {
    const session = makeSession({ status: "cross_review" });
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));

    await waitFor(() =>
      expect(apiMock.pauseDiscussion).toHaveBeenCalledWith("s1", "bot-a"),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("terminates after confirmation and then refreshes", async () => {
    const session = makeSession({ status: "cross_review" });
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "终止" }));
    fireEvent.click(screen.getByRole("button", { name: "确认终止" }));

    await waitFor(() =>
      expect(apiMock.terminateDiscussion).toHaveBeenCalledWith("s1", "bot-a"),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("resumes while skipping the failed bot", async () => {
    const session = makeSession({ status: "cross_review", paused: true });
    const failure: DiscussionMessage = {
      session_id: "s1",
      seq: 3,
      kind: "system",
      bot_id: "bot-b",
      round: 1,
      payload: { event: "bot_failed", bot_id: "bot-b", error_category: "timeout", text: "周明 调用超时" },
      created_at: "2026-11-20T10:01:00Z",
    };
    setHookState({ session, sessions: [session], messages: [failure] });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "跳过此 Bot" }));

    await waitFor(() =>
      expect(apiMock.resumeDiscussion).toHaveBeenCalledWith(
        "s1",
        { skip_bot_ids: ["bot-b"] },
        "bot-a",
      ),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("shows a Chinese action error and keeps the timeline", async () => {
    const session = makeSession({ status: "cross_review" });
    apiMock.pauseDiscussion.mockRejectedValueOnce(new Error("只有 Leader 可以暂停讨论"));
    setHookState({
      session,
      sessions: [session],
      timeline: [{ type: "divider", key: "d1", text: "第 1 次讨论" }],
    });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));

    await waitFor(() =>
      expect(screen.getByTestId("disc-action-error").textContent).toBe("只有 Leader 可以暂停讨论"),
    );
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("DiscussionView proposal bodies", () => {
  function reviewStateWithProposals() {
    const session = makeSession({ status: "cross_review" });
    setHookState({
      session,
      sessions: [session],
      messages: [proposalMessage(1, "prop-1"), proposalMessage(2, "prop-1")],
      timeline: [
        { type: "divider", key: "d1", text: "第 1 次讨论" },
        { type: "message", message: proposalMessage(1, "prop-1") },
        { type: "message", message: proposalMessage(2, "prop-1") },
      ],
    });
  }

  it("loads the proposal body from the API and caches repeated calls", async () => {
    reviewStateWithProposals();
    apiMock.discussionProposals.mockResolvedValue({
      items: [
        { proposal_id: "prop-1", author_bot_id: "bot-b", round: 1, sealed: false, body_md: "方案正文" },
      ],
    });
    renderView();

    fireEvent.click(screen.getAllByRole("button", { name: "展开方案" })[0]);
    await waitFor(() => expect(screen.getAllByLabelText("方案正文").length).toBe(1));

    fireEvent.click(screen.getAllByRole("button", { name: "展开方案" })[0]);
    await waitFor(() => expect(screen.getAllByLabelText("方案正文").length).toBe(2));

    expect(apiMock.discussionProposals).toHaveBeenCalledTimes(1);
    expect(apiMock.discussionProposals).toHaveBeenCalledWith("s1", "bot-a");
    expect(screen.getAllByLabelText("方案正文")[0].textContent).toBe("方案正文");
  });

  it("says the body is still sealed instead of throwing when it is null", async () => {
    reviewStateWithProposals();
    apiMock.discussionProposals.mockResolvedValue({
      items: [{ proposal_id: "prop-1", author_bot_id: "bot-b", round: 1, sealed: true, body_md: null }],
    });
    renderView();

    fireEvent.click(screen.getAllByRole("button", { name: "展开方案" })[0]);

    expect(await screen.findByText("正文尚未解封")).toBeTruthy();
  });
});
