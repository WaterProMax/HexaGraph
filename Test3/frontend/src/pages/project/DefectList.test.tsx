import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DefectRecord } from "../../api/types";
import { DefectList } from "./DefectList";

const defects: DefectRecord[] = [
  {
    defect_id: "d-1",
    run_id: "run-1",
    task_code: "T-02",
    module_id: "M1",
    related_requirement_id: null,
    evidence_uris: ["file://logs/t02.log"],
    status: "open",
    detail: "缺少边界用例",
  },
];

afterEach(cleanup);

describe("DefectList", () => {
  it("locates the task behind a defect", () => {
    const onLocateTask = vi.fn();
    render(<DefectList defects={defects} onLocateTask={onLocateTask} />);
    fireEvent.click(screen.getByTestId("defect-T-02"));
    expect(onLocateTask).toHaveBeenCalledWith("T-02");
  });

  it("does not auto-resolve defects", () => {
    render(<DefectList defects={defects} onLocateTask={vi.fn()} />);
    expect(screen.getByTestId("defect-list").textContent).toContain("open");
    expect(screen.queryByText("resolved")).toBeNull();
  });

  it("shows an empty state", () => {
    render(<DefectList defects={[]} onLocateTask={vi.fn()} />);
    expect(screen.getByTestId("defect-list").textContent).toContain("没有未关闭的缺陷");
  });
});
describe("defect cards", () => {
  it("renders a status pill and evidence count", () => {
    render(<DefectList defects={defects} onLocateTask={vi.fn()} />);
    const card = screen.getByTestId("defect-T-02");
    expect(card.textContent).toContain("open");
    expect(card.textContent).toContain("证据 1");
  });
});
