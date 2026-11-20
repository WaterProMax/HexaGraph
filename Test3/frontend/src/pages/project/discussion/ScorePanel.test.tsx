import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  ReviewBallot,
} from "../../../api/types";
import { ScorePanel } from "./ScorePanel";

const BOTS: BotInstance[] = [
  {
    bot_id: "bot-a",
    display_name: "林可",
    role_template: "pm",
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
  {
    bot_id: "bot-c",
    display_name: "郑一",
    role_template: "architect",
    provider_ref: "dashscope",
    model: "qwen-plus",
    slot: "architect",
    secret_ref: "DASHSCOPE_API_KEY",
    tool_policy: [],
    skill_bindings: [],
    token_budget: null,
    status: "active",
  },
];

function makeSession(overrides: Record<string, unknown> = {}): DiscussionSession {
  return {
    session_id: "s1",
    project_id: "p1",
    leader_bot_id: "bot-a",
    participant_bot_ids: ["bot-a", "bot-b", "bot-c"],
    status: "cross_review",
    current_round: 2,
    budget: {
      max_rounds: 3,
      max_tokens: null,
      max_wallclock_seconds: null,
      score_gap_threshold: 5,
    },
    requirement_snapshot_hash: "hash",
    decision_package: null,
    requirement_text: "做一个登录页",
    previous_session_id: null,
    resolution_comment: "",
    paused: false,
    created_at: "2026-11-20T10:00:00Z",
    ...overrides,
  } as DiscussionSession;
}

function proposalMessage(seq: number, proposalId: string, botId: string): DiscussionMessage {
  return {
    session_id: "s1",
    seq,
    kind: "proposal",
    bot_id: botId,
    round: 2,
    payload: { proposal_id: proposalId, chars: 500, truncated: false, round: 2 },
    created_at: "2026-11-20T10:00:00Z",
  } as DiscussionMessage;
}

const MESSAGES: DiscussionMessage[] = [
  proposalMessage(1, "prop-1", "bot-a"),
  proposalMessage(2, "prop-2", "bot-b"),
];

function ballot(
  reviewer: string,
  proposalId: string,
  score: number,
  gates: Record<string, boolean> = {
    coverage: true,
    conflicts_closed_or_recorded: true,
    evidence_complete: true,
  },
): ReviewBallot {
  return {
    reviewer_bot_id: reviewer,
    proposal_id: proposalId,
    scores: { value: score, feasibility: score, testability: score, clarity: score },
    score_justification: {},
    hard_gate_results: gates,
    dissent_items: [],
  };
}

const EVIDENCE_FAIL = {
  coverage: true,
  conflicts_closed_or_recorded: true,
  evidence_complete: false,
};

const REVIEWS: ReviewBallot[] = [
  ballot("bot-c", "prop-1", 2.5, EVIDENCE_FAIL),
  ballot("bot-c", "prop-2", 2),
  ballot("bot-b", "prop-2", 3, EVIDENCE_FAIL),
];

function renderPanel(
  overrides: {
    session?: DiscussionSession;
    reviews?: ReviewBallot[];
    messages?: DiscussionMessage[];
    busy?: boolean;
    onPause?: () => void;
    onResume?: (skipBotIds?: string[]) => void;
    onTerminate?: () => void;
  } = {},
) {
  const onPause = overrides.onPause ?? vi.fn();
  const onResume = overrides.onResume ?? vi.fn();
  const onTerminate = overrides.onTerminate ?? vi.fn();
  const view = render(
    <ScorePanel
      session={overrides.session ?? makeSession()}
      reviews={overrides.reviews ?? REVIEWS}
      messages={overrides.messages ?? MESSAGES}
      bots={BOTS}
      busy={overrides.busy}
      onPause={onPause}
      onResume={onResume}
      onTerminate={onTerminate}
    />,
  );
  return { ...view, onPause, onResume, onTerminate };
}

function rowCells(proposalId: string): string[] {
  const row = document.querySelector(`tr[data-proposal-id="${proposalId}"]`) as HTMLElement;
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent || "");
}

afterEach(cleanup);

