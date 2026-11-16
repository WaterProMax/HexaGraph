import { describe, expect, it } from "vitest";
import {
  autoAdvanceAllowed,
  gateActionsLocked,
  isDesignImporting,
  pauseResumeEnabled,
  pauseResumeKind,
  scheduleEnabled,
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
