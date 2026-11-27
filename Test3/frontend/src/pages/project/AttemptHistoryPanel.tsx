import { useEffect, useRef, useState } from "react";
import type { ExecutionAttempt, ExecutionTrace } from "../../api/types";
import {
  attemptStatusLabel,
  attemptStatusTone,
  executionTraceErrorMessage,
  fetchExecutionTrace,
  formatTraceTime,
  shortHash,
} from "./executionTrace";

/**
 * Collapsible attempt history for one task.
 *
 * Every attempt renders the values frozen when it ended (hashes, commit,
 * manual revision, injection flag, step count). This panel is strictly
 * read-only: editing the task/role memory never rewrites what an old attempt
 * recorded, and the two newest attempts sit side by side so their frozen
 * values can be compared.
 */

export type AttemptHistoryPanelProps = {
  runId?: string;
  taskCode?: string;
  role?: string;
  /** Bumped when a step event arrives so the attempt list refreshes. */
  refreshToken?: number;
  /** Pre-loaded attempts; when provided the panel skips the dedicated fetch. */
  attempts?: ExecutionAttempt[];
  currentAttemptId?: string;
  className?: string;
};

type RequestIdentity = { runId: string; taskCode: string };

const EMPTY_TEXT = "还没有尝试记录。任务开始执行后，每次尝试的状态与冻结上下文会显示在这里。";

const panelStyle = {
  marginTop: 16,
  padding: 12,
  border: "1px solid rgba(82,115,140,.18)",
  borderRadius: 14,
  background: "rgba(255,255,255,.55)",
} as const;

function fieldRow(label: string, value: string, title?: string) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
      <dt style={{ fontSize: 10.5, color: "#7a8fa2" }}>{label}</dt>
      <dd
        className="mono"
        title={title}
        style={{
          margin: 0,
          fontSize: 11.5,
          color: "#24465e",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </dd>
    </div>
  );
}

