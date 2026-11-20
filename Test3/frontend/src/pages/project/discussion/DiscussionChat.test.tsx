import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  DiscussionSessionStatus,
  DiscussionTimelineItem,
} from "../../../api/types";
import { DiscussionChat } from "./DiscussionChat";
import { isProposalSealed } from "./MessageBubble";

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
];

function message(
  seq: number,
  kind: DiscussionMessage["kind"],
  extra: Partial<DiscussionMessage> = {},
): DiscussionMessage {
  return {
    session_id: "s1",
    seq,
    kind,
    bot_id: "bot-a",
    round: 1,
    payload: {},
    created_at: "2026-11-20T10:00:00Z",
    ...extra,
  } as DiscussionMessage;
}

function proposal(seq = 1, round = 1, proposalId = "prop-1"): DiscussionTimelineItem {
  return {
    type: "message",
    message: message(seq, "proposal", {
      round,
      payload: { proposal_id: proposalId, chars: 842, truncated: false, round },
    }),
  };
}

function session(status: DiscussionSessionStatus, currentRound = 1): DiscussionSession {
  return {
    session_id: "s1",
    project_id: "p-1",
    leader_bot_id: "bot-a",
    participant_bot_ids: ["bot-a", "bot-b"],
    status,
    current_round: currentRound,
    budget: { max_rounds: 3, max_tokens: null, max_wallclock_seconds: null, score_gap_threshold: 2 },
    requirement_snapshot_hash: "hash",
    decision_package: null,
    requirement_text: "做一个座位预约工具",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-20T10:00:00Z",
  };
}

const BODY = "## 方案正文\n先用邮箱登录，再加验证码。";

function loadSpy(value: string = BODY) {
  return vi.fn(async (_proposalId: string): Promise<string> => value);
}

afterEach(cleanup);

