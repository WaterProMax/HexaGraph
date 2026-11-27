import { useEffect, useRef, useState } from "react";
import type { ExecutionAttempt, ExecutionTrace } from "../../api/types";
import {
  currentAttemptOf,
  executionTraceErrorMessage,
  fetchExecutionTrace,
  formatStepDuration,
  formatTraceTime,
  isErrorStatus,
  shortHash,
  stepKindLabel,
  stepStatusLabel,
} from "./executionTrace";
import {
  CONTEXT_INJECTED_NO_SKILL_TEXT,
  CONTEXT_INJECTED_WITH_SKILL_TEXT,
  CONTEXT_NOT_INJECTED_TEXT,
  OBSERVATION_STYLES,
  OBSERVATION_STYLE_LABELS,
  downloadObservation,
  hasObservationSteps,
  traceToJson,
  traceToMarkdown,
  traceToTable,
  type ObservationStyle,
} from "./observationStyles";

/**
 * Step-level view for one task, rendered next to the existing run/task controls.
 *
 * All data comes from the dedicated execution-trace endpoint (not the 24-event
 * stream): the event bus is only a refresh trigger. Nothing here edits memory,
 * permissions or task state.
 */

// Honest context wording now lives in observationStyles.ts so every export
// style repeats exactly the same sentences as this banner.
const EMPTY_TEXT = "该任务还没有执行步骤。scripted/开发任务开始执行后会显示模型与工具调用。";
const COST_TEXT = "费用：当前未计价";

export type ExecutionTracePanelProps = {
  runId?: string;
  taskCode?: string;
  role?: string;
  /** Bumped when a task.*_step event arrives so the timeline refreshes from the API. */
  refreshToken?: number;
  className?: string;
};

type RequestIdentity = { runId: string; taskCode: string };

const panelStyle = {
  marginTop: 16,
  padding: 12,
  border: "1px solid rgba(82,115,140,.18)",
  borderRadius: 14,
  background: "rgba(255,255,255,.55)",
} as const;

const labelStyle = {
  display: "block",
  fontSize: 10.5,
  fontWeight: 600,
  color: "var(--glass-muted, #405c71)",
} as const;

const summaryStyle = {
  margin: "3px 0 0",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  fontFamily: "inherit",
  fontSize: 11.5,
  lineHeight: 1.55,
  color: "var(--glass-secondary, #304b60)",
  maxHeight: 160,
  overflow: "auto",
} as const;

