import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../../../api/client";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  DiscussionTimelineItem,
  ReviewBallot,
} from "../../../api/types";
import type { TeamMember } from "../TeamStrip";
import { DiscussionView } from "./DiscussionView";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const apiMock = vi.hoisted(() => ({
  discussionProposals: vi.fn(),
  pauseDiscussion: vi.fn(),
  resumeDiscussion: vi.fn(),
  terminateDiscussion: vi.fn(),
  planDiscussion: vi.fn(),
  designDiscussion: vi.fn(),
  run: vi.fn(),
  resolveGate: vi.fn(),
  addDiscussionIntervention: vi.fn(),
  supplementDiscussion: vi.fn(),
  endDiscussionRound: vi.fn(),
  startDiscussionRound: vi.fn(),
  runDiscussion: vi.fn(),
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

function element(actorBotId = "bot-a") {
  return (
    <MemoryRouter>
      <DiscussionView
        projectId="proj-1"
        actorBotId={actorBotId}
        members={MEMBERS}
        bots={BOTS}
        onInvite={onInvite}
      />
    </MemoryRouter>
  );
}

function renderView(actorBotId = "bot-a") {
  return render(element(actorBotId));
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
  apiMock.addDiscussionIntervention.mockResolvedValue(makeSession({ paused: true }));
  apiMock.supplementDiscussion.mockResolvedValue(makeSession({ status: "round_n_revise" }));
  apiMock.endDiscussionRound.mockResolvedValue(
    makeSession({ status: "converged_pending_human", paused: true, round_end_reason: { kind: "manual", text: "", round_no: 1, actor: "bot-a", revision: 2 } }),
  );
  apiMock.startDiscussionRound.mockResolvedValue(makeSession({ status: "round_n_revise", current_round: 2 }));
  apiMock.runDiscussion.mockResolvedValue({ running: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

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

  it("shows only the spec actions and opens the spec viewer", () => {
    const body = "# 需求规格\n\n" + "覆盖主流程与边界条件。".repeat(40);
    const session = makeSession({
      status: "approved",
      decision_package: { ...DECISION_PACKAGE, body_md: body },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    const summary = screen.getByTestId("disc-spec-summary");
    expect(within(summary).getByText(/Leader 正在拆解/)).toBeTruthy();
    expect(summary.textContent).not.toContain("覆盖主流程与边界条件。");
    expect(screen.queryByText("需求规格已通过")).toBeNull();
    expect(screen.getByTestId("disc-chat")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "查看需求规格" }));
    expect(screen.getByTestId("disc-spec-dialog")).toBeTruthy();
  });
});

describe("DiscussionView design stage", () => {
  const DESIGN_RUN = {
    id: "design-run",
    stage: "5",
    status: "waiting",
    artifacts: {
      design: {
        modules: [
          { code: "M1", name: "座位查询", responsibility: "返回空闲座位", sources: ["F1"], depends_on: [] },
          { code: "M2", name: "学生端页面", responsibility: "展示座位", sources: ["F1"], depends_on: ["M1"] },
        ],
        interfaces: [{ code: "C1", provider: "M1", consumers: ["M2"] }],
      },
      design_reviews: [
        { reviewer: "架构", dimension: "架构一致性", score: 5, opinions: [] },
        { reviewer: "质量", dimension: "实现质量", score: 4, opinions: [] },
      ],
    },
    gates: [{ id: "gate-design", kind: "DESIGN基线确认", status: "pending", payload: {} }],
  };

  function designSession(workflow: Record<string, unknown> = { design_approved: false }) {
    return makeSession({
      status: "approved",
      decision_package: DECISION_PACKAGE,
      workflow: { stage: "design_pending", run_id: null, ...workflow } as DiscussionSession["workflow"],
    });
  }

  it("routes an approved spec without design approval to the design step", async () => {
    apiMock.designDiscussion.mockResolvedValue({ run_id: "design-run" });
    apiMock.run.mockResolvedValue(DESIGN_RUN);
    const session = designSession();
    setHookState({ session, sessions: [session] });
    renderView();

    expect(stageBarStage()).toBe("design");
    expect(apiMock.designDiscussion).toHaveBeenCalledWith("s1", "bot-a");
    const panel = await screen.findByTestId("disc-design-review");
    expect(within(panel).getByText("设计规格待你确认")).toBeTruthy();
    expect(within(panel).getByText("座位查询")).toBeTruthy();
    expect(within(panel).getByText(/模块 2 个 · 接口 1 个/)).toBeTruthy();
    expect(within(panel).getByText(/架构 5 分/)).toBeTruthy();
    expect(apiMock.planDiscussion).not.toHaveBeenCalled();
  });

  it("approves the design baseline through the gate and refreshes", async () => {
    apiMock.designDiscussion.mockResolvedValue({ run_id: "design-run" });
    apiMock.run.mockResolvedValue(DESIGN_RUN);
    apiMock.resolveGate.mockResolvedValue({ status: "need_human", gate: { kind: "PLAN基线确认" } });
    const session = designSession();
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "批准设计基线" }));

    await waitFor(() =>
      expect(apiMock.resolveGate).toHaveBeenCalledWith("gate-design", "approve", {}),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("requires a reason before rejecting and refetches the rewritten design", async () => {
    const rewritten = {
      ...DESIGN_RUN,
      artifacts: {
        ...DESIGN_RUN.artifacts,
        design: {
          ...DESIGN_RUN.artifacts.design,
          modules: [{ code: "M1", name: "座位查询（含更新时间）", responsibility: "返回空闲座位", sources: ["F1"], depends_on: [] }],
        },
      },
      gates: [
        { id: "gate-design", kind: "DESIGN基线确认", status: "rejected", payload: {} },
        { id: "gate-design-2", kind: "DESIGN基线确认", status: "pending", payload: {} },
      ],
    };
    apiMock.designDiscussion.mockResolvedValue({ run_id: "design-run" });
    apiMock.run.mockResolvedValueOnce(DESIGN_RUN).mockResolvedValue(rewritten);
    apiMock.resolveGate.mockResolvedValue({ status: "need_human", gate: { kind: "DESIGN基线确认" } });
    const session = designSession();
    setHookState({ session, sessions: [session] });
    renderView();

    const rejectButton = await screen.findByRole("button", { name: "驳回重写" });
    expect((rejectButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("设计驳回意见"), { target: { value: "模块职责需补充更新时间" } });
    fireEvent.click(screen.getByRole("button", { name: "驳回重写" }));

    await waitFor(() =>
      expect(apiMock.resolveGate).toHaveBeenCalledWith("gate-design", "reject", { reason: "模块职责需补充更新时间" }),
    );
    expect(await screen.findByText("座位查询（含更新时间）")).toBeTruthy();
  });

  it("reuses an existing design run from the workflow projection without regenerating", async () => {
    apiMock.run.mockResolvedValue(DESIGN_RUN);
    const session = designSession({ design_approved: false, run_id: "design-run" });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(await screen.findByTestId("disc-design-review")).toBeTruthy();
    expect(apiMock.designDiscussion).not.toHaveBeenCalled();
    expect(apiMock.run).toHaveBeenCalledWith("design-run");
  });

  it("moves on to task splitting once the design baseline is approved", async () => {
    apiMock.planDiscussion.mockResolvedValue({ run_id: "design-run" });
    const session = designSession({ design_approved: true, run_id: "design-run", stage: "plan_pending" });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(stageBarStage()).toBe("approved");
    expect(await screen.findByRole("link", { name: "查看任务编排" })).toBeTruthy();
    expect(apiMock.designDiscussion).not.toHaveBeenCalled();
  });
});

describe("DiscussionView terminated", () => {
  it("keeps the timeline and scores but does not offer recoverable controls", () => {
    const session = makeSession({ status: "terminated" });
    setHookState({
      session,
      sessions: [session],
      timeline: [{ type: "divider", key: "d1", text: "第 1 次讨论" }],
    });
    renderView();

    expect(stageBarStage()).toBe("terminated");
    expect(screen.getByTestId("disc-chat")).toBeTruthy();
    expect(screen.getByTestId("disc-score-panel")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "暂停" })).toBeNull();
    expect(screen.queryByRole("button", { name: "终止" })).toBeNull();
    expect(screen.getByTestId("disc-readonly-note").textContent).toContain("讨论已终止");
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

  it("passes the current control revision when pausing", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 4 });
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    await waitFor(() =>
      expect(apiMock.pauseDiscussion).toHaveBeenCalledWith("s1", "bot-a", 4),
    );
  });

  it("pauses with the control revision and shows the pausing state", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 4, pause_requested: true });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(await screen.findByRole("button", { name: "正在暂停…" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "正在暂停…" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows only the bottom supplement composer when paused (intervention box retired)", async () => {
    const session = makeSession({ status: "cross_review", paused: true, control_revision: 7 });
    setHookState({ session, sessions: [session] });
    renderView();

    // 顶部「插话 / 调整方向」输入框已下线，只保留底部「补充信息」。
    expect(screen.queryByTestId("disc-intervention")).toBeNull();
    expect(screen.queryByLabelText("讨论插话")).toBeNull();
    expect(screen.queryByTestId("disc-send-intervention")).toBeNull();
    expect(await screen.findByLabelText("补充信息")).toBeTruthy();
    expect(apiMock.addDiscussionIntervention).not.toHaveBeenCalled();
  });

  it("ends the round only after confirmation and never shows approval", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 5 });
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(screen.getByTestId("disc-end-round"));
    fireEvent.change(screen.getByLabelText("结束本轮原因"), {
      target: { value: "方向已足够清楚" },
    });
    fireEvent.click(screen.getByTestId("disc-confirm-end-round"));

    await waitFor(() =>
      expect(apiMock.endDiscussionRound).toHaveBeenCalledWith(
        "s1",
        { expected_revision: 5, reason: "方向已足够清楚", confirm: true },
        "bot-a",
      ),
    );
  });

  it("shows manual end as not approved and offers only an explicit new round", async () => {
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      control_revision: 8,
      round_end_reason: { kind: "manual", text: "人工结束", round_no: 1, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.getByTestId("disc-manual-end").textContent).toContain("未自动收敛");
    expect(screen.queryByRole("button", { name: "继续" })).toBeNull();
    fireEvent.click(screen.getByTestId("disc-start-round"));
    fireEvent.click(screen.getByTestId("disc-confirm-start-round"));

    await waitFor(() =>
      expect(apiMock.startDiscussionRound).toHaveBeenCalledWith(
        "s1",
        { expected_revision: 8 },
        "bot-a",
      ),
    );
    await waitFor(() => expect(apiMock.runDiscussion).toHaveBeenCalledWith("s1", "bot-a"));
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

  it("does not render pause/resume once a decision package exists", () => {
    const approval = makeSession({
      status: "converged_pending_human",
      current_round: 2,
      decision_package: DECISION_PACKAGE,
    });
    setHookState({ session: approval, sessions: [approval] });
    const first = renderView();

    // A pause request is a guaranteed no-op while a decision package exists, so
    // the control must not be offered (approval stage is the same state).
    expect(screen.queryByTestId("disc-pause-resume")).toBeNull();
    expect(screen.queryByRole("button", { name: "暂停" })).toBeNull();
    expect(screen.queryByTestId("disc-end-round")).toBeNull();

    first.unmount();
    const running = makeSession({ status: "cross_review" });
    setHookState({ session: running, sessions: [running] });
    renderView();
    expect(screen.getByTestId("disc-pause-resume")).toBeTruthy();
  });

  it("focuses the end-round dialog and closes it with Escape or a backdrop click", () => {
    const session = makeSession({ status: "cross_review", control_revision: 5 });
    setHookState({ session, sessions: [session] });
    renderView();

    fireEvent.click(screen.getByTestId("disc-end-round"));
    const dialog = screen.getByTestId("disc-end-round-dialog");
    expect(document.activeElement).toBe(dialog);

    // Typing must not re-run the open effect and steal focus back to the dialog.
    const reason = screen.getByLabelText("结束本轮原因") as HTMLTextAreaElement;
    reason.focus();
    fireEvent.change(reason, { target: { value: "方向已足够清楚" } });
    expect(document.activeElement).toBe(reason);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("disc-end-round-dialog")).toBeNull();

    fireEvent.click(screen.getByTestId("disc-end-round"));
    fireEvent.click(screen.getByTestId("disc-end-round-dialog").parentElement as HTMLElement);
    expect(screen.queryByTestId("disc-end-round-dialog")).toBeNull();
  });

  it("refreshes and shows a Chinese message when a control action conflicts", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 3 });
    setHookState({ session, sessions: [session] });
    apiMock.pauseDiscussion.mockRejectedValueOnce(
      new ApiError("revision_conflict", { status: 409 }),
    );
    renderView();

    fireEvent.click(screen.getByTestId("disc-pause-resume"));

    await waitFor(() =>
      expect(screen.getByTestId("disc-action-error").textContent).toContain("控制版本冲突"),
    );
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("polls the session while a pause request is pending and stops once paused", async () => {
    vi.useFakeTimers();
    const pausing = makeSession({ status: "cross_review", pause_requested: true, control_revision: 4 });
    setHookState({ session: pausing, sessions: [pausing] });
    const view = renderView();

    expect(screen.getByRole("button", { name: "正在暂停…" })).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    const paused = makeSession({ status: "cross_review", paused: true, control_revision: 5 });
    setHookState({ session: paused, sessions: [paused] });
    view.rerender(element());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4500);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("stops polling when unmounted during a pending pause", async () => {
    vi.useFakeTimers();
    const pausing = makeSession({ status: "cross_review", pause_requested: true, control_revision: 4 });
    setHookState({ session: pausing, sessions: [pausing] });
    const view = renderView();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4500);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("shows the in-flight pause request instead of claiming it is paused", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 4 });
    setHookState({ session, sessions: [session] });
    const pending = deferred<DiscussionSession>();
    apiMock.pauseDiscussion.mockReturnValueOnce(pending.promise);
    renderView();

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    const requesting = await screen.findByRole("button", { name: "正在请求暂停…" });
    expect((requesting as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "继续" })).toBeNull();

    await act(async () => {
      pending.resolve(makeSession({ status: "cross_review", paused: true, control_revision: 5 }));
      await pending.promise;
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "暂停" })).toBeTruthy());
    expect(refresh).toHaveBeenCalled();
  });

  it("submits a pause request only once per click burst", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 4 });
    setHookState({ session, sessions: [session] });
    const pending = deferred<DiscussionSession>();
    apiMock.pauseDiscussion.mockReturnValueOnce(pending.promise);
    renderView();

    const pause = screen.getByTestId("disc-pause-resume");
    fireEvent.click(pause);
    fireEvent.click(pause);
    expect(apiMock.pauseDiscussion).toHaveBeenCalledTimes(1);
    await act(async () => {
      pending.resolve(makeSession({ status: "cross_review", paused: true }));
      await pending.promise;
    });
  });

  it("waits for the safe stop before offering a new round after a manual end", () => {
    const session = makeSession({
      status: "cross_review",
      paused: false,
      pause_requested: true,
      control_revision: 6,
      round_end_reason: { kind: "manual", text: "人工结束", round_no: 1, actor: "bot-a", revision: 6 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.getByTestId("disc-manual-ending").textContent).toContain("正在结束本轮");
    expect(screen.getByTestId("disc-manual-end").textContent).not.toContain("讨论已停止");
    expect(screen.queryByTestId("disc-start-round")).toBeNull();
    expect(screen.queryByRole("button", { name: "继续" })).toBeNull();
    expect(screen.queryByTestId("disc-send-intervention")).toBeNull();
  });

  it("offers the new round only after the manual stop is settled", () => {
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      pause_requested: false,
      current_round: 1,
      control_revision: 8,
      round_end_reason: { kind: "manual", text: "人工结束", round_no: 1, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.getByTestId("disc-manual-end").textContent).toContain("已安全停止");
    expect(screen.queryByTestId("disc-manual-ending")).toBeNull();
    expect((screen.getByTestId("disc-start-round") as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not offer a new round when the round budget is exhausted", () => {
    const base = makeSession();
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      current_round: 3,
      budget: { ...base.budget, max_rounds: 3 },
      control_revision: 8,
      round_end_reason: { kind: "manual", text: "人工结束", round_no: 3, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.queryByTestId("disc-start-round")).toBeNull();
    expect(screen.getByTestId("disc-manual-end").textContent).toContain("轮数预算已用尽");
  });

  it("requires a control revision before a new round can start", () => {
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      current_round: 1,
      round_end_reason: { kind: "manual", text: "", round_no: 1, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.queryByTestId("disc-start-round")).toBeNull();
    expect(screen.getByTestId("disc-manual-end").textContent).toContain("控制版本缺失");
  });

  it("keeps budget_exhausted read-only even with a leftover manual marker", () => {
    const session = makeSession({
      status: "budget_exhausted",
      paused: true,
      current_round: 3,
      round_end_reason: { kind: "manual", text: "", round_no: 3, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    renderView();

    expect(screen.queryByTestId("disc-start-round")).toBeNull();
    expect(screen.queryByTestId("disc-pause-resume")).toBeNull();
    expect(screen.queryByTestId("disc-manual-end")).toBeNull();
    expect(screen.getByTestId("disc-readonly-note").textContent).toContain("预算");
  });

  it("classifies a budget_exhausted conflict without blaming another editor", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 3 });
    setHookState({ session, sessions: [session] });
    apiMock.pauseDiscussion.mockRejectedValueOnce(
      new ApiError("预算已用尽", { status: 409, category: "budget_exhausted" }),
    );
    renderView();

    fireEvent.click(screen.getByTestId("disc-pause-resume"));
    const error = await screen.findByTestId("disc-action-error");
    expect(error.textContent).toContain("预算");
    expect(error.textContent).not.toContain("状态已变化");
    expect(refresh).toHaveBeenCalled();
  });

  it("explains a manual_end_not_finalized detail without inventing a category", async () => {
    const session = makeSession({ status: "cross_review", control_revision: 3 });
    setHookState({ session, sessions: [session] });
    apiMock.pauseDiscussion.mockRejectedValueOnce(
      new ApiError("manual_end_not_finalized: round is still stopping", {
        status: 409,
        category: "invalid_status",
      }),
    );
    renderView();

    fireEvent.click(screen.getByTestId("disc-pause-resume"));
    const error = await screen.findByTestId("disc-action-error");
    expect(error.textContent).toContain("人工结束");
    expect(error.textContent).toContain("安全检查点");
    expect(refresh).toHaveBeenCalled();
  });

  it("does not start the run when rounds/start is rejected", async () => {
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      current_round: 1,
      control_revision: 8,
      round_end_reason: { kind: "manual", text: "", round_no: 1, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    apiMock.startDiscussionRound.mockRejectedValueOnce(
      new ApiError("invalid_status", { status: 409, category: "invalid_status" }),
    );
    renderView();

    fireEvent.click(screen.getByTestId("disc-start-round"));
    fireEvent.click(screen.getByTestId("disc-confirm-start-round"));

    await waitFor(() => expect(screen.getByTestId("disc-action-error")).toBeTruthy());
    expect(apiMock.runDiscussion).not.toHaveBeenCalled();
  });

  it("reports a created-but-not-started round without starting a second one", async () => {
    const session = makeSession({
      status: "converged_pending_human",
      paused: true,
      current_round: 1,
      control_revision: 8,
      round_end_reason: { kind: "manual", text: "", round_no: 1, actor: "bot-a", revision: 8 },
    });
    setHookState({ session, sessions: [session] });
    apiMock.runDiscussion.mockRejectedValueOnce(new Error("driver unavailable"));
    renderView();

    fireEvent.click(screen.getByTestId("disc-start-round"));
    fireEvent.click(screen.getByTestId("disc-confirm-start-round"));

    const error = await screen.findByTestId("disc-action-error");
    expect(error.textContent).toContain("新轮已创建");
    expect(apiMock.startDiscussionRound).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalled();
  });

  it("does not leak a stale action outcome into a switched session", async () => {
    const first = makeSession({ session_id: "s1", status: "cross_review", control_revision: 1 });
    setHookState({ session: first, sessions: [first] });
    const pending = deferred<DiscussionSession>();
    apiMock.pauseDiscussion.mockReturnValueOnce(pending.promise);
    const view = renderView();

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    const second = makeSession({
      session_id: "s2",
      project_id: "proj-2",
      status: "cross_review",
      control_revision: 2,
    });
    setHookState({ session: second, sessions: [second] });
    view.rerender(element());

    await act(async () => {
      pending.resolve(makeSession({ session_id: "s1", status: "cross_review", paused: true }));
      await pending.promise;
    });
    expect(screen.queryByTestId("disc-action-error")).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("hides the control bar from a non-leader actor", () => {
    const session = makeSession({ status: "cross_review" });
    setHookState({ session, sessions: [session] });
    renderView("bot-b");

    expect(screen.queryByTestId("disc-pause-resume")).toBeNull();
    expect(screen.queryByRole("button", { name: "终止" })).toBeNull();
    expect(screen.getByTestId("disc-control-readonly").textContent).toContain(
      "只有本场讨论的 Leader",
    );
  });

  it("keeps the supplement text when the request fails", async () => {
    const session = makeSession({ status: "cross_review", paused: true, control_revision: 7 });
    setHookState({ session, sessions: [session] });
    apiMock.supplementDiscussion.mockRejectedValueOnce(new Error("网络中断"));
    renderView();

    fireEvent.change(await screen.findByLabelText("补充信息"), { target: { value: "保留的补充" } });
    fireEvent.click(screen.getByRole("button", { name: /发送补充/ }));

    await waitFor(() => expect(screen.getByTestId("disc-action-error")).toBeTruthy());
    expect((screen.getByLabelText("补充信息") as HTMLTextAreaElement).value).toBe("保留的补充");
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
    expect(screen.getAllByLabelText("方案正文")[0].textContent).toBe("方案正文");
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByLabelText("方案正文")).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "展开方案" })[1]);
    await waitFor(() => expect(screen.getAllByLabelText("方案正文").length).toBe(1));
    expect(screen.getAllByLabelText("方案正文")[0].textContent).toBe("方案正文");

    expect(apiMock.discussionProposals).toHaveBeenCalledTimes(1);
    expect(apiMock.discussionProposals).toHaveBeenCalledWith("s1", "bot-a");
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
