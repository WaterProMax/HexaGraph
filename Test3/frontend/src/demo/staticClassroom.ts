import { STATIC_PLAN, STATIC_UTTERANCES } from "./staticClassroomData";

export const STATIC_DEMO_STORAGE_KEY = "hexagraph.static-classroom-demo.v1";
export const STATIC_DEMO_AUTOPLAY_MS = 1400;

export type StaticDemoStage = "discussion" | "SPEC" | "DESIGN" | "PLAN" | "execution" | "acceptance";
export type StaticGate = "DISCUSSION" | "SPEC" | "DESIGN" | "PLAN";
export type StaticTaskState = "pending" | "ready" | "running" | "done";

export interface StaticActivity {
  seq: number;
  kind: string;
  subject: string;
  detail: string;
  provenance: "静态课堂演示事件";
}

export interface StaticDemoState {
  version: 1;
  replay: number;
  runId: string;
  started: boolean;
  stage: StaticDemoStage;
  discussionCount: number;
  approvedGates: StaticGate[];
  executionStep: number;
  activities: StaticActivity[];
}

export type StaticDemoAction =
  | { type: "START" }
  | { type: "NEXT" }
  | { type: "APPROVE"; gate: StaticGate }
  | { type: "RESET" };

export const STATIC_GATE_TITLE: Record<StaticGate, string> = {
  DISCUSSION: "讨论结论确认",
  SPEC: "SPEC 基线确认",
  DESIGN: "DESIGN 基线确认",
  PLAN: "PLAN 基线确认",
};

function demoRunId(replay: number) {
  return `STATIC-CLASSROOM-${String(replay).padStart(3, "0")}`;
}

export function createStaticDemoState(replay = 1, started = true): StaticDemoState {
  return {
    version: 1,
    replay,
    runId: demoRunId(replay),
    started,
    stage: "discussion",
    discussionCount: 0,
    approvedGates: [],
    executionStep: 0,
    activities: started
      ? [
          {
            seq: 1,
            kind: "演示已创建",
            subject: demoRunId(replay),
            detail: "独立静态运行；未创建后端项目，未调用真实模型。",
            provenance: "静态课堂演示事件",
          },
        ]
      : [],
  };
}

export function currentStaticGate(state: StaticDemoState): StaticGate | null {
  if (!state.started) return null;
  if (state.stage === "discussion" && state.discussionCount === STATIC_UTTERANCES.length) return "DISCUSSION";
  if (state.stage === "SPEC" || state.stage === "DESIGN" || state.stage === "PLAN") return state.stage;
  return null;
}

export function canAdvanceStaticDemo(state: StaticDemoState): boolean {
  if (!state.started || state.stage === "acceptance" || currentStaticGate(state)) return false;
  if (state.stage === "discussion") return state.discussionCount < STATIC_UTTERANCES.length;
  return state.stage === "execution" && state.executionStep < 9;
}

function appendActivity(state: StaticDemoState, activity: Omit<StaticActivity, "seq" | "provenance">): StaticActivity[] {
  const seq = state.activities.reduce((max, item) => Math.max(max, item.seq), 0) + 1;
  return [...state.activities, { ...activity, seq, provenance: "静态课堂演示事件" }];
}

const EXECUTION_EVENTS = [
  { kind: "任务就绪", subject: "T-01", detail: "PLAN 已人工确认；T-01 依赖为空，进入 ready。" },
  { kind: "任务启动（模拟）", subject: "T-01", detail: "T-01 进入 running，读取预置查询契约。" },
  { kind: "任务完成（模拟）", subject: "T-01", detail: "T-01 done；T-02 与 T-03 同时进入 ready。" },
  { kind: "并行启动（模拟）", subject: "T-02 + T-03", detail: "两个任务同时 running，展示依赖分叉后的并行片段。" },
  { kind: "任务完成（模拟）", subject: "T-02", detail: "T-02 done；T-03 仍 running，T-04 继续等待。" },
  { kind: "任务完成（模拟）", subject: "T-03", detail: "T-03 done；两个上游均完成，T-04 进入 ready。" },
  { kind: "任务启动（模拟）", subject: "T-04", detail: "T-04 在依赖汇合后进入 running。" },
  { kind: "任务完成（模拟）", subject: "T-04", detail: "T-04 done；T-05 进入 ready。" },
  { kind: "任务启动（模拟）", subject: "T-05", detail: "T-05 进入 running，整理预置验收场景。" },
  { kind: "静态验收就绪", subject: "T-05", detail: "T-05 done；展示预置验收总结，不代表真实测试通过。" },
] as const;

