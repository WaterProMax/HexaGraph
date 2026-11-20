import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import type { DecisionPackage, DiscussionSession } from "../../../api/types";
import { SpecViewer } from "./SpecViewer";

const basePackage: DecisionPackage = {
  decision_id: "decision-1",
  session_id: "session-1",
  requirement_snapshot_hash: "snap-hash",
  proposal_ids: ["p1"],
  dissent_items: [],
  hard_gate_summary: {
    coverage: true,
    conflicts_closed_or_recorded: true,
    evidence_complete: true,
  },
  body_md: "正文",
  sha256: "aaaaaaaaaaaaaaaa",
};

const baseSession: DiscussionSession = {
  session_id: "session-1",
  project_id: "project-1",
  leader_bot_id: "bot-leader",
  participant_bot_ids: ["bot-leader", "bot-a"],
  status: "draft",
  current_round: 1,
  budget: {
    max_rounds: 3,
    max_tokens: null,
    max_wallclock_seconds: null,
    score_gap_threshold: null,
  },
  requirement_snapshot_hash: "snap-hash",
  decision_package: basePackage,
  requirement_text: "原始需求",
  previous_session_id: null,
  resolution_comment: null,
  paused: false,
  created_at: "2026-11-18T10:00:00Z",
};

function makeSession(overrides: Partial<DiscussionSession> = {}) {
  return { ...baseSession, ...overrides };
}

function packageFor(sessionId: string, bodyMd: string, sha256: string): DecisionPackage {
  return {
    ...basePackage,
    session_id: sessionId,
    body_md: bodyMd,
    sha256,
  };
}

const first = makeSession({
  session_id: "s1",
  status: "rejected",
  created_at: "2026-11-18T10:00:00Z",
  decision_package: packageFor("s1", "# 第一版\n\n旧规格正文", "1111222233334444"),
});
const second = makeSession({
  session_id: "s2",
  status: "approved",
  created_at: "2026-11-19T10:00:00Z",
  decision_package: packageFor("s2", "# 第二版\n\n较早批准正文", "aaaabbbbccccdddd"),
});
const third = makeSession({
  session_id: "s3",
  status: "approved",
  created_at: "2026-11-20T10:00:00Z",
  decision_package: packageFor("s3", "# 第三版\n\n最新规格正文", "abcdef1234567890"),
});

function renderViewer(overrides: Partial<ComponentProps<typeof SpecViewer>> = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    sessions: [first, second, third],
    ...overrides,
  };
  render(<SpecViewer {...props} />);
  return props;
}

afterEach(cleanup);

describe("SpecViewer", () => {
  it("shows the latest approved markdown, its version and the first 8 characters of the sha", () => {
    renderViewer();

    const currentBox = screen.getByTestId("disc-spec-current");
    expect(within(currentBox).getByText("最新规格正文")).toBeTruthy();
    expect(within(currentBox).getByText("版本：第 3 次讨论")).toBeTruthy();
    expect(within(currentBox).getByText("摘要 abcdef12")).toBeTruthy();
    expect(within(currentBox).queryByText("较早批准正文")).toBeNull();
  });

  it("lists history newest first with approved and rejected labels", () => {
    renderViewer();

    const history = screen.getByTestId("disc-spec-history");
    expect(within(history).getByText("第 3 次讨论")).toBeTruthy();
    expect(within(history).getByText("第 2 次讨论")).toBeTruthy();
    expect(within(history).getByText("第 1 次讨论")).toBeTruthy();
    expect(within(history).getAllByText("已批准")).toHaveLength(2);
    expect(within(history).getByText("已打回")).toBeTruthy();

    const labels = within(history)
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    expect(labels[0]).toContain("第 3 次讨论");
    expect(labels[2]).toContain("第 1 次讨论");
  });

  it("switches the viewed markdown when a history version is selected", () => {
    renderViewer();

    fireEvent.click(screen.getByRole("button", { name: /第 1 次讨论/ }));

    const currentBox = screen.getByTestId("disc-spec-current");
    expect(within(currentBox).getByText("旧规格正文")).toBeTruthy();
    expect(within(currentBox).getByText("版本：第 1 次讨论")).toBeTruthy();
    expect(within(currentBox).queryByText("最新规格正文")).toBeNull();
    expect(screen.getByRole("button", { name: /第 1 次讨论/ }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("shows an empty state when no session has been approved", () => {
    renderViewer({ sessions: [first] });

    expect(screen.getByText("还没有已批准的规格")).toBeTruthy();
    expect(screen.queryByText("旧规格正文")).toBeNull();
    expect(screen.getByTestId("disc-spec-history").textContent).toContain("已打回");
  });

  it("closes on Escape", () => {
    const props = renderViewer();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when closed", () => {
    renderViewer({ open: false });
    expect(screen.queryByTestId("disc-spec-dialog")).toBeNull();
    expect(screen.queryByText("还没有已批准的规格")).toBeNull();
  });
});