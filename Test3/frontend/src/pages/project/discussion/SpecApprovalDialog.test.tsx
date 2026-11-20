import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { ApiError } from "../../../api/client";
import type { DiscussionSession, ReviewBallot } from "../../../api/types";
import { SpecApprovalDialog } from "./SpecApprovalDialog";

const apiMock = vi.hoisted(() => ({
  resolveDiscussion: vi.fn(),
  createDiscussionSession: vi.fn(),
  runDiscussion: vi.fn(),
}));

vi.mock("../../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, ...apiMock },
  };
});

const baseSession: DiscussionSession = {
  session_id: "session-1",
  project_id: "project-1",
  leader_bot_id: "bot-leader",
  participant_bot_ids: ["bot-leader", "bot-a", "bot-b"],
  status: "converged_pending_human",
  current_round: 2,
  budget: {
    max_rounds: 3,
    max_tokens: null,
    max_wallclock_seconds: null,
    score_gap_threshold: 2,
  },
  requirement_snapshot_hash: "snap-hash",
  decision_package: {
    decision_id: "decision-1",
    session_id: "session-1",
    requirement_snapshot_hash: "snap-hash",
    proposal_ids: ["p1", "p2"],
    dissent_items: ["风险 X 未闭环", "边界条件待确认"],
    hard_gate_summary: {
      coverage: true,
      conflicts_closed_or_recorded: false,
      evidence_complete: true,
    },
    body_md: "# 需求规格\n\n正文第一段",
    sha256: "abcdef1234567890",
  },
  requirement_text: "原始需求：多 Bot 讨论",
  previous_session_id: null,
  resolution_comment: null,
  paused: false,
  created_at: "2026-11-20T10:00:00Z",
};

function makeSession(overrides: Partial<DiscussionSession> = {}) {
  return { ...baseSession, ...overrides };
}

const ballots: ReviewBallot[] = [
  {
    reviewer_bot_id: "bot-a",
    proposal_id: "p1",
    scores: { coverage: 4, evidence: 3 },
    score_justification: {},
    hard_gate_results: {
      coverage: true,
      conflicts_closed_or_recorded: true,
      evidence_complete: true,
    },
    dissent_items: [],
  },
  {
    reviewer_bot_id: "bot-b",
    proposal_id: "p1",
    scores: { coverage: 3, evidence: 2 },
    score_justification: {},
    hard_gate_results: {
      coverage: true,
      conflicts_closed_or_recorded: false,
      evidence_complete: true,
    },
    dissent_items: [],
  },
  {
    reviewer_bot_id: "bot-a",
    proposal_id: "p2",
    scores: { coverage: 2, evidence: 2 },
    score_justification: {},
    hard_gate_results: {
      coverage: true,
      conflicts_closed_or_recorded: true,
      evidence_complete: false,
    },
    dissent_items: [],
  },
];

