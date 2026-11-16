import { describe, expect, it } from "vitest";
import {
  autoAdvanceAllowed,
  gateActionsLocked,
  isDesignImporting,
  pauseResumeEnabled,
  pauseResumeKind,
  provenanceMarks,
  scheduleEnabled,
  scheduleNoticeText,
} from "./workstationControls";

describe("workstationControls from backend status", () => {
  it.each(["stopped", "terminated", "done"])("disables pause and resume when run is %s", (status) => {
    expect(pauseResumeEnabled({ status, paused: false })).toBe(false);
    expect(pauseResumeEnabled({ status, paused: true })).toBe(false);
    expect(pauseResumeKind({ status, paused: false })).toBeNull();
  });

  it("shows resume when paused and pause when running", () => {
    expect(pauseResumeKind({ status: "waiting", paused: true })).toBe("resume");
    expect(pauseResumeKind({ status: "active", paused: false })).toBe("pause");
    expect(pauseResumeEnabled({ status: "waiting", paused: true })).toBe(true);
    expect(pauseResumeEnabled({ status: "active", paused: false })).toBe(true);
  });

  it("locks approve and reject while a gate request is pending", () => {
    expect(gateActionsLocked({ resolving: true })).toBe(true);
    expect(gateActionsLocked({ resolving: false })).toBe(false);
  });

  it("locks approve and schedule while importing", () => {
    expect(gateActionsLocked({ importing: true })).toBe(true);
    expect(scheduleEnabled({ status: "waiting", paused: false, stage: "7" }, { importing: true })).toBe(false);
  });

  it("treats an in-flight create as importing until artifacts report a status", () => {
    expect(
      isDesignImporting({
        inFlight: { run_id: "run-2", status: "importing" },
        activeRunId: "run-2",
      }),
    ).toBe(true);
    expect(
      isDesignImporting({
        artifactStatus: "importing",
        inFlight: { run_id: "run-2", status: "importing" },
        activeRunId: "run-2",
      }),
    ).toBe(true);
    expect(
      isDesignImporting({
        artifactStatus: "awaiting_confirmation",
        inFlight: { run_id: "run-2", status: "importing" },
        activeRunId: "run-2",
      }),
    ).toBe(false);
    expect(
      isDesignImporting({
        inFlight: { run_id: "run-2", status: "importing" },
        activeRunId: "run-other",
      }),
    ).toBe(false);
  });

  it("allows auto-advance only when a pending gate is unlocked", () => {
    expect(autoAdvanceAllowed({ autoAdvance: true, hasPendingGate: true, gatesLocked: false })).toBe(true);
    expect(autoAdvanceAllowed({ autoAdvance: true, hasPendingGate: true, gatesLocked: true })).toBe(false);
    expect(autoAdvanceAllowed({ autoAdvance: true, hasPendingGate: false, gatesLocked: false })).toBe(false);
    expect(autoAdvanceAllowed({ autoAdvance: false, hasPendingGate: true, gatesLocked: false })).toBe(false);
  });

  it("does not dispatch while paused or terminal", () => {
    expect(scheduleEnabled({ status: "waiting", paused: true, stage: "7" })).toBe(false);
    expect(scheduleEnabled({ status: "stopped", paused: false, stage: "7" })).toBe(false);
    expect(scheduleEnabled({ status: "waiting", paused: false, stage: "7" })).toBe(true);
  });

  it("disables dangerous controls when the status query failed", () => {
    expect(pauseResumeEnabled({ status: "waiting", paused: false }, { statusQueryFailed: true })).toBe(false);
    expect(gateActionsLocked({ statusQueryFailed: true })).toBe(true);
    expect(
      scheduleEnabled({ status: "waiting", paused: false, stage: "7" }, { statusQueryFailed: true }),
    ).toBe(false);
  });
});

describe("schedule notice follows backend schedule_mode", () => {
  it("asks for a click in manual mode and never claims a 5-second loop", () => {
    expect(scheduleNoticeText("manual")).toContain("请点击调度执行");
    expect(scheduleNoticeText("manual")).not.toContain("每 5 秒自动调度");
    expect(scheduleNoticeText(undefined)).toContain("请点击调度执行");
    expect(scheduleNoticeText(undefined)).not.toContain("每 5 秒自动调度");
  });

  it("mentions the 5-second loop only when the backend reports auto mode", () => {
    expect(scheduleNoticeText("auto")).toContain("每 5 秒自动调度");
    expect(scheduleNoticeText("auto")).not.toContain("请点击调度执行");
  });

  it("does not take provenance/preset into account", () => {
    expect(scheduleNoticeText.length).toBe(1);
    expect(scheduleNoticeText("auto")).toContain("每 5 秒自动调度");
  });
});

describe("provenanceMarks stay on run/artifacts", () => {
  it("surfaces generation and execution labels together", () => {
    expect(
      provenanceMarks({
        generation_label: "预置测试输出（scripted）",
        execution_label: "模拟执行（预置工具调用）",
      }),
    ).toEqual(["预置测试输出（scripted）", "模拟执行（预置工具调用）"]);
  });
});
