import type { ExecutionAttempt, ExecutionTrace } from "../../api/types";
import {
  currentAttemptOf,
  formatStepDuration,
  stepKindLabel,
  stepStatusLabel,
} from "./executionTrace";

/**
 * A5 · Pure front-end converters for the observation trace.
 *
 * Input is ONLY the already-redacted JSON returned by the existing
 * execution-trace API (`ExecutionTrace` in api/types.ts). Nothing here fetches
 * data, restores ***REDACTED*** values, or invents fields the API does not
 * provide (cost stays 未计价; no skill-count / LangSmith claims).
 */

export type ObservationStyle = "timeline" | "table" | "json" | "markdown";

/** Timeline first: it stays the default view of ExecutionTracePanel. */
export const OBSERVATION_STYLES: readonly ObservationStyle[] = ["timeline", "table", "json", "markdown"];

export const OBSERVATION_STYLE_LABELS: Record<ObservationStyle, string> = {
  timeline: "时间线",
  table: "表格",
  json: "JSON",
  markdown: "Markdown",
};

/** Honest context wording, shared verbatim with the panel's existing banner. */
export const CONTEXT_NOT_INJECTED_TEXT =
  "本尝试仅冻结上下文哈希，未向模型提示词注入任务上下文（路径：simulated / granted_v1）";
export const CONTEXT_INJECTED_NO_SKILL_TEXT =
  "已注入角色/手动段；公共 skill 包未导入或加载失败";
export const CONTEXT_INJECTED_WITH_SKILL_TEXT =
  "上下文已注入（角色/手动段与公共 skill 包哈希均已记录）";

export function contextInjectionNote(contextInjected: boolean, skillBundleHash?: string | null): string {
  if (!contextInjected) return CONTEXT_NOT_INJECTED_TEXT;
  return skillBundleHash ? CONTEXT_INJECTED_WITH_SKILL_TEXT : CONTEXT_INJECTED_NO_SKILL_TEXT;
}

/** True when at least one attempt recorded steps (export must stay disabled otherwise). */
export function hasObservationSteps(trace: ExecutionTrace | null | undefined): boolean {
  return Boolean(trace && trace.attempts.some((attempt) => attempt.steps.length > 0));
}

function sortedSteps(attempt: ExecutionAttempt | null): ExecutionAttempt["steps"] {
  return attempt ? [...attempt.steps].sort((left, right) => left.step - right.step) : [];
}

/* ------------------------------------------------------------------ */
/* timeline                                                            */
/* ------------------------------------------------------------------ */

export type ObservationTimelineStep = {
  step: number;
  kind: string;
  kindLabel: string;
  name: string;
  status: string;
  statusLabel: string;
  durationMs: number;
  durationText: string;
  model: string;
  slot: string;
  inputSummary: string;
  outputSummary: string;
  error: string;
  truncated: boolean;
};

export type ObservationTimeline = {
  runId: string;
  taskCode: string;
  role: string;
  executionPath: string;
  contextInjected: boolean;
  contextNote: string;
  attemptId: string;
  showingOlderAttempt: boolean;
  steps: ObservationTimelineStep[];
};

/**
 * Same data (and same attempt fallback) as the panel's existing timeline:
 * when the current attempt has no steps yet, show the newest attempt that
 * does and flag it honestly instead of claiming "no steps at all".
 */
