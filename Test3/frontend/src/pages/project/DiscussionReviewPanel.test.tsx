import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ReviewBallot } from "../../api/types";
import { DiscussionReviewPanel } from "./DiscussionReviewPanel";

const ballot: ReviewBallot = {
  reviewer_bot_id: "bot-2",
  proposal_id: "proposal-1",
  scores: { coverage: 3, evidence: 2 },
  score_justification: { coverage: "覆盖主路径", evidence: "附了命令输出" },
  hard_gate_results: {
    coverage: true,
    conflicts_closed_or_recorded: true,
    evidence_complete: false,
  },
  dissent_items: ["缺边界用例"],
};

afterEach(cleanup);

describe("DiscussionReviewPanel", () => {
  it("lists hard gates, justifications and dissent", () => {
    render(<DiscussionReviewPanel ballots={[ballot]} dissentItems={["风险 X 未闭环"]} />);
    const panel = screen.getByTestId("discussion-review-panel");
    expect(panel.textContent).toContain("覆盖");
    expect(panel.textContent).toContain("证据完整");
    expect(panel.textContent).toContain("未通过");
    expect(panel.textContent).toContain("覆盖主路径");
    expect(panel.textContent).toContain("缺边界用例");
    expect(panel.textContent).toContain("风险 X 未闭环");
  });

  it("never claims a score-spread automatic pass", () => {
    render(<DiscussionReviewPanel ballots={[ballot]} dissentItems={[]} />);
    const text = screen.getByTestId("discussion-review-panel").textContent || "";
    expect(text).not.toMatch(/分差.*自动通过/);
    expect(text).not.toMatch(/自动通过/);
  });

  it("shows an empty state for no ballots", () => {
    render(<DiscussionReviewPanel ballots={[]} dissentItems={[]} />);
    expect(screen.getByTestId("discussion-review-panel").textContent).toContain("还没有评审票");
  });
});
describe("review cards with a bot directory", () => {
  const reviewer = {
    bot_id: "bot-2",
    display_name: "周明",
    role_template: "pm",
    provider_ref: "dashscope",
    model: "qwen-plus",
    slot: "coder",
    secret_ref: "DASHSCOPE_API_KEY",
    tool_policy: [],
    skill_bindings: [],
    token_budget: 40000,
    status: "active" as const,
  };

  it("shows the reviewer avatar and display name instead of the raw id", () => {
    render(<DiscussionReviewPanel ballots={[ballot]} dissentItems={[]} bots={[reviewer]} />);
    const panel = screen.getByTestId("discussion-review-panel");
    expect(panel.textContent).toContain("周明");
    expect(screen.getByTestId("bot-avatar").getAttribute("data-bot-id")).toBe("bot-2");
    expect(panel.textContent).toContain("覆盖");
    expect(panel.textContent).not.toMatch(/分差.*自动通过/);
  });
});
