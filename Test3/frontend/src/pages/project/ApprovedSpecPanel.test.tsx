import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DecisionPackage, DiscussionSession } from "../../api/types";
import { ApprovedSpecPanel } from "./ApprovedSpecPanel";

const apiMock = vi.hoisted(() => ({ artifacts: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { artifacts: apiMock.artifacts },
}));

const basePackage: DecisionPackage = {
  decision_id: "decision-1",
  session_id: "session-1",
  requirement_snapshot_hash: "snap-hash",
  proposal_ids: ["p1"],
  dissent_items: [],
  hard_gate_summary: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: true },
  body_md: "# 规格\n\n正文",
  sha256: "a".repeat(64),
};

function packageFor(sessionId: string, bodyMd: string): DecisionPackage {
  return { ...basePackage, session_id: sessionId, body_md: bodyMd };
}

function makeSession(overrides: Partial<DiscussionSession> = {}): DiscussionSession {
  return {
    session_id: "session-1",
    project_id: "project-1",
    leader_bot_id: "bot-leader",
    participant_bot_ids: ["bot-leader", "bot-a"],
    status: "approved",
    current_round: 1,
    budget: {
      max_rounds: 3,
      max_tokens: null,
      max_wallclock_seconds: null,
      score_gap_threshold: null,
    },
    requirement_snapshot_hash: "snap-hash",
    decision_package: basePackage,
    requirement_text: "做一个自习室空位查询小程序。",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-18T10:00:00Z",
    ...overrides,
  };
}

const first = makeSession({
  session_id: "s1",
  status: "rejected",
  created_at: "2026-11-18T10:00:00Z",
  decision_package: packageFor("s1", "# 第一版\n\n旧规格正文"),
});
const approved = makeSession({
  session_id: "s2",
  status: "approved",
  created_at: "2026-11-19T10:00:00Z",
  decision_package: packageFor("s2", "# 第二版\n\n最新规格正文：学生可按空闲时段筛选座位。"),
});

beforeEach(() => {
  apiMock.artifacts.mockReset().mockResolvedValue({});
});

afterEach(cleanup);

describe("ApprovedSpecPanel", () => {
  it("renders the latest approved discussion markdown inline, with history and the original requirement", async () => {
    const statuses: unknown[] = [];
    render(
      <ApprovedSpecPanel
        runId="run-1"
        sessions={[first, approved]}
        onStatusChange={(status) => statuses.push(status)}
      />,
    );

    expect(screen.getByTestId("approved-spec-panel")).toBeTruthy();
    expect(screen.getByText(/最新规格正文：学生可按空闲时段筛选座位。/)).toBeTruthy();
    // The full requirement text is a read-only summary, never a second editor.
    expect(screen.getByTestId("approved-spec-requirement").textContent).toContain(
      "做一个自习室空位查询小程序。",
    );
    // History stays available inline; no dialog mask is required to read the body.
    expect(screen.getByTestId("disc-spec-history")).toBeTruthy();
    expect(screen.queryByTestId("disc-spec-dialog")).toBeNull();
    expect(statuses).toContainEqual({ kind: "discussion", version: 2 });
    // Discussion markdown exists: the artifact fallback must not be fetched or shown.
    expect(apiMock.artifacts).not.toHaveBeenCalled();
  });

  it("falls back to the complete approved SPEC artifact (all features), labelled honestly", async () => {
    apiMock.artifacts.mockResolvedValue({
      baseline_SPEC: "1.4",
      spec: {
        scenarios: [{ code: "S1", title: "空位查询" }, { code: "S2", title: "上报表单" }],
        features: [
          { code: "F1", title: "座位查询" },
          { code: "F2", title: "上报表单" },
          { code: "F3", title: "限频" },
          { code: "F4", title: "告警" },
        ],
        nonfunc: [{ code: "N1", title: "响应时间" }],
        out_of_scope: ["不做支付"],
        open_questions: ["是否需要地图"],
      },
    });

    render(<ApprovedSpecPanel runId="run-1" sessions={[]} />);

    const artifact = await screen.findByTestId("approved-spec-artifact");
    expect(artifact.textContent).toContain("已批准 SPEC 工件");
    expect(artifact.textContent).toContain("基线 v1.4");
    // All four features, not the "还有 1 项" summary.
    expect(screen.getAllByTestId("approved-spec-feature")).toHaveLength(4);
    expect(artifact.textContent).toContain("座位查询");
    expect(artifact.textContent).toContain("告警");
    expect(artifact.textContent).toContain("不做支付");
    expect(artifact.textContent).toContain("是否需要地图");
    expect(artifact.textContent).not.toContain("还有 1 项功能");
  });

  it("shows an honest empty state when neither discussion markdown nor SPEC artifact exists", async () => {
    render(<ApprovedSpecPanel runId="run-1" sessions={[]} />);

    expect(await screen.findByTestId("approved-spec-empty")).toBeTruthy();
    expect(screen.getByTestId("approved-spec-empty").textContent).toContain("尚未生成已批准规格");
    expect(screen.queryByTestId("approved-spec-feature")).toBeNull();
  });

  it("does not treat a rejected-only discussion as an approved spec", async () => {
    render(<ApprovedSpecPanel runId="run-1" sessions={[first]} />);

    expect(await screen.findByTestId("approved-spec-empty")).toBeTruthy();
    expect(screen.queryByText(/旧规格正文/)).toBeNull();
  });
});