describe("ScorePanel scoring table", () => {
  it("shows the round and one column per reviewer with averages", () => {
    renderPanel();
    const panel = screen.getByTestId("disc-score-panel");
    expect(panel.textContent).toContain("第 2 / 3 轮");

    expect(rowCells("prop-1")).toEqual(["10", "—", "10.0"]);
    expect(rowCells("prop-2")).toEqual(["8", "12", "10.0"]);

    const rowHeader = document.querySelector(
      'tr[data-proposal-id="prop-1"] th[scope="row"]',
    ) as HTMLElement;
    expect(rowHeader.textContent).toContain("林可");
    expect(rowHeader.textContent).toContain("prop-1");
  });

  it("marks a score gap inside the threshold as ok", () => {
    renderPanel();
    const gap = screen.getByTestId("disc-gap");
    expect(gap.className).toContain("is-ok");
    expect(gap.className).not.toContain("is-over");
    expect(gap.textContent).toContain("分差 0 / 阈值 5");
  });

  it("marks a score gap above the threshold as over", () => {
    renderPanel({
      session: makeSession({
        budget: {
          max_rounds: 3,
          max_tokens: null,
          max_wallclock_seconds: null,
          score_gap_threshold: 1,
        },
      }),
      reviews: [ballot("bot-c", "prop-1", 2.5), ballot("bot-c", "prop-2", 2)],
    });
    const gap = screen.getByTestId("disc-gap");
    expect(gap.className).toContain("is-over");
    expect(gap.textContent).toContain("分差 2 / 阈值 1");
  });

  it("says only hard gates when the threshold is null", () => {
    renderPanel({
      session: makeSession({
        budget: {
          max_rounds: 3,
          max_tokens: null,
          max_wallclock_seconds: null,
          score_gap_threshold: null,
        },
      }),
    });
    const gap = screen.getByTestId("disc-gap");
    expect(gap.textContent).toBe("仅硬门槛");
    expect(gap.className).toContain("is-muted");
  });

  it("counts hard gates that every ballot passed", () => {
    renderPanel();
    const gates = screen.getByTestId("disc-gates");
    expect(gates.textContent).toContain("2/3");
    const evidence = gates.querySelector('[data-gate="evidence_complete"]') as HTMLElement;
    expect(evidence.className).toContain("is-over");
    expect(evidence.textContent).toContain("未通过");
    const coverage = gates.querySelector('[data-gate="coverage"]') as HTMLElement;
    expect(coverage.className).toContain("is-ok");
  });

  it("shows an empty state without votes", () => {
    renderPanel({ messages: [], reviews: [] });
    expect(screen.getByTestId("disc-score-panel").textContent).toContain("还没有评分票");
  });
});

describe("ScorePanel controls", () => {
  it("requires a confirmation before terminating", () => {
    const onTerminate = vi.fn();
    renderPanel({ onTerminate });

    fireEvent.click(screen.getByRole("button", { name: "终止" }));
    expect(onTerminate).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("确认终止");

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onTerminate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "终止" }));
    fireEvent.click(screen.getByRole("button", { name: "确认终止" }));
    expect(onTerminate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes the confirmation with Escape", () => {
    const onTerminate = vi.fn();
    renderPanel({ onTerminate });
    fireEvent.click(screen.getByRole("button", { name: "终止" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onTerminate).not.toHaveBeenCalled();
  });

  it("offers retry and skip after a bot failure", () => {
    const onResume = vi.fn();
    const failure: DiscussionMessage = {
      session_id: "s1",
      seq: 3,
      kind: "system",
      bot_id: "bot-b",
      round: 2,
      payload: { event: "bot_failed", bot_id: "bot-b", error_category: "timeout", text: "周明 调用超时" },
      created_at: "2026-11-20T10:01:00Z",
    } as DiscussionMessage;
    renderPanel({ messages: [...MESSAGES, failure], onResume });

    const failed = screen.getByTestId("disc-bot-failed");
    expect(failed.textContent).toContain("周明");
    expect(failed.textContent).toContain("timeout");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onResume).toHaveBeenNthCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "跳过此 Bot" }));
    expect(onResume).toHaveBeenNthCalledWith(2, ["bot-b"]);
  });

  it("switches between pause and resume with the session state", () => {
    const onPause = vi.fn();
    const onResume = vi.fn();
    const { rerender } = renderPanel({ onPause, onResume });

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    expect(onPause).toHaveBeenCalledTimes(1);

    rerender(
      <ScorePanel
        session={makeSession({ paused: true })}
        reviews={REVIEWS}
        messages={MESSAGES}
        bots={BOTS}
        onPause={onPause}
        onResume={onResume}
        onTerminate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it("disables the controls while busy", () => {
    renderPanel({ busy: true });
    expect((screen.getByRole("button", { name: "暂停" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "终止" }) as HTMLButtonElement).disabled).toBe(true);
  });
});