export function AttemptHistoryPanel({
  runId,
  taskCode,
  role,
  refreshToken = 0,
  attempts,
  currentAttemptId,
  className,
}: AttemptHistoryPanelProps) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [trace, setTrace] = useState<ExecutionTrace | null>(null);
  const [error, setError] = useState("");
  // Per-attempt overrides; when absent the current attempt defaults to open.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const requestSeq = useRef(0);
  const latestProps = useRef<RequestIdentity>({ runId: runId || "", taskCode: taskCode || "" });
  latestProps.current = { runId: runId || "", taskCode: taskCode || "" };
  const lastScopeKey = useRef<string | null>(null);
  const controlled = attempts !== undefined;

  useEffect(() => {
    if (controlled) {
      // Pre-loaded attempts win: no second request for the same trace.
      requestSeq.current += 1;
      return;
    }
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
      setTrace(null);
      setError("");
      setState("idle");
      return;
    }
    if (scopeChanged) {
      setTrace(null);
      setError("");
      setState("loading");
    }
    void (async () => {
      try {
        const data = await fetchExecutionTrace(request.runId, request.taskCode);
        if (!stillCurrent()) return;
        setTrace(data);
        setError("");
        setState("ready");
      } catch (err) {
        if (!stillCurrent()) return;
        setError(executionTraceErrorMessage(err));
        setState((previous) => (previous === "loading" ? "error" : previous));
      }
    })();

    return () => {
      requestSeq.current += 1;
    };
  }, [runId, taskCode, refreshToken, controlled]);

  const rows: ExecutionAttempt[] = controlled ? attempts : trace?.attempts || [];
  const activeId = controlled
    ? currentAttemptId || rows[rows.length - 1]?.attempt_id || ""
    : trace?.current_attempt_id || rows[rows.length - 1]?.attempt_id || "";

  return (
    <section
      className={className ? `attempt-history ${className}` : "attempt-history"}
      data-testid="attempt-history"
      aria-label={`任务 ${taskCode || "—"}${role ? `（${role}）` : ""} 的历次尝试`}
      style={panelStyle}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong style={{ color: "var(--glass-ink, #122d42)" }}>历次尝试</strong>
        <span style={{ fontSize: 11, color: "var(--glass-muted, #405c71)" }}>
          任务 {taskCode || "—"} · {rows.length} 次尝试
          {rows.length > 1 ? " · 并排显示，便于对比冻结值" : ""}
        </span>
      </div>

      {!controlled && state === "loading" && (
        <p role="status" data-testid="attempt-history-loading" style={{ margin: "8px 0 0", fontSize: 12 }}>
          正在加载历次尝试…
        </p>
      )}

      {!controlled && error && (
        <p
          role="alert"
          data-testid="attempt-history-error"
          style={{ margin: "8px 0 0", fontSize: 12, lineHeight: 1.55, color: "#9b2c2c" }}
        >
          {error}
          {trace ? " 已保留上一次成功加载的尝试记录。" : ""}
        </p>
      )}

      {(controlled || state === "ready") && rows.length === 0 && (
        <div className="mon-note" data-testid="attempt-history-empty">
          {EMPTY_TEXT}
        </div>
      )}

      {rows.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 8,
            marginTop: 8,
            alignItems: "start",
          }}
        >
          {rows.map((attempt) => {
            const isCurrent = attempt.attempt_id === activeId;
            const isOpen = expanded[attempt.attempt_id] ?? isCurrent;
            return (
              <div
                key={attempt.attempt_id}
                data-testid={`attempt-${attempt.attempt_id}`}
                style={{
                  border: isCurrent ? "1px solid #8fbee3" : "1px solid #e3edf5",
                  borderRadius: 10,
                  background: isCurrent ? "#f0f8ff" : "rgba(255,255,255,.6)",
                  padding: "7px 9px",
                  minWidth: 0,
                }}
              >
                <button
                  type="button"
                  aria-expanded={isOpen}
                  data-testid={`attempt-toggle-${attempt.attempt_id}`}
                  onClick={() =>
                    setExpanded((previous) => ({
                      ...previous,
                      [attempt.attempt_id]: !isOpen,
                    }))
                  }
                  style={{
                    width: "100%",
                    minHeight: 36,
                    display: "flex",
                    gap: 7,
                    alignItems: "center",
                    flexWrap: "wrap",
                    padding: 0,
                    border: 0,
                    background: "transparent",
                    color: "inherit",
                    font: "inherit",
                    fontSize: 11.5,
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <span aria-hidden="true" style={{ color: "#6a8296", width: 10 }}>
                    {isOpen ? "▾" : "▸"}
                  </span>
                  <span className="mono" style={{ color: "#526a7d", fontSize: 11 }}>
                    {shortHash(attempt.attempt_id)}
                  </span>
                  <span className={`mon-state ${attemptStatusTone(attempt.status)}`}>
                    {attemptStatusLabel(attempt.status)}
                  </span>
                  {isCurrent && <em style={{ fontStyle: "normal", color: "#0b63b6" }}>当前尝试</em>}
                  <span style={{ color: "#6a8296" }}>
                    {formatTraceTime(attempt.started_at)} → {attempt.ended_at ? formatTraceTime(attempt.ended_at) : "进行中"}
                  </span>
                  <span style={{ color: "#6a8296" }}>{attempt.steps.length} 步</span>
                </button>

                {isOpen && (
                  <div data-testid={`attempt-detail-${attempt.attempt_id}`}>
                    <dl
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                        gap: "6px 10px",
                        margin: "8px 0 0",
                        paddingTop: 8,
                        borderTop: "1px dashed #d7e6f1",
                      }}
                    >
                      {fieldRow("开始", formatTraceTime(attempt.started_at), attempt.started_at)}
                      {fieldRow("结束", attempt.ended_at ? formatTraceTime(attempt.ended_at) : "进行中", attempt.ended_at || "")}
                      {fieldRow("commit", shortHash(attempt.commit), attempt.commit)}
                      {fieldRow("context_hash", shortHash(attempt.context_hash), attempt.context_hash)}
                      {fieldRow("memory_context_hash", shortHash(attempt.memory_context_hash), attempt.memory_context_hash)}
                      {fieldRow("manual_revision", String(attempt.manual_revision))}
                      {fieldRow(
                        "context_injected",
                        attempt.context_injected ? "已注入" : "未注入（仅冻结哈希）",
                      )}
                      {fieldRow("执行路径", attempt.execution_path || "—")}
                      {fieldRow("skill 包", attempt.skill_bundle_hash ? shortHash(attempt.skill_bundle_hash) : "未加载")}
                      {fieldRow("step 数", `${attempt.steps.length} 步`)}
                    </dl>
                    <p style={{ margin: "7px 0 0", fontSize: 10.5, lineHeight: 1.5, color: "#7a8fa2" }}>
                      冻结值：以上哈希、commit 与 revision 在本次尝试结束时记录，不随之后编辑的任务记忆变化。
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mon-note" style={{ marginTop: 8 }}>
        只读：这里是已经结束或正在进行的尝试快照，不是正在编辑的记忆。
      </p>
    </section>
  );
}

export default AttemptHistoryPanel;