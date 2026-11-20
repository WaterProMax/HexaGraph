import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StageBar, type DiscussionStage } from "./StageBar";

const STEPS = ["想法", "独立方案", "互评", "Leader 审核", "你的审批", "任务拆解"];

function setup(stage: DiscussionStage): HTMLElement {
  render(<StageBar stage={stage} />);
  return screen.getByTestId("disc-stage-bar");
}

function steps(bar: HTMLElement): HTMLElement[] {
  return within(bar).getAllByRole("listitem");
}

afterEach(cleanup);

describe("StageBar", () => {
  const cases: Array<[DiscussionStage, number]> = [
    ["idea", 0],
    ["independent", 1],
    ["review", 2],
    ["leader", 3],
    ["approval", 4],
  ];

  it.each(cases)("highlights the current step and checks earlier steps for %s", (stage, index) => {
    const bar = setup(stage);
    expect(bar.getAttribute("data-stage")).toBe(stage);

    const items = steps(bar);
    expect(items.map((item) => item.textContent)).toHaveLength(STEPS.length);

    const current = items.filter((item) => item.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0]).toBe(items[index]);
    expect(current[0].textContent).toContain(STEPS[index]);

    items.forEach((item, itemIndex) => {
      expect(item.textContent?.includes("✓")).toBe(itemIndex < index);
    });
  });

  it("shows every step done and waits for task split when approved", () => {
    const bar = setup("approved");
    const items = steps(bar);

    expect(items.filter((item) => item.textContent?.includes("✓"))).toHaveLength(5);
    expect(items[5].getAttribute("aria-current")).toBe("step");
    expect(items[5].textContent).toContain("任务拆解");
    expect(within(items[5]).getByText("等待任务拆解")).toBeTruthy();
  });

  it("keeps the steps and marks the discussion terminated", () => {
    const bar = setup("terminated");
    const items = steps(bar);

    expect(bar.getAttribute("data-stage")).toBe("terminated");
    expect(items).toHaveLength(STEPS.length);
    expect(items.some((item) => item.getAttribute("aria-current") === "step")).toBe(false);
    expect(items.some((item) => item.textContent?.includes("✓"))).toBe(false);
    expect(within(bar).getByRole("status").textContent).toBe("讨论已终止");
  });
});