function renderDialog(overrides: Partial<ComponentProps<typeof SpecApprovalDialog>> = {}) {
  const props = {
    open: true,
    projectId: "project-1",
    actorBotId: "bot-leader",
    session: makeSession(),
    reviews: ballots,
    onClose: vi.fn(),
    onApproved: vi.fn(),
    onRestarted: vi.fn(),
    ...overrides,
  };
  render(<SpecApprovalDialog {...props} />);
  return props;
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(cleanup);

describe("SpecApprovalDialog", () => {
  it("approves with resolveDiscussion without run_id and reports the updated session", async () => {
    const updated = makeSession({ status: "approved" });
    apiMock.resolveDiscussion.mockResolvedValue(updated);
    const props = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "通过，进入任务拆解" }));

    await waitFor(() => expect(props.onApproved).toHaveBeenCalledWith(updated));
    expect(apiMock.resolveDiscussion).toHaveBeenCalledWith(
      "session-1",
      { decision: "approved" },
      "bot-leader",
    );
    const body = apiMock.resolveDiscussion.mock.calls[0][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("run_id");
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("requires a non-blank reject comment, then resolves, recreates and runs the next round", async () => {
    const created = makeSession({
      session_id: "session-2",
      status: "draft",
      previous_session_id: "session-1",
      created_at: "2026-11-20T11:00:00Z",
    });
    apiMock.resolveDiscussion.mockResolvedValue(makeSession({ status: "rejected" }));
    apiMock.createDiscussionSession.mockResolvedValue(created);
    apiMock.runDiscussion.mockResolvedValue({});
    const props = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "打回重新讨论" }));
    const input = screen.getByLabelText("打回意见") as HTMLTextAreaElement;
    const submit = screen.getByRole("button", { name: "确认打回并重新讨论" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "   " } });
    expect(submit.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "  补充验收标准  " } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);

    await waitFor(() => expect(props.onRestarted).toHaveBeenCalledWith(created));
    expect(apiMock.resolveDiscussion).toHaveBeenCalledWith(
      "session-1",
      { decision: "rejected", comment: "补充验收标准" },
      "bot-leader",
    );
    expect(apiMock.createDiscussionSession).toHaveBeenCalledWith(
      "project-1",
      {
        leader_bot_id: "bot-leader",
        participant_bot_ids: ["bot-leader", "bot-a", "bot-b"],
        requirement_snapshot: "原始需求：多 Bot 讨论",
        previous_session_id: "session-1",
      },
      "bot-leader",
    );
    expect(apiMock.runDiscussion).toHaveBeenCalledWith("session-2", "bot-leader");

    const resolveOrder = apiMock.resolveDiscussion.mock.invocationCallOrder[0];
    const createOrder = apiMock.createDiscussionSession.mock.invocationCallOrder[0];
    const runOrder = apiMock.runDiscussion.mock.invocationCallOrder[0];
    expect(resolveOrder).toBeLessThan(createOrder);
    expect(createOrder).toBeLessThan(runOrder);
  });

  it("closes without deciding when the close button is used", () => {
    const props = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(apiMock.resolveDiscussion).not.toHaveBeenCalled();
  });

  it("closes on Escape without deciding", () => {
    const props = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(apiMock.resolveDiscussion).not.toHaveBeenCalled();
  });

  it("shows a Chinese ApiError message inside the dialog and stays open", async () => {
    apiMock.resolveDiscussion.mockRejectedValue(
      new ApiError("规格版本已变化，请刷新后重试", { status: 409 }),
    );
    const props = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "通过，进入任务拆解" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("规格版本已变化，请刷新后重试");
    expect(props.onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId("disc-approval-dialog")).toBeTruthy();
    expect(props.onApproved).not.toHaveBeenCalled();
  });

  it("shows a forbidden message and keeps the dialog open on 403", async () => {
    apiMock.resolveDiscussion.mockRejectedValue(
      new ApiError("只有会话 Leader 可以批准或打回", { status: 403, category: "forbidden" }),
    );
    const props = renderDialog({ actorBotId: "bot-a" });

    fireEvent.click(screen.getByRole("button", { name: "通过，进入任务拆解" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("只有会话 Leader 可以批准或打回");
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.onApproved).not.toHaveBeenCalled();
    expect(props.onRestarted).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("renders the summary chips, dissent items and score table", () => {
    renderDialog();

    expect(screen.getByText("第 2 轮")).toBeTruthy();
    expect(screen.getByText("分差 2.0 / 阈值 2.0")).toBeTruthy();
    expect(screen.getByText("硬门槛 1/3")).toBeTruthy();
    expect(screen.getByText("未解决分歧 2 条")).toBeTruthy();

    expect(screen.getByText("未解决分歧（2）")).toBeTruthy();
    expect(screen.getByText("风险 X 未闭环")).toBeTruthy();
    expect(screen.getByText("边界条件待确认")).toBeTruthy();
    expect(screen.getByText("正文第一段")).toBeTruthy();

    const table = screen.getByRole("table");
    expect(within(table).getByText("作者")).toBeTruthy();
    expect(within(table).getByText("平均总分")).toBeTruthy();
    expect(within(table).getByText("票数")).toBeTruthy();
    expect(within(table).getByText("p1")).toBeTruthy();
    expect(within(table).getByText("6.0")).toBeTruthy();
    expect(within(table).getByText("p2")).toBeTruthy();
    expect(within(table).getByText("4.0")).toBeTruthy();
  });

  it("renders nothing when closed", () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId("disc-approval-dialog")).toBeNull();
  });
});