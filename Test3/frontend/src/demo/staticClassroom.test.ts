import { beforeEach, describe, expect, it } from "vitest";
import {
  canAdvanceStaticDemo,
  createStaticDemoState,
  currentStaticGate,
  getStaticTasks,
  loadStaticDemoState,
  saveStaticDemoState,
  staticArtifactVisibility,
  staticDemoReducer,
  STATIC_DEMO_STORAGE_KEY,
  type StaticDemoState,
  type StaticGate,
} from "./staticClassroom";
import { STATIC_PLAN, STATIC_SPEC, STATIC_UTTERANCES } from "./staticClassroomData";

function next(state: StaticDemoState) {
  return staticDemoReducer(state, { type: "NEXT" });
}

function approve(state: StaticDemoState, gate: StaticGate) {
  return staticDemoReducer(state, { type: "APPROVE", gate });
}

function atDiscussionGate() {
  let state = createStaticDemoState();
  for (let index = 0; index < STATIC_UTTERANCES.length; index += 1) state = next(state);
  return state;
}

function atExecution() {
  let state = atDiscussionGate();
  state = approve(state, "DISCUSSION");
  state = approve(state, "SPEC");
  state = approve(state, "DESIGN");
  state = approve(state, "PLAN");
  return state;
}

function statesByCode(state: StaticDemoState) {
  return Object.fromEntries(getStaticTasks(state).map((task) => [task.code, task.state]));
}

beforeEach(() => window.localStorage.clear());

describe("static classroom fixture", () => {
  it("keeps stable role order, two substantive disputes and consistent scope", () => {
    expect(STATIC_UTTERANCES.map((item) => item.seq)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(new Set(STATIC_UTTERANCES.map((item) => item.role))).toEqual(new Set(["产品", "架构", "开发", "测试"]));
    expect(new Set(STATIC_UTTERANCES.filter((item) => item.phase === "讨论分歧").map((item) => item.issue))).toEqual(new Set(["D-01", "D-02"]));
    expect(STATIC_SPEC.exclusions).toEqual(["座位预约与取消", "支付", "真实硬件接入"]);
    expect(STATIC_SPEC.features.map((feature) => feature.code)).toEqual(["F1", "F2", "F3"]);
    expect(STATIC_PLAN.tasks.map((task) => task.code)).toEqual(["T-01", "T-02", "T-03", "T-04", "T-05"]);
    expect(STATIC_PLAN.tasks.find((task) => task.code === "T-04")?.depends_on).toEqual(["T-02", "T-03"]);
  });
});

describe("static classroom gates", () => {
  it("stops at every gate and never lets NEXT approve it", () => {
    let state = atDiscussionGate();
    const gates: StaticGate[] = ["DISCUSSION", "SPEC", "DESIGN", "PLAN"];
    for (const gate of gates) {
      expect(currentStaticGate(state)).toBe(gate);
      expect(canAdvanceStaticDemo(state)).toBe(false);
      expect(next(state)).toBe(state);
      const beforeActivities = state.activities.length;
      const approved = approve(state, gate);
      expect(approved.approvedGates).toContain(gate);
      expect(approve(approved, gate)).toBe(approved);
      expect(approved.activities.length).toBeGreaterThan(beforeActivities);
      state = approved;
    }
    expect(state.stage).toBe("execution");
    expect(state.approvedGates).toEqual(gates);
  });

  it("reveals artifacts only after the preceding human approval", () => {
    let state = atDiscussionGate();
    expect(staticArtifactVisibility(state)).toEqual({ spec: false, design: false, plan: false });
    state = approve(state, "DISCUSSION");
    expect(staticArtifactVisibility(state)).toEqual({ spec: true, design: false, plan: false });
    state = approve(state, "SPEC");
    expect(staticArtifactVisibility(state)).toEqual({ spec: true, design: true, plan: false });
    state = approve(state, "DESIGN");
    expect(staticArtifactVisibility(state)).toEqual({ spec: true, design: true, plan: true });
  });
});

describe("static classroom dependency execution", () => {
  it("keeps T-02/T-03 simultaneously running and blocks T-04 until both finish", () => {
    let state = atExecution();
    expect(statesByCode(state)).toEqual({ "T-01": "ready", "T-02": "pending", "T-03": "pending", "T-04": "pending", "T-05": "pending" });
    state = next(state);
    expect(statesByCode(state)["T-01"]).toBe("running");
    state = next(state);
    expect(statesByCode(state)).toMatchObject({ "T-01": "done", "T-02": "ready", "T-03": "ready", "T-04": "pending" });
    state = next(state);
    expect(statesByCode(state)).toMatchObject({ "T-02": "running", "T-03": "running", "T-04": "pending" });
    state = next(state);
    expect(statesByCode(state)).toMatchObject({ "T-02": "done", "T-03": "running", "T-04": "pending" });
    state = next(state);
    expect(statesByCode(state)).toMatchObject({ "T-02": "done", "T-03": "done", "T-04": "ready" });
    state = next(state);
    expect(statesByCode(state)["T-04"]).toBe("running");
  });

  it("finishes with one stable acceptance event and no post-completion advance", () => {
    let state = atExecution();
    for (let index = 0; index < 9; index += 1) state = next(state);
    expect(state.stage).toBe("acceptance");
    expect(Object.values(statesByCode(state)).every((taskState) => taskState === "done")).toBe(true);
    expect(canAdvanceStaticDemo(state)).toBe(false);
    const activityCount = state.activities.length;
    expect(next(state)).toBe(state);
    expect(state.activities).toHaveLength(activityCount);
    expect(state.activities.filter((event) => event.kind === "静态验收就绪")).toHaveLength(1);
  });
});

describe("static classroom replay and persistence", () => {
  it("resets three times without exhausting data or mixing old activities", () => {
    let state = createStaticDemoState();
    const runIds = [state.runId];
    for (let replay = 0; replay < 3; replay += 1) {
      state = next(state);
      expect(state.discussionCount).toBe(1);
      state = staticDemoReducer(state, { type: "RESET" });
      runIds.push(state.runId);
      expect(state.discussionCount).toBe(0);
      expect(state.approvedGates).toEqual([]);
      expect(state.activities).toHaveLength(1);
      expect(state.activities[0].subject).toBe(state.runId);
      expect(state.stage).toBe("discussion");
    }
    expect(new Set(runIds).size).toBe(4);
  });

  it("restores the same progress after a refresh round trip", () => {
    let state = atExecution();
    state = next(next(next(state)));
    saveStaticDemoState(window.localStorage, state);
    expect(loadStaticDemoState(window.localStorage)).toEqual(state);
    expect(statesByCode(loadStaticDemoState(window.localStorage))).toMatchObject({ "T-02": "running", "T-03": "running" });
  });

  it("falls back to a clean entry when only the demo storage is corrupt", () => {
    window.localStorage.setItem(STATIC_DEMO_STORAGE_KEY, "not-json");
    window.localStorage.setItem("unrelated-real-run", "keep-me");
    const state = loadStaticDemoState(window.localStorage);
    expect(state.started).toBe(false);
    expect(state.replay).toBe(0);
    expect(window.localStorage.getItem("unrelated-real-run")).toBe("keep-me");
  });
});