describe("DiscussionChat", () => {
  it("shows an empty state before any message arrives", () => {
    render(
      <DiscussionChat
        timeline={[]}
        bots={BOTS}
        stage="idea"
        session={null}
        loadProposalBody={loadSpy()}
      />,
    );
    expect(screen.getByTestId("disc-chat").textContent).toContain("还没有消息");
  });

  it("keeps proposal bodies sealed during the independent stage", () => {
    const loadProposalBody = loadSpy();
    render(
      <DiscussionChat
        timeline={[proposal()]}
        bots={BOTS}
        stage="independent"
        session={session("round1_independent")}
        loadProposalBody={loadProposalBody}
      />,
    );
    const bubble = screen.getByTestId("disc-bubble-proposal");
    expect(bubble.textContent).toContain("已提交方案（内容已封存）");
    expect(bubble.textContent).toContain("提交了方案 · 第 1 轮");
    expect(bubble.textContent).toContain("842 字");
    expect(screen.queryByText("展开方案")).toBeNull();
    expect(loadProposalBody).not.toHaveBeenCalled();
  });

  it("loads an unsealed proposal body once and caches it", async () => {
    const loadProposalBody = loadSpy();
    render(
      <DiscussionChat
        timeline={[proposal()]}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadProposalBody}
      />,
    );
    fireEvent.click(screen.getByText("展开方案"));
    expect(await screen.findByText(/先用邮箱登录/)).toBeTruthy();
    expect(loadProposalBody).toHaveBeenCalledTimes(1);
    expect(loadProposalBody).toHaveBeenCalledWith("prop-1");

    fireEvent.click(screen.getByText("收起方案"));
    expect(screen.queryByText(/先用邮箱登录/)).toBeNull();
    fireEvent.click(screen.getByText("展开方案"));
    expect(screen.getByText(/先用邮箱登录/)).toBeTruthy();
    expect(loadProposalBody).toHaveBeenCalledTimes(1);
  });

  it("offers a retry when the body request fails", async () => {
    let fail = true;
    const loadProposalBody = vi.fn(async (_proposalId: string): Promise<string> => {
      if (fail) throw new Error("boom");
      return "恢复后的正文";
    });
    render(
      <DiscussionChat
        timeline={[proposal()]}
        bots={BOTS}
        stage="approval"
        session={session("converged_pending_human")}
        loadProposalBody={loadProposalBody}
      />,
    );
    fireEvent.click(screen.getByText("展开方案"));
    expect(await screen.findByText("正文加载失败，重试")).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByText("正文加载失败，重试"));
    expect(await screen.findByText("恢复后的正文")).toBeTruthy();
    expect(loadProposalBody).toHaveBeenCalledTimes(2);
  });

  it("marks a truncated proposal", () => {
    const truncated: DiscussionTimelineItem = {
      type: "message",
      message: message(2, "proposal", {
        payload: { proposal_id: "prop-2", chars: 9000, truncated: true, round: 2 },
      }),
    };
    render(
      <DiscussionChat
        timeline={[truncated]}
        bots={BOTS}
        stage="independent"
        session={session("round1_independent")}
        loadProposalBody={loadSpy()}
      />,
    );
    expect(screen.getByTestId("disc-bubble-proposal").textContent).toContain("已截断");
  });

  it("renders system, proposal, review and leader bubbles", () => {
    const timeline: DiscussionTimelineItem[] = [
      {
        type: "message",
        message: message(1, "system", {
          bot_id: null,
          payload: { event: "bot_skipped", text: "已跳过 周明 的评审" },
        }),
      },
      proposal(2),
      {
        type: "message",
        message: message(3, "review", {
          bot_id: "bot-b",
          payload: {
            proposal_id: "prop-1",
            reviewer_bot_id: "bot-b",
            total: 8,
            scores: { value: 2, feasibility: 2, testability: 2, clarity: 2 },
            hard_gate_results: {
              coverage: true,
              conflicts_closed_or_recorded: true,
              evidence_complete: false,
            },
            summary: "缺失败路径用例",
          },
        }),
      },
      {
        type: "message",
        message: message(4, "leader", {
          payload: { action: "request_revision", text: "请补充分支流程" },
        }),
      },
    ];

    render(
      <DiscussionChat
        timeline={timeline}
        bots={BOTS}
        stage="leader"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );

    const chat = screen.getByTestId("disc-chat");
    expect(chat.textContent).toContain("已跳过 周明 的评审");
    expect(chat.textContent).toContain("已跳过 Bot");
    expect(chat.textContent).toContain("提交了方案 · 第 1 轮");

    const review = screen.getByTestId("disc-bubble-review");
    expect(review.textContent).toContain("周明");
    expect(review.textContent).toContain("总分 8");
    expect(review.textContent).toContain("用户价值");
    expect(review.textContent).toContain("清晰度");
    expect(review.textContent).toContain("证据完整");
    expect(review.textContent).toContain("未通过");
    expect(review.textContent).toContain("缺失败路径用例");

    const leader = screen.getByTestId("disc-bubble-leader");
    expect(leader.textContent).toContain("要求再改");
    expect(leader.textContent).toContain("请补充分支流程");
  });

  it("falls back to a placeholder avatar for unknown bots", () => {
    const timeline: DiscussionTimelineItem[] = [
      {
        type: "message",
        message: message(1, "leader", {
          bot_id: "bot-missing",
          payload: { action: "accept", text: "接受方案" },
        }),
      },
    ];
    render(
      <DiscussionChat
        timeline={timeline}
        bots={BOTS}
        stage="leader"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    const avatar = screen.getByTestId("bot-avatar");
    expect(avatar.getAttribute("data-bot-id")).toBe("bot-missing");
    expect(screen.getByTestId("disc-bubble-leader").textContent).toContain("接受");
  });

  it("renders a divider with its text", () => {
    const timeline: DiscussionTimelineItem[] = [
      { type: "divider", key: "s2", text: "第 2 次讨论 · 你的意见：补上边界用例" },
    ];
    render(
      <DiscussionChat
        timeline={timeline}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    const divider = screen.getByTestId("disc-divider");
    expect(divider.textContent).toContain("第 2 次讨论 · 你的意见：补上边界用例");
    expect(divider.getAttribute("role")).toBe("separator");
  });
});