export function traceToTimeline(trace: ExecutionTrace): ObservationTimeline {
  const currentAttempt = currentAttemptOf(trace);
  const lastAttemptWithSteps =
    [...trace.attempts].reverse().find((attempt) => attempt.steps.length > 0) || null;
  const displayAttempt =
    currentAttempt && currentAttempt.steps.length > 0
      ? currentAttempt
      : lastAttemptWithSteps || currentAttempt;
  const contextInjected = displayAttempt
    ? Boolean(displayAttempt.context_injected)
    : Boolean(trace.context_injected);
  return {
    runId: trace.run_id,
    taskCode: trace.task_code,
    role: trace.role,
    executionPath: displayAttempt?.execution_path || trace.execution_path || "",
    contextInjected,
    contextNote: contextInjectionNote(contextInjected, displayAttempt?.skill_bundle_hash),
    attemptId: displayAttempt?.attempt_id || "",
    showingOlderAttempt: Boolean(displayAttempt && displayAttempt !== currentAttempt),
    steps: sortedSteps(displayAttempt).map((step) => ({
      step: step.step,
      kind: step.kind,
      kindLabel: stepKindLabel(step.kind),
      name: step.name,
      status: step.status,
      statusLabel: stepStatusLabel(step.status),
      durationMs: step.duration_ms,
      durationText: formatStepDuration(step.duration_ms),
      model: step.model,
      slot: step.slot,
      inputSummary: step.input_summary,
      outputSummary: step.output_summary,
      error: step.error || "",
      truncated: step.truncated,
    })),
  };
}

/** Timeline export: a readable markdown rendering of exactly the timeline data. */
export function timelineToMarkdown(view: ObservationTimeline): string {
  const lines: string[] = [
    `# 执行轨迹（时间线） ${view.taskCode || "—"}`,
    "",
    `- 运行：${view.runId || "—"}`,
    `- 角色：${view.role || "—"}`,
    `- execution_path：${view.executionPath || "未记录"}`,
    `- context_injected：${view.contextInjected}`,
    `- 上下文说明：${view.contextNote}`,
    `- 费用：当前未计价`,
  ];
  if (view.attemptId) lines.push(`- 尝试：${view.attemptId}${view.showingOlderAttempt ? "（当前尝试尚无步骤，显示最近一次有步骤的尝试）" : ""}`);
  if (view.steps.length === 0) {
    lines.push("", "该任务还没有执行步骤。");
    return lines.join("\n");
  }
  lines.push("", "## 步骤");
  for (const step of view.steps) {
    lines.push("", `### #${step.step} ${step.kindLabel} · ${step.name || "—"}`);
    lines.push(`- 状态：${step.statusLabel} · 耗时：${step.durationText}${step.truncated ? " · 已截断" : ""}`);
    if (step.kind === "llm") lines.push(`- 模型 ${step.model || "—"} · 槽位 ${step.slot || "—"}`);
    if (step.inputSummary) lines.push(`- 输入摘要：${step.inputSummary}`);
    if (step.outputSummary) lines.push(`- 输出摘要：${step.outputSummary}`);
    if (step.error) lines.push(`- 错误：${step.error}`);
  }
  return lines.join("\n");
}

/* ------------------------------------------------------------------ */
/* table + CSV                                                         */
/* ------------------------------------------------------------------ */

export type ObservationTable = {
  columns: string[];
  rows: Array<Array<string | number>>;
};

export const OBSERVATION_TABLE_COLUMNS: readonly string[] = [
  "attempt",
  "step",
  "kind",
  "name",
  "status",
  "duration_ms",
  "model",
  "slot",
  "input_summary",
  "output_summary",
  "error",
];

/** One row per recorded step across all attempts, steps ascending per attempt. */
export function traceToTable(trace: ExecutionTrace): ObservationTable {
  const rows: Array<Array<string | number>> = [];
  for (const attempt of trace.attempts) {
    for (const step of sortedSteps(attempt)) {
      rows.push([
        attempt.attempt_id,
        step.step,
        step.kind,
        step.name,
        step.status,
        step.duration_ms,
        step.model,
        step.slot,
        step.input_summary,
        step.output_summary,
        step.error || "",
      ]);
    }
  }
  return { columns: [...OBSERVATION_TABLE_COLUMNS], rows };
}

/**
 * Same formula-injection guard as runMonitor.ts `agentsToCsv` (read-only
 * reference; that module is deliberately left untouched): cells starting
 * with = + - @ get a leading apostrophe, then RFC-style quoting.
 */
