import { ApiError, api } from "../../api/client";
import type { ExecutionAttempt, ExecutionTrace } from "../../api/types";

/**
 * Shared read-side helpers for the execution-trace panels.
 *
 * The trace endpoint is read-only observation data; nothing here mutates a
 * task, a permission or a model pin. Labels stay Chinese so the monitor page
 * never shows raw English status values such as `finished_ok`.
 */

/** Run event kinds pushed while a scripted/legacy task records a step. */
export const STEP_EVENT_KINDS: ReadonlySet<string> = new Set([
  "task.llm_step",
  "task.tool_step",
  "task.granted_command",
]);

/** Highest step-event sequence seen so far; `0` when no step event arrived. */
export function stepEventRefreshToken(
  events: Array<{ kind?: unknown; seq?: unknown }> | null | undefined,
): number {
  let latest = 0;
  for (const event of events || []) {
    if (!event || !STEP_EVENT_KINDS.has(String(event.kind ?? ""))) continue;
    const seq = Number(event.seq);
    if (Number.isFinite(seq) && seq > latest) latest = seq;
  }
  return latest;
}

/**
 * One in-flight GET per run/task, shared by the step timeline and the attempt
 * history so selecting a task does not download the same trace twice. This is
 * a de-duplication window only (no cached result), so a later refresh still
 * hits the API.
 */
const inFlightTraces = new Map<string, Promise<ExecutionTrace>>();

export function fetchExecutionTrace(runId: string, taskCode: string): Promise<ExecutionTrace> {
  const key = `${runId}\u0000${taskCode}`;
  const existing = inFlightTraces.get(key);
  if (existing) return existing;
  let pending: Promise<ExecutionTrace>;
  pending = api.executionTrace(runId, taskCode).finally(() => {
    if (inFlightTraces.get(key) === pending) inFlightTraces.delete(key);
  });
  inFlightTraces.set(key, pending);
  return pending;
}

/**
 * Chinese, short load-error messages.
 *
 * The raw response body is deliberately not echoed: FastAPI validation bodies
 * can quote request payloads, and the trace response is already the only
 * surface allowed to show step summaries.
 */
export function executionTraceErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "任务或运行不存在，请刷新任务列表后重试。";
    if (err.status === 403) return "没有权限读取该任务的执行轨迹。";
    if (err.status >= 500) return `执行轨迹暂时不可用（HTTP ${err.status}），请稍后重试。`;
    if (err.status > 0) return `执行轨迹加载失败（HTTP ${err.status}），请稍后重试。`;
  }
  return "执行轨迹加载失败，请检查网络或后端是否可用。";
}

export function shortHash(value: string | null | undefined): string {
  return value ? String(value).slice(0, 12) : "—";
}

/** Step durations are milliseconds; keep them readable without inventing precision. */
export function formatStepDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/**
 * Frozen timestamps arrive as ISO strings. Slice the date/time part instead of
 * re-localising so the value shown is the value that was recorded, regardless
 * of the browser time zone.
 */
export function formatTraceTime(value: string | null | undefined): string {
  if (!value) return "—";
  const text = String(value);
  const match = text.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : text;
}

export function stepKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    llm: "模型调用",
    tool: "工具调用",
    granted_command: "授权命令",
  };
  return labels[kind] || kind || "步骤";
}

export function stepStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ok: "成功",
    done: "成功",
    finished_ok: "成功",
    error: "错误",
    failed: "失败",
    denied: "被拒绝",
    running: "执行中",
    started: "执行中",
    pending: "等待中",
  };
  return labels[status] || status || "—";
}

export function attemptStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    started: "执行中",
    running: "执行中",
    finished_ok: "已完成",
    finished_failed: "失败",
    done: "已完成",
    failed: "失败",
    unknown: "状态未知",
  };
  return labels[status] || status || "状态未知";
}

/** CSS tone used by the existing `.mon-state` classes in runMonitor.css. */
export function attemptStatusTone(status: string): string {
  if (status === "finished_ok" || status === "done" || status === "ok") return "done";
  if (status === "finished_failed" || status === "failed") return "failed";
  if (status === "started" || status === "running") return "running";
  return "";
}

export function isErrorStatus(status: string): boolean {
  return status === "denied" || status === "error" || status === "failed";
}

/** The attempt the trace endpoint points at, falling back to the newest one. */
export function currentAttemptOf(trace: ExecutionTrace | null): ExecutionAttempt | null {
  if (!trace || !Array.isArray(trace.attempts) || trace.attempts.length === 0) return null;
  return (
    trace.attempts.find((attempt) => attempt.attempt_id === trace.current_attempt_id) ||
    trace.attempts[trace.attempts.length - 1] ||
    null
  );
}