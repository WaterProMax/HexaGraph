/**
 * 静态演示项目（课上演示内容的搬家目标）。
 *
 * 「小红书项目搭建（静态）」是一个只读快照项目：原项目页的课上演示网格已下线，
 * 其内容（规格 / 任务 / 派发 / 监控 / 时间线）以冻结数据的形式保存在这里，
 * 并按项目工作台的拆分 tabs（详情 / 任务派发 / 执行监控 / Agent 评测 / 活动 / 任务图）展示。
 *
 * 快照由 `Test3/scripts/capture_static_snapshot.py` 生成：所有 UUID 加 `st-`
 * 前缀、任务代码加 `S` 前缀（W1-01 → SW1-01），保证静态实体永远不会与真实
 * 后端实体撞车；所有写请求在 API 层被拒绝（409 static_read_only）。
 */

export const STATIC_PROJECT_ID = "st-1958d688-c67e-4ad1-a667-5e6314ab7efd";
export const STATIC_RUN_ID = "st-09182750-4271-5e8f-8228-7db27ffb26fd";
export const STATIC_PROJECT_NAME = "小红书项目搭建（静态）";

/** Sidebar / project-list entry; kept in sync with the snapshot project. */
export const STATIC_PROJECT_ENTRY = {
  id: STATIC_PROJECT_ID,
  name: STATIC_PROJECT_NAME,
  profile: "python-pytest",
};

/** Slim run-list entry so the static project resolves a run without loading the big snapshot. */
export const STATIC_RUN_SUMMARY = {
  id: STATIC_RUN_ID,
  project_id: STATIC_PROJECT_ID,
  status: "waiting",
  stage: "7",
  revision: 2,
  paused: false,
  idea: "我想做一个类似小红书的平台",
};

export type StaticSnapshot = {
  project: { id: string; name: string; profile: string };
  runSummary: Record<string, unknown>;
  responses: Record<string, any>;
  events: any[];
  sessionMessages: Record<string, any[]>;
  roleMemory: Record<string, any>;
  bots: { items: any[] };
};

let snapshotPromise: Promise<StaticSnapshot> | null = null;

/** Lazy-loaded so the ~3MB snapshot stays out of the main bundle. */
export function loadStaticSnapshot(): Promise<StaticSnapshot> {
  snapshotPromise ??= import("./staticSnapshot.json").then((mod) => mod.default as StaticSnapshot);
  return snapshotPromise;
}

export function isStaticProjectId(id: string): boolean {
  return id === STATIC_PROJECT_ID;
}

export function isStaticRunId(id: string | undefined): boolean {
  return id === STATIC_RUN_ID;
}

const STATIC_UUID_RE = /\bst-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/;
const STATIC_TASK_RE = /\/tasks\/SW\d+-\d+(?=\/|$)/;

/**
 * Classify a request before it reaches fetch. Static reads are served from the
 * snapshot; static writes are rejected by the caller with a read-only error.
 * The body is inspected too so writes that only carry the static id in their
 * payload (e.g. creating a memory record) cannot leak into the live backend.
 */
export function staticRequestKind(path: string, init?: RequestInit): "none" | "read" | "write" {
  const method = (init?.method || "GET").toUpperCase();
  const body = typeof init?.body === "string" ? init.body : "";
  const hit = STATIC_UUID_RE.test(path) || STATIC_TASK_RE.test(path) || STATIC_UUID_RE.test(body);
  if (!hit) return "none";
  return method === "GET" || method === "HEAD" ? "read" : "write";
}

function snapshotTasks(snap: StaticSnapshot): any[] {
  const tasks = snap.responses[`/runs/${STATIC_RUN_ID}/tasks`];
  return Array.isArray(tasks) ? tasks : [];
}

function findTask(snap: StaticSnapshot, idOrCode: string): any | null {
  return snapshotTasks(snap).find((task) => task?.code === idOrCode || task?.id === idOrCode) || null;
}

function emptyRoleMemory(taskCode: string, role: string) {
  return {
    run_id: STATIC_RUN_ID,
    project_id: STATIC_PROJECT_ID,
    task_code: taskCode,
    role,
    revision: 0,
    manual_text: "",
    manual_updated_by: null,
    manual_updated_at: null,
    role_snapshot: { text: "", sources: [], matcher_version: "" },
    manual_section: null,
    role_section: null,
    context_hash: "",
    frozen: false,
    frozen_context: {},
    effective: "current",
  };
}

/** Serve a static GET from the snapshot; unknown static reads resolve to null. */
export async function resolveStaticRead(path: string): Promise<any> {
  const snap = await loadStaticSnapshot();
  if (Object.prototype.hasOwnProperty.call(snap.responses, path)) return snap.responses[path];

  let match = path.match(/^\/runs\/([^/]+)\/events\/history\?after=(\d+)$/);
  if (match && match[1] === STATIC_RUN_ID) {
    const after = Number(match[2]);
    return snap.events.filter((event) => Number(event?.seq ?? 0) > after);
  }

  match = path.match(/^\/discussion-sessions\/([^/]+)\/messages\?after=(\d+)$/);
  if (match && snap.sessionMessages[match[1]]) {
    const after = Number(match[2]);
    return { items: snap.sessionMessages[match[1]].filter((msg) => Number(msg?.seq ?? 0) > after) };
  }

  match = path.match(/^\/runs\/([^/]+)\/tasks\/([^/]+)\/execution-trace$/);
  if (match && match[1] === STATIC_RUN_ID) {
    const code = decodeURIComponent(match[2]);
    const task = findTask(snap, code);
    // The source run never executed a task (waiting at PLAN gate); every trace is empty.
    return {
      run_id: STATIC_RUN_ID,
      task_code: code,
      role: task?.card?.role || "coder",
      execution_path: "",
      context_injected: false,
      current_attempt_id: "",
      attempts: [],
    };
  }

  match = path.match(/^\/runs\/([^/]+)\/tasks\/([^/]+)\/role-memory\/([^/]+)$/);
  if (match && match[1] === STATIC_RUN_ID) {
    const code = decodeURIComponent(match[2]);
    const role = decodeURIComponent(match[3]);
    return snap.roleMemory[`${code}:${role}`] || emptyRoleMemory(code, role);
  }

  match = path.match(/^\/tasks\/([^/]+)$/);
  if (match) {
    const task = findTask(snap, decodeURIComponent(match[1]));
    if (task) return task;
  }

  if (path.startsWith("/memory/records") && path.includes(STATIC_PROJECT_ID)) {
    return snap.responses[`/memory/records?project_id=${STATIC_PROJECT_ID}&visibility=project`] ?? { items: [] };
  }

  return null;
}

/** Append the static project to a live project list (idempotent). */
export function withStaticProject(list: any): any {
  if (!Array.isArray(list) || list.some((item) => item?.id === STATIC_PROJECT_ID)) return list;
  return [...list, STATIC_PROJECT_ENTRY];
}

/** Append the static run to a live run list (idempotent). */
export function withStaticRun(list: any): any {
  if (!Array.isArray(list) || list.some((item) => item?.id === STATIC_RUN_ID)) return list;
  return [...list, STATIC_RUN_SUMMARY];
}
