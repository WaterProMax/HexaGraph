import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalBanner } from "./ApprovalBanner";

afterEach(cleanup);

describe("ApprovalBanner", () => {
  it("shows the approval copy with the round and opens the dialog", () => {
    const onOpen = vi.fn();
    render(<ApprovalBanner round={2} onOpen={onOpen} />);

    const banner = screen.getByTestId("disc-approval-banner");
    expect(banner.textContent).toContain("需求规格待你审批");
    expect(banner.textContent).toContain("第 2 轮");

    fireEvent.click(screen.getByRole("button", { name: "查看并审批" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("omits the round when it is not provided", () => {
    render(<ApprovalBanner onOpen={vi.fn()} />);
    expect(screen.getByTestId("disc-approval-banner").textContent).not.toContain("第");
  });
});