describe("isProposalSealed", () => {
  it("never seals without a session", () => {
    expect(isProposalSealed(null, 1)).toBe(false);
  });

  it("seals the current round during the blind independent round", () => {
    const current = session("round1_independent", 1);
    expect(isProposalSealed(current, 1)).toBe(true);
    expect(isProposalSealed(current, 2)).toBe(false);
  });

  it("seals only the open revision round", () => {
    const current = session("round_n_revise", 2);
    expect(isProposalSealed(current, 2)).toBe(true);
    expect(isProposalSealed(current, 1)).toBe(false);
  });

  it("unseals every round from cross review onwards", () => {
    expect(isProposalSealed(session("cross_review", 2), 1)).toBe(false);
    expect(isProposalSealed(session("cross_review", 2), 2)).toBe(false);
    expect(isProposalSealed(session("converged_pending_human", 2), 2)).toBe(false);
  });
});

describe("DiscussionChat proposal sealing by round", () => {
  it("seals the open revision round but reveals the previous round", async () => {
    const loadProposalBody = loadSpy();
    render(
      <DiscussionChat
        timeline={[proposal(1, 1, "prop-r1"), proposal(2, 2, "prop-r2")]}
        bots={BOTS}
        stage="revise"
        session={session("round_n_revise", 2)}
        loadProposalBody={loadProposalBody}
      />,
    );

    const bubbles = screen.getAllByTestId("disc-bubble-proposal");
    expect(bubbles).toHaveLength(2);
    expect(bubbles[1].textContent).toContain("提交了方案 · 第 2 轮");
    expect(bubbles[1].textContent).toContain("已提交方案（内容已封存）");
    expect(within(bubbles[1]).queryByText("展开方案")).toBeNull();
    expect(within(bubbles[0]).queryByText("展开方案")).toBeTruthy();
    expect(loadProposalBody).not.toHaveBeenCalled();

    fireEvent.click(within(bubbles[0]).getByText("展开方案"));
    expect(await within(bubbles[0]).findByText(/先用邮箱登录/)).toBeTruthy();
    expect(loadProposalBody).toHaveBeenCalledTimes(1);
    expect(loadProposalBody).toHaveBeenCalledWith("prop-r1");
  });

  it("reveals both rounds once cross review starts", async () => {
    const loadProposalBody = loadSpy();
    render(
      <DiscussionChat
        timeline={[proposal(1, 1, "prop-r1"), proposal(2, 2, "prop-r2")]}
        bots={BOTS}
        stage="review"
        session={session("cross_review", 2)}
        loadProposalBody={loadProposalBody}
      />,
    );

    const bubbles = screen.getAllByTestId("disc-bubble-proposal");
    expect(within(bubbles[0]).getByText("展开方案")).toBeTruthy();
    expect(within(bubbles[1]).getByText("展开方案")).toBeTruthy();

    fireEvent.click(within(bubbles[0]).getByText("展开方案"));
    fireEvent.click(within(bubbles[1]).getByText("展开方案"));
    expect(await screen.findAllByText(/先用邮箱登录/)).toHaveLength(2);
    expect(loadProposalBody).toHaveBeenCalledTimes(2);
    expect(loadProposalBody).toHaveBeenCalledWith("prop-r1");
    expect(loadProposalBody).toHaveBeenCalledWith("prop-r2");
  });
});

describe("DiscussionChat auto-scroll", () => {
  function mockScroll(el: HTMLElement, initialTop: number, scrollHeight = 1000, clientHeight = 300) {
    let top = initialTop;
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => scrollHeight });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => clientHeight });
    Object.defineProperty(el, "scrollTop", {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = value;
      },
    });
    return () => top;
  }

  it("follows new messages while the user is already at the bottom", () => {
    const { rerender } = render(
      <DiscussionChat
        timeline={[proposal(1)]}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    const chat = screen.getByTestId("disc-chat");
    const readTop = mockScroll(chat, 700);
    fireEvent.scroll(chat);

    rerender(
      <DiscussionChat
        timeline={[proposal(1), proposal(2)]}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    expect(readTop()).toBe(1000);
  });

  it("does not yank the user down after they scrolled up", () => {
    const { rerender } = render(
      <DiscussionChat
        timeline={[proposal(1)]}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    const chat = screen.getByTestId("disc-chat");
    const readTop = mockScroll(chat, 100);
    fireEvent.scroll(chat);

    rerender(
      <DiscussionChat
        timeline={[proposal(1), proposal(2)]}
        bots={BOTS}
        stage="review"
        session={session("cross_review")}
        loadProposalBody={loadSpy()}
      />,
    );
    expect(readTop()).toBe(100);
  });
});