import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RequirementTracePanel, normalizeTraceLinks } from "./RequirementTracePanel";

const traceMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({
  api: { trace: traceMock },
}));

beforeEach(() => {
  traceMock.mockReset();
});

afterEach(cleanup);

describe("RequirementTracePanel", () => {
  it("renders one row per trace link with from/to/kind/version", async () => {
    traceMock.mockResolvedValue([
      { from: "ISSUE-01", to: "SPEC-01", kind: "issue → spec_item", version: "1.0" },
      { from: "SPEC-01", to: "T-01", kind: "spec_item → task", version: "1.0" },
    ]);

    render(<RequirementTracePanel runId="run-1" />);

    const rows = await screen.findAllByTestId("requirement-trace-link");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("ISSUE-01");
    expect(rows[0].textContent).toContain("SPEC-01");
    expect(rows[0].textContent).toContain("issue → spec_item");
    expect(rows[1].textContent).toContain("SPEC-01");
    expect(rows[1].textContent).toContain("T-01");
    expect(rows[1].textContent).toContain("spec_item → task");
    expect(rows[1].textContent).toContain("1.0");

    const table = screen.getByTestId("requirement-trace-table");
    // Columns are explicitly labelled as the API fields.
    for (const column of ["from", "to", "kind", "version"]) {
      expect(table.textContent).toContain(column);
    }
    // The panel is the orchestration trace, not an execution-step graph.
    const panel = screen.getByTestId("requirement-trace-panel");
    expect(panel.textContent).toContain("编排追溯");
    expect(panel.textContent).toContain("执行步骤见执行监控");
    expect(panel.textContent).not.toContain("工具步骤图");
    expect(traceMock).toHaveBeenCalledWith("run-1");
  });

  it("shows a short Chinese error instead of a blank page when loading fails", async () => {
    traceMock.mockRejectedValue(new Error("network down"));

    render(<RequirementTracePanel runId="run-1" />);

    const error = await screen.findByTestId("requirement-trace-error");
    expect(error.textContent).toContain("暂时无法载入追溯链路");
    expect(screen.queryByTestId("requirement-trace-table")).toBeNull();
    // The panel heading and the layer explanation stay visible on failure.
    expect(screen.getByTestId("requirement-trace-panel").textContent).toContain("需求追溯");
  });

  it("shows the empty-state sentence when the run has no trace links yet", async () => {
    traceMock.mockResolvedValue([]);

    render(<RequirementTracePanel runId="run-1" />);

    const empty = await screen.findByTestId("requirement-trace-empty");
    expect(empty.textContent).toBe("还没有追溯链路。任务由已批准规格物化后会出现规格项 → 任务的连线。");
    expect(screen.queryByTestId("requirement-trace-table")).toBeNull();
  });

  it("ignores malformed links instead of throwing", () => {
    expect(normalizeTraceLinks(null)).toEqual([]);
    expect(normalizeTraceLinks({ links: [{ from: "A", to: "B", kind: "k", version: "1" }] })).toEqual([
      { from: "A", to: "B", kind: "k", version: "1" },
    ]);
    expect(normalizeTraceLinks([{ bogus: true }, { from: "A", to: "B" }])).toEqual([
      { from: "A", to: "B", kind: "", version: "" },
    ]);
  });
});