import { describe, expect, it } from "vitest";
import type { DiscussionSession, DiscussionSessionStatus } from "../../../api/types";
import { deriveStage, type DiscussionStage } from "./deriveStage";

function session(status: DiscussionSessionStatus, overrides: Partial<DiscussionSession> = {}): DiscussionSession {
  return {
    session_id: "s-1",
    project_id: "p-1",
    leader_bot_id: "bot-leader",
    participant_bot_ids: ["bot-leader", "bot-2"],
    status,
    current_round: 1,
    budget: { max_rounds: 3, max_tokens: null, max_wallclock_seconds: null, score_gap_threshold: 2 },
    requirement_snapshot_hash: "hash",
    decision_package: null,
    requirement_text: "做一个座位预约工具",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-20T08:00:00+00:00",
    ...overrides,
  };
}

const decisionPackage = {
  decision_id: "d-1",
  session_id: "s-1",
  requirement_snapshot_hash: "hash",
  proposal_ids: ["prop-1"],
  dissent_items: [],
  hard_gate_summary: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: true },
  body_md: "# 需求规格",
  sha256: "abc",
};

describe("deriveStage", () => {
  it("starts at idea when there is no session", () => {
    expect(deriveStage(null)).toBe("idea");
  });

  it("maps draft to idea", () => {
    expect(deriveStage(session("draft"))).toBe("idea");
  });

  it("maps grouping to independent", () => {
    expect(deriveStage(session("grouping"))).toBe("independent");
  });

  it("maps the blind first round to independent", () => {
    expect(deriveStage(session("round1_independent"))).toBe("independent");
  });

  it("maps cross_review to review", () => {
    expect(deriveStage(session("cross_review"))).toBe("review");
  });

  it("maps round_n_revise to revise", () => {
    expect(deriveStage(session("round_n_revise"))).toBe("revise");
  });

  it("includes revise in the discussion stage union", () => {
    const stage: DiscussionStage = "revise";
    expect(stage).toBe("revise");
  });

  it("maps converged without a decision package to leader", () => {
    expect(deriveStage(session("converged_pending_human"))).toBe("leader");
  });

  it("maps converged with a decision package to approval", () => {
    expect(deriveStage(session("converged_pending_human", { decision_package: decisionPackage }))).toBe("approval");
  });

  it("maps approved to approved", () => {
    expect(deriveStage(session("approved", { decision_package: decisionPackage }))).toBe("approved");
  });

  it("sends rejected back to idea so the page can start a new session", () => {
    expect(deriveStage(session("rejected", { resolution_comment: "补充离线能力" }))).toBe("idea");
  });

  it("maps terminated to terminated", () => {
    expect(deriveStage(session("terminated"))).toBe("terminated");
  });

  it("maps budget_exhausted to terminated", () => {
    expect(deriveStage(session("budget_exhausted"))).toBe("terminated");
  });
});