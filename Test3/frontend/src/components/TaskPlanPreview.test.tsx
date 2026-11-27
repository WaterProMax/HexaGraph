import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TaskPlanPreview from "./TaskPlanPreview";

afterEach(cleanup);

const plan = { tasks: [
  { code: "T1", title: "查询座位", role: "coder", write_set: ["seats.py"], depends_on: [] },
  { code: "T2", title: "测试座位", role: "tester", depends_on: ["T1"] },
] };

describe("task plan execution feedback", () => {
  it("shows a restored failure output and the task blocking its successor", () => {
    render(<TaskPlanPreview plan={plan} tasks={[
      { code: "T1", state: "failed", prev_output: "模型调用失败" },
      { code: "T2", state: "blocked", blocked_by: ["T1"] },
    ]} />);
    expect(screen.getByText("失败原因 · 模型调用失败")).toBeTruthy();
    expect(screen.getByText("当前状态 · 失败依赖阻塞：T1（failed）")).toBeTruthy();
    expect(screen.getByText(/交付物 seats.py/)).toBeTruthy();
  });

  it("keeps cancelled predecessors in the waiting dependencies", () => {
    render(<TaskPlanPreview plan={plan} tasks={[
      { code: "T1", state: "cancelled" }, { code: "T2", state: "pending" },
    ]} />);
    expect(screen.getByText(/失败依赖阻塞：T1（cancelled）/)).toBeTruthy();
  });

  it("distinguishes a materialized pending task from an unconfirmed plan", () => {
    const selected = vi.fn();
    render(<TaskPlanPreview plan={plan} tasks={[{ code: "T1", state: "pending" }]} onSelect={selected} />);
    expect(screen.getByText("当前状态 · 依赖已满足，等待调度")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /查询座位/ }));
    expect(selected).toHaveBeenCalledWith("T1");
  });
});
