import { describe, expect, it } from "vitest";
import { UX_TIMEOUT_MS, designComposerForced, importWaitText } from "./designImportWait";

describe("importWaitText from run artifacts", () => {
  it("keeps elapsed and step from started_at so a remount does not reset to 0", () => {
    const startedAt = "2026-11-16T00:00:00.000Z";
    const now = Date.parse(startedAt) + 45_000;
    expect(
      importWaitText({ status: "importing", step: "spec", startedAt, now }),
    ).toBe("正在整理需求规格 45 秒");
    expect(
      importWaitText({ status: "importing", step: "design", startedAt, now: now + 4_000 }),
    ).toBe("正在整理设计规格 49 秒");
  });

  it("shows the 10-minute UX timeout from started_at after remount", () => {
    const startedAt = "2026-11-16T00:00:00.000Z";
    const now = Date.parse(startedAt) + UX_TIMEOUT_MS;
    expect(importWaitText({ status: "importing", step: "spec", startedAt, now })).toMatch(
      /等待已停止（未取消后端整理）/,
    );
  });

  it("hides wait copy once import is no longer running", () => {
    expect(
      importWaitText({
        status: "awaiting_confirmation",
        step: "spec",
        startedAt: "2026-11-16T00:00:00.000Z",
      }),
    ).toBe("");
  });

  it("keeps elapsed from a local fallback start when started_at is not yet known", () => {
    const fallbackStart = Date.parse("2026-11-16T00:00:00.000Z");
    expect(
      importWaitText({
        status: "importing",
        step: "spec",
        now: fallbackStart + 3_000,
        fallbackStart,
      }),
    ).toBe("正在整理需求规格 3 秒");
  });
});

describe("designComposerForced", () => {
  it("keeps the design composer visible while importing even if local flowMode reset", () => {
    expect(designComposerForced({ design_input_status: "importing" }, null)).toBe(true);
    expect(designComposerForced(null, { origin: "design_spec" })).toBe(true);
    expect(designComposerForced({ design_input: { text: "目标：座位" } }, null)).toBe(true);
    expect(designComposerForced(null, { origin: "idea" })).toBe(false);
  });
});
