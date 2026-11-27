import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { GrantStatusBanner } from "./GrantStatusBanner";

afterEach(cleanup);

describe("GrantStatusBanner", () => {
  it("explains baseline_stale and asks for re-approval", () => {
    render(<GrantStatusBanner errorCategory="baseline_stale" />);
    const text = screen.getByTestId("grant-banner").textContent || "";
    expect(text).toMatch(/基线/);
    expect(text).toMatch(/重新审批/);
    expect(text).not.toMatch(/请逐行确认/);
  });

  it("explains grant_required", () => {
    render(<GrantStatusBanner errorCategory="grant_required" />);
    const text = screen.getByTestId("grant-banner").textContent || "";
    expect(text).toMatch(/执行授权|grant/);
  });

  it("maps a stale grant status when no error category is present", () => {
    render(<GrantStatusBanner status="stale" />);
    expect(screen.getByTestId("grant-banner").textContent).toMatch(/重新审批/);
  });

  it("renders nothing without a grant signal", () => {
    const { container } = render(<GrantStatusBanner />);
    expect(container.textContent).toBe("");
  });
});