function csvCell(value: unknown): string {
  let text = String(value ?? "");
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function tableToCsv(table: ObservationTable): string {
  return [table.columns, ...table.rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

/* ------------------------------------------------------------------ */
/* json + markdown                                                     */
/* ------------------------------------------------------------------ */

/** The API object verbatim — it is already redacted server-side. */
export function traceToJson(trace: ExecutionTrace): string {
  return JSON.stringify(trace, null, 2);
}

/** Per-attempt markdown report; wording mirrors the panel's honest banner. */
export function traceToMarkdown(trace: ExecutionTrace): string {
  const lines: string[] = [
    `# 执行轨迹 ${trace.task_code || "—"}`,
    "",
    `- 运行：${trace.run_id || "—"}`,
    `- 任务代码：${trace.task_code || "—"}`,
    `- 角色：${trace.role || "—"}`,
    `- execution_path：${trace.execution_path || "未记录"}`,
    `- context_injected：${trace.context_injected}`,
    `- 费用：当前未计价`,
  ];
  if (trace.attempts.length === 0) {
    lines.push("", "该任务还没有执行步骤。");
    return lines.join("\n");
  }
  for (const attempt of trace.attempts) {
    lines.push("", `## 尝试 ${attempt.attempt_id}`);
    lines.push(`- 状态：${attempt.status} · 角色：${attempt.role || "—"}`);
    lines.push(`- execution_path：${attempt.execution_path || "未记录"} · context_injected：${attempt.context_injected}`);
    lines.push(`- 上下文说明：${contextInjectionNote(attempt.context_injected, attempt.skill_bundle_hash)}`);
    const steps = sortedSteps(attempt);
    if (steps.length === 0) {
      lines.push("- 该尝试还没有执行步骤。");
      continue;
    }
    for (const step of steps) {
      lines.push("", `### #${step.step} ${stepKindLabel(step.kind)} · ${step.name || "—"}`);
      lines.push(`- 状态：${stepStatusLabel(step.status)} · 耗时：${formatStepDuration(step.duration_ms)}${step.truncated ? " · 已截断" : ""}`);
      if (step.kind === "llm") {
        lines.push(`- 模型 ${step.model || "—"} · 槽位 ${step.slot || "—"} · Token ${step.tokens_in}/${step.tokens_out}`);
      }
      if (step.input_summary) lines.push(`- 输入摘要：${step.input_summary}`);
      if (step.output_summary) lines.push(`- 输出摘要：${step.output_summary}`);
      if (step.error) lines.push(`- 错误：${step.error}`);
    }
  }
  return lines.join("\n");
}

/* ------------------------------------------------------------------ */
/* export helpers                                                      */
/* ------------------------------------------------------------------ */

export type ObservationExport = {
  filename: string;
  content: string;
  mime: string;
};

const STYLE_FORMAT: Record<ObservationStyle, { extension: string; mime: string }> = {
  timeline: { extension: "md", mime: "text/markdown;charset=utf-8" },
  table: { extension: "csv", mime: "text/csv;charset=utf-8" },
  json: { extension: "json", mime: "application/json;charset=utf-8" },
  markdown: { extension: "md", mime: "text/markdown;charset=utf-8" },
};

function filenamePart(value: string): string {
  return (value || "unknown").replace(/[^\w.-]+/g, "-");
}

/** trace-{runId}-{taskCode}-{style}.{ext} with filesystem-safe identifiers. */
export function observationExport(trace: ExecutionTrace, style: ObservationStyle): ObservationExport {
  const format = STYLE_FORMAT[style];
  const filename = `trace-${filenamePart(trace.run_id)}-${filenamePart(trace.task_code)}-${style}.${format.extension}`;
  let content: string;
  switch (style) {
    case "table":
      content = tableToCsv(traceToTable(trace));
      break;
    case "json":
      content = traceToJson(trace);
      break;
    case "markdown":
      content = traceToMarkdown(trace);
      break;
    default:
      content = timelineToMarkdown(traceToTimeline(trace));
  }
  return { filename, content, mime: format.mime };
}

/**
 * Generic text download. runMonitor.ts `downloadCsv` hard-codes the CSV MIME
 * type, so json/markdown exports need this sibling (runMonitor stays untouched).
 */
export function downloadTextFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadObservation(trace: ExecutionTrace, style: ObservationStyle): void {
  const { filename, content, mime } = observationExport(trace, style);
  downloadTextFile(filename, content, mime);
}