export function staticDemoReducer(state: StaticDemoState, action: StaticDemoAction): StaticDemoState {
  if (action.type === "START") {
    return state.started ? state : createStaticDemoState(state.replay + 1, true);
  }
  if (action.type === "RESET") return createStaticDemoState(state.replay + 1, true);

  if (action.type === "APPROVE") {
    const gate = currentStaticGate(state);
    if (!gate || gate !== action.gate) return state;
    const approvedGates = [...state.approvedGates, gate];
    const base = {
      ...state,
      approvedGates,
      activities: appendActivity(state, {
        kind: "人工确认",
        subject: STATIC_GATE_TITLE[gate],
        detail: "由用户点击“批准并推进”；自动播放未代替批准。",
      }),
    };
    if (gate === "DISCUSSION") {
      return {
        ...base,
        stage: "SPEC",
        activities: appendActivity(base, {
          kind: "预置产物就绪",
          subject: "SPEC",
          detail: "讨论决策已写入 F1–F3；预约、支付和硬件保持排除。",
        }),
      };
    }
    if (gate === "SPEC") {
      return {
        ...base,
        stage: "DESIGN",
        activities: appendActivity(base, {
          kind: "预置产物就绪",
          subject: "DESIGN",
          detail: "M1–M4 与 C1 已可查看，内容为人工编写。",
        }),
      };
    }
    if (gate === "DESIGN") {
      return {
        ...base,
        stage: "PLAN",
        activities: appendActivity(base, {
          kind: "预置产物就绪",
          subject: "PLAN",
          detail: "T-01–T-05 与依赖图已可查看，尚未模拟执行。",
        }),
      };
    }
    return {
      ...base,
      stage: "execution",
      executionStep: 0,
      activities: appendActivity(base, {
        kind: EXECUTION_EVENTS[0].kind,
        subject: EXECUTION_EVENTS[0].subject,
        detail: EXECUTION_EVENTS[0].detail,
      }),
    };
  }

  if (!canAdvanceStaticDemo(state)) return state;

  if (state.stage === "discussion") {
    const nextCount = state.discussionCount + 1;
    const utterance = STATIC_UTTERANCES[nextCount - 1];
    return {
      ...state,
      discussionCount: nextCount,
      activities: appendActivity(state, {
        kind: nextCount === STATIC_UTTERANCES.length ? "讨论完成（预置）" : "角色讨论（预置）",
        subject: `#${utterance.seq} ${utterance.speaker}`,
        detail:
          nextCount === STATIC_UTTERANCES.length
            ? "10 条人工编写发言已展示；时间线停在讨论结论确认。"
            : `${utterance.phase}${utterance.issue ? ` · ${utterance.issue}` : ""}；未调用真实模型。`,
      }),
    };
  }

  const executionStep = state.executionStep + 1;
  const event = EXECUTION_EVENTS[executionStep];
  return {
    ...state,
    stage: executionStep === 9 ? "acceptance" : "execution",
    executionStep,
    activities: appendActivity(state, { kind: event.kind, subject: event.subject, detail: event.detail }),
  };
}

export function getStaticTasks(state: StaticDemoState) {
  const step = state.stage === "execution" || state.stage === "acceptance" ? state.executionStep : -1;
  return STATIC_PLAN.tasks.map((card) => {
    let taskState: StaticTaskState = "pending";
    if (step >= 0) {
      if (card.code === "T-01") {
        if (step === 0) taskState = "ready";
        else if (step === 1) taskState = "running";
        else if (step >= 2) taskState = "done";
      }
      if (card.code === "T-02" || card.code === "T-03") {
        if (step === 2) taskState = "ready";
        else if (step === 3) taskState = "running";
        else if (step === 4) taskState = card.code === "T-02" ? "done" : "running";
        else if (step >= 5) taskState = "done";
      }
      if (card.code === "T-04") {
        if (step === 5) taskState = "ready";
        else if (step === 6) taskState = "running";
        else if (step >= 7) taskState = "done";
      }
      if (card.code === "T-05") {
        if (step === 7) taskState = "ready";
        else if (step === 8) taskState = "running";
        else if (step >= 9) taskState = "done";
      }
    }
    return {
      code: card.code,
      state: taskState,
      revision: 1,
      card,
      simulated: true,
      execution_label: "预置内容／未真实执行",
    };
  });
}

export function staticArtifactVisibility(state: StaticDemoState) {
  return {
    spec: state.approvedGates.includes("DISCUSSION"),
    design: state.approvedGates.includes("SPEC"),
    plan: state.approvedGates.includes("DESIGN"),
  };
}

function isStaticDemoState(value: unknown): value is StaticDemoState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<StaticDemoState>;
  return (
    state.version === 1 &&
    typeof state.replay === "number" &&
    Number.isInteger(state.replay) &&
    state.replay >= 0 &&
    typeof state.runId === "string" &&
    typeof state.started === "boolean" &&
    ["discussion", "SPEC", "DESIGN", "PLAN", "execution", "acceptance"].includes(state.stage || "") &&
    typeof state.discussionCount === "number" &&
    state.discussionCount >= 0 &&
    state.discussionCount <= STATIC_UTTERANCES.length &&
    Array.isArray(state.approvedGates) &&
    typeof state.executionStep === "number" &&
    state.executionStep >= 0 &&
    state.executionStep <= 9 &&
    Array.isArray(state.activities)
  );
}

export function loadStaticDemoState(storage?: Storage): StaticDemoState {
  if (!storage) return createStaticDemoState(0, false);
  try {
    const raw = storage.getItem(STATIC_DEMO_STORAGE_KEY);
    if (!raw) return createStaticDemoState(0, false);
    const parsed: unknown = JSON.parse(raw);
    return isStaticDemoState(parsed) ? parsed : createStaticDemoState(0, false);
  } catch {
    return createStaticDemoState(0, false);
  }
}

export function saveStaticDemoState(storage: Storage | undefined, state: StaticDemoState) {
  if (!storage) return;
  try {
    storage.setItem(STATIC_DEMO_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage can be unavailable in private contexts; the in-memory demo still works.
  }
}
