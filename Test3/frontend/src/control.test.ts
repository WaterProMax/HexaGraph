import { describe, expect, it } from "vitest";
import { controlEnabled } from "./api/client";

describe("control buttons", () => {
  it("matches Design 16.3", () => {
    expect(controlEnabled("retry", "needs_human")).toBe(true);
    expect(controlEnabled("retry", "running")).toBe(false);
    expect(controlEnabled("force-pass", "failed")).toBe(true);
    expect(controlEnabled("force-pass", "done")).toBe(false);
    expect(controlEnabled("resume", "running")).toBe(true);
    expect(controlEnabled("resume", "verifying")).toBe(true);
    expect(controlEnabled("pause", "running")).toBe(true);
  });
});
