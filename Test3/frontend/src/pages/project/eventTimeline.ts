/**
 * Shared run-event helpers for the full event timeline (project activity tab and
 * `/runs/:id/timeline` deep link). Pure functions only: no fetching, no DOM, and
 * never raw prompt/tool output — only the payload fields the backend already
 * exposes (`input_summary` / `name` / `duration_ms` / `category` / `detail`).
 */

export type TimelineEvent = {
  seq?: number;
  kind?: string;
  subject?: string;
  ts?: string;
  payload?: Record<string, unknown> | null;
};

const STEP_SUMMARY_LIMIT = 120;
const ACTIVITY_SUMMARY_LIMIT = 200;

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

/**
 * One-line summary for step events only. Non-step events render no step summary
 * here (callers use `eventSummary` for the richer activity fallback).
 */
export function stepSummary(
  kind: string,
  payload: Record<string, unknown> | null | undefined,
): string {
  if (kind !== "task.llm_step" && kind !== "task.tool_step") return "";
  const rawSummary = typeof payload?.input_summary === "string" ? payload.input_summary.trim() : "";
  if (rawSummary) return truncate(rawSummary, STEP_SUMMARY_LIMIT);
  const name = typeof payload?.name === "string" ? payload.name.trim() : "";
  const duration = typeof payload?.duration_ms === "number" ? `${payload.duration_ms}ms` : "";
  return truncate([name, duration].filter(Boolean).join(" · "), STEP_SUMMARY_LIMIT);
}

/** Task code used by the filter: event subject first, then common payload keys. */
export function eventTaskCode(event: TimelineEvent): string {
  if (typeof event.subject === "string" && event.subject.trim()) return event.subject.trim();
  const payload = event.payload || {};
  for (const key of ["task_code", "code", "task"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/**
 * Compact, already-redacted payload preview. Step events keep `stepSummary`
 * semantics; everything else prefers the reason (`category` / `detail`) or the
 * destination (`to`) before clipping JSON. This is the richer fallback the
 * activity feed used, merged into the shared timeline so control/rejection
 * events do not lose their reason when the 20-row feed is replaced.
 */
export function eventSummary(
  kind: string,
  payload: Record<string, unknown> | null | undefined,
): string {
  const step = stepSummary(kind, payload);
  if (step) return step;
  if (kind === "task.llm_step" || kind === "task.tool_step") return "";
  const values = payload || {};
  const inputSummary = typeof values.input_summary === "string" ? values.input_summary.trim() : "";
  if (inputSummary) return truncate(inputSummary, ACTIVITY_SUMMARY_LIMIT);
  const name = typeof values.name === "string" ? values.name.trim() : "";
  const duration = typeof values.duration_ms === "number" ? `${values.duration_ms}ms` : "";
  const named = [name, duration].filter(Boolean).join(" · ");
  if (named) return truncate(named, ACTIVITY_SUMMARY_LIMIT);
  const category = typeof values.category === "string" ? values.category.trim() : "";
  const detail = typeof values.detail === "string" ? values.detail.trim() : "";
  const reason = [category, detail].filter(Boolean).join(" · ");
  if (reason) return truncate(reason, ACTIVITY_SUMMARY_LIMIT);
  const to = typeof values.to === "string" ? values.to.trim() : "";
  if (to) return truncate(`→ ${to}`, ACTIVITY_SUMMARY_LIMIT);
  if (!Object.keys(values).length) return "";
  try {
    return truncate(JSON.stringify(values), ACTIVITY_SUMMARY_LIMIT);
  } catch {
    return truncate(String(values), ACTIVITY_SUMMARY_LIMIT);
  }
}