export function ExecutionTracePanel({
  runId,
  taskCode,
  role,
  refreshToken = 0,
  className,
}: ExecutionTracePanelProps) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [trace, setTrace] = useState<ExecutionTrace | null>(null);
  const [error, setError] = useState("");
  // Pure view state: switching styles never re-fetches (effect deps unchanged).
  const [style, setStyle] = useState<ObservationStyle>("timeline");

  const requestSeq = useRef(0);
  const traceRef = useRef<ExecutionTrace | null>(null);
  // Latest props, compared after every await so a response for a previous
  // run/task can never overwrite the current selection (same guard pattern as
  // TaskRoleMemoryPanel). Assigning during render keeps the comparison current
  // even if the old promise resolves between the prop change render and the
  // effect cleanup.
  const latestProps = useRef<RequestIdentity>({ runId: runId || "", taskCode: taskCode || "" });
  latestProps.current = { runId: runId || "", taskCode: taskCode || "" };
  const lastScopeKey = useRef<string | null>(null);

  useEffect(() => {
    const request: RequestIdentity = {
      runId: latestProps.current.runId,
      taskCode: latestProps.current.taskCode,
    };
    const scopeKey = `${request.runId}\u0000${request.taskCode}`;
    const scopeChanged = lastScopeKey.current !== scopeKey;
    lastScopeKey.current = scopeKey;
    const seq = ++requestSeq.current;
    const stillCurrent = () =>
      seq === requestSeq.current &&
      latestProps.current.runId === request.runId &&
      latestProps.current.taskCode === request.taskCode;

    if (!request.runId || !request.taskCode) {
      traceRef.current = null;
      setTrace(null);
      setError("");
      setState("idle");
      return;
    }

    if (scopeChanged) {
      // A new selection must never show the previous task's steps while loading.
      traceRef.current = null;
      setTrace(null);
      setError("");
      setState("loading");
    }

    void (async () => {
      try {
        const data = await fetchExecutionTrace(request.runId, request.taskCode);
        if (!stillCurrent()) return;
        traceRef.current = data;
        setTrace(data);
        setError("");
        setState("ready");
      } catch (err) {
        if (!stillCurrent()) return;
        setError(executionTraceErrorMessage(err));
        // Keep the last successful trace for this same scope visible; only an
        // initial failure leaves the panel in the error-only state.
        setState(traceRef.current ? "ready" : "error");
      }
    })();

    return () => {
      // Invalidate in-flight requests when props change or the panel unmounts.
      requestSeq.current += 1;
    };
  }, [runId, taskCode, refreshToken]);

  const currentAttempt: ExecutionAttempt | null = currentAttemptOf(trace);
  // A retry may already have started a new attempt with no steps yet. Rather
  // than claiming "no steps at all", fall back to the newest attempt that does
  // have recorded steps and label it honestly in the header.
  const lastAttemptWithSteps = trace
    ? [...trace.attempts].reverse().find((attempt) => attempt.steps.length > 0) || null
    : null;
  const displayAttempt =
    currentAttempt && currentAttempt.steps.length > 0
      ? currentAttempt
      : lastAttemptWithSteps || currentAttempt;
  const steps = displayAttempt
    ? [...displayAttempt.steps].sort((left, right) => left.step - right.step)
    : [];
  const contextInjected = displayAttempt
    ? Boolean(displayAttempt.context_injected)
    : Boolean(trace?.context_injected);
  const skillBundleHash = displayAttempt?.skill_bundle_hash || "";
  const executionPath = displayAttempt?.execution_path || trace?.execution_path || "";
  const stepCount = steps.length;
  const showingOlderAttempt = Boolean(displayAttempt && displayAttempt !== currentAttempt);
  // Alternative styles are pure conversions of the already-loaded trace; they
  // never request more data than the timeline shows.
  const tableData = style === "table" && trace && stepCount > 0 ? traceToTable(trace) : null;
  const jsonText = style === "json" && trace && stepCount > 0 ? traceToJson(trace) : null;
  const markdownText = style === "markdown" && trace && stepCount > 0 ? traceToMarkdown(trace) : null;

  return (
    <section
      className={className ? `exec-trace ${className}` : "exec-trace"}
      data-testid="execution-trace"
      aria-label={`任务 ${taskCode || "—"}${role ? `（${role}）` : ""} 的执行步骤`}
      style={panelStyle}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong style={{ color: "var(--glass-ink, #122d42)" }}>执行步骤</strong>
        <span style={{ fontSize: 11, color: "var(--glass-muted, #405c71)" }}>
          任务 {taskCode || "—"}
          {displayAttempt ? ` · 尝试 ${shortHash(displayAttempt.attempt_id)}` : ""}
          {showingOlderAttempt ? " · 当前尝试尚无步骤，显示最近一次有步骤的尝试" : ""}
          {executionPath ? ` · 路径 ${executionPath}` : ""}
          {stepCount > 0 ? ` · ${stepCount} 步` : ""}
        </span>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
        <div
          className="obs-style-switch"
          data-testid="observation-style-switch"
          role="group"
          aria-label="观测数据样式"
        >
          {OBSERVATION_STYLES.map((option) => (
            <button
              key={option}
              type="button"
              className="obs-style-option"
              data-testid={`observation-style-option-${option}`}
              aria-pressed={style === option}
              onClick={() => setStyle(option)}
            >
              {OBSERVATION_STYLE_LABELS[option]}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="obs-export"
          data-testid="observation-export"
          disabled={!hasObservationSteps(trace)}
          onClick={() => {
            if (trace && hasObservationSteps(trace)) downloadObservation(trace, style);
          }}
        >
          按当前样式导出
        </button>
      </div>

      {state === "loading" && (
        <p role="status" data-testid="execution-trace-loading" style={{ margin: "8px 0 0", fontSize: 12 }}>
          正在加载执行步骤…
        </p>
      )}

      {error && (
        <p
          role="alert"
          data-testid="execution-trace-error"
          style={{ margin: "8px 0 0", fontSize: 12, lineHeight: 1.55, color: "#9b2c2c" }}
        >
          {error}
          {trace ? " 已保留上一次成功加载的步骤。" : ""}
        </p>
      )}

      {trace && displayAttempt && (
        <div
          data-testid="execution-context-state"
          style={{
            marginTop: 8,
            padding: "7px 9px",
            borderRadius: 10,
            fontSize: 11.5,
            lineHeight: 1.55,
            background: contextInjected ? "#eef7f1" : "#fff8e8",
            color: contextInjected ? "#0f5f35" : "#805400",
          }}
        >
          {contextInjected ? (
            skillBundleHash ? (
              <span data-testid="execution-context-injected">{CONTEXT_INJECTED_WITH_SKILL_TEXT}</span>
            ) : (
              <span data-testid="execution-context-injected">{CONTEXT_INJECTED_NO_SKILL_TEXT}</span>
            )
          ) : (
            <span data-testid="execution-context-not-injected">{CONTEXT_NOT_INJECTED_TEXT}</span>
          )}
        </div>
      )}

      {state === "ready" && stepCount === 0 && (
        <div className="mon-note" data-testid="execution-trace-empty">
          {EMPTY_TEXT}
        </div>
      )}

      {style === "timeline" && stepCount > 0 && (
        <ol style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}>
          {steps.map((step) => {
            const errored = isErrorStatus(step.status);
            return (
              <li
                key={`${step.step}-${step.kind}`}
                data-testid={`execution-step-${step.step}`}
                data-kind={step.kind}
                data-status={step.status}
                style={{
                  marginTop: 8,
                  padding: "8px 10px",
                  border: errored ? "1px solid #eec2bb" : "1px solid #e3edf5",
                  borderRadius: 10,
                  background: errored ? "#fff4f2" : "rgba(255,255,255,.6)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 650,
                      color: errored ? "#9f2f1b" : "var(--glass-secondary, #304b60)",
                      overflowWrap: "anywhere",
                    }}
                  >
                    #{step.step} {stepKindLabel(step.kind)} · {step.name || "—"}
                  </span>
                  <span style={{ fontSize: 11, color: "#6a8296", whiteSpace: "nowrap" }}>
                    <span
                      className={`mon-state ${errored ? "failed" : ""}`}
                      data-testid={`execution-step-status-${step.step}`}
                    >
                      {stepStatusLabel(step.status)}
                    </span>
                    {" · "}
                    {formatStepDuration(step.duration_ms)}
                    {step.truncated && (
                      <span data-testid={`execution-step-truncated-${step.step}`} style={{ color: "#8b5b00" }}>
                        {" · "}已截断
                      </span>
                    )}
                  </span>
                </div>

                <div style={{ marginTop: 4, fontSize: 11.5, color: "#405c71" }}>
                  {step.kind === "llm" && (
                    <>
                      模型 {step.model || "—"} · 槽位 {step.slot || "—"} · Token {step.tokens_in}/{step.tokens_out}
                      {step.finish_reason ? ` · finish_reason ${step.finish_reason}` : ""}
                      {step.started_at ? ` · ${formatTraceTime(step.started_at)}` : ""}
                    </>
                  )}
                  {step.kind === "tool" && (
                    <>工具 {step.name || "—"} · 耗时 {formatStepDuration(step.duration_ms)}</>
                  )}
                  {step.kind === "granted_command" && (
                    <>授权命令 {step.name || "—"} · 耗时 {formatStepDuration(step.duration_ms)}</>
                  )}
                </div>

                {step.input_summary && (
                  <div style={{ marginTop: 5 }}>
                    <span style={labelStyle}>
                      {step.kind === "llm" ? "输入摘要" : step.kind === "tool" ? "参数摘要" : "命令 / argv"}
                    </span>
                    <pre data-testid={`execution-step-input-${step.step}`} style={summaryStyle}>
                      {step.input_summary}
                    </pre>
                  </div>
                )}
                {step.output_summary && (
                  <div style={{ marginTop: 5 }}>
                    <span style={labelStyle}>
                      {step.kind === "llm" ? "输出摘要" : step.kind === "tool" ? "输出摘要" : "退出码 / 输出"}
                    </span>
                    <pre data-testid={`execution-step-output-${step.step}`} style={summaryStyle}>
                      {step.output_summary}
                    </pre>
                  </div>
                )}

                {errored && (
                  <p
                    role="alert"
                    data-testid={`execution-step-error-${step.step}`}
                    style={{ margin: "5px 0 0", fontSize: 12, lineHeight: 1.55, color: "#9f2f1b", whiteSpace: "pre-wrap" }}
                  >
                    错误：{step.error && step.error.trim() ? step.error : "未提供错误详情"}
                  </p>
                )}
                {!errored && step.error && (
                  <p
                    data-testid={`execution-step-error-${step.step}`}
                    style={{ margin: "5px 0 0", fontSize: 12, lineHeight: 1.55, color: "#9f2f1b", whiteSpace: "pre-wrap" }}
                  >
                    错误：{step.error}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {tableData && (
        <div style={{ marginTop: 8, overflow: "auto", maxHeight: 320 }}>
          <table className="obs-table" data-testid="observation-table">
            <thead>
              <tr>
                {tableData.columns.map((column) => (
                  <th key={column} scope="col">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableData.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {jsonText !== null && (
        <pre className="obs-pre" data-testid="observation-json">{jsonText}</pre>
      )}

      {markdownText !== null && (
        <pre className="obs-pre" data-testid="observation-markdown">{markdownText}</pre>
      )}

      <div className="mon-note" data-testid="execution-trace-cost" style={{ marginTop: 8 }}>
        {COST_TEXT}
      </div>
    </section>
  );
}

export default ExecutionTracePanel;