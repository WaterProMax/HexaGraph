import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { TaskRole, TaskRoleMemory } from "../../api/types";

/** Server limit is 4000 Unicode code points; count code points, never UTF-16 units. */
const MAX_MANUAL_CODE_POINTS = 4000;

export type TaskRoleMemoryPanelProps = {
  runId: string;
  taskCode: string;
  role: TaskRole;
  actorBotId: string;
  /** Fail closed: only an explicit leader grant may enable the write controls. */
  isLeader?: boolean;
};

type RequestIdentity = { runId: string; taskCode: string; role: TaskRole; actorBotId: string };

function shortHash(value: string): string {
  return value ? value.slice(0, 12) : "—";
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

/**
 * Load errors must stay in Chinese and must never echo a raw response payload
 * (FastAPI validation bodies can quote the submitted manual text).
 */
function loadErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404 || err.category === "task_memory_not_found") {
      return "任务不存在或已变化，请刷新任务列表后重试。";
    }
    if (err.status === 403) return "没有权限读取该任务记忆。";
    if (err.status >= 500) {
      return `任务记忆暂时不可用（HTTP ${err.status}），请稍后重试。`;
    }
    if (err.message && err.message.trim()) return err.message;
  }
  return "任务记忆加载失败，请检查网络或后端是否可用。";
}

/**
 * Task/role scoped memory: one automatic role boundary block plus one manual
 * note. It is intentionally not a global memory editor and never shows a bot
 * identity; the backend scope is run + task + role.
 */
export function TaskRoleMemoryPanel({
  runId,
  taskCode,
  role,
  actorBotId,
  isLeader = false,
}: TaskRoleMemoryPanelProps) {
  const [state, setState] = useState<"loading" | "ready" | "forbidden" | "error">("loading");
  const [memory, setMemory] = useState<TaskRoleMemory | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingWrite, setPendingWrite] = useState<"save" | "clear" | null>(null);
  const [writesBlocked, setWritesBlocked] = useState(false);

  const requestSeq = useRef(0);
  const writeSeq = useRef(0);
  const writeInFlight = useRef(false);
  // Latest props, compared after every await so a response (or a 409 reload)
  // for a previous run/task can never overwrite the current one. Assigning the
  // ref during render keeps the comparison current even if the old promise
  // resolves between the prop change render and the effect cleanup.
  const latestProps = useRef<RequestIdentity>({ runId, taskCode, role, actorBotId });
  latestProps.current = { runId, taskCode, role, actorBotId };

  const propsStillCurrent = useCallback((request: RequestIdentity) => {
    const current = latestProps.current;
    return (
      current.runId === request.runId &&
      current.taskCode === request.taskCode &&
      current.role === request.role &&
      current.actorBotId === request.actorBotId
    );
  }, []);

  const isCurrentRequest = useCallback(
    (seq: number, request: RequestIdentity) =>
      seq === requestSeq.current && propsStillCurrent(request),
    [propsStillCurrent],
  );

  const load = useCallback(async () => {
    const request: RequestIdentity = { runId, taskCode, role, actorBotId };
    requestSeq.current += 1;
    const seq = requestSeq.current;
    if (!runId || !taskCode || !actorBotId) {
      if (isCurrentRequest(seq, request)) {
        setState("error");
        setError("缺少运行、任务或身份信息");
      }
      return;
    }
    setState("loading");
    setError("");
    try {
      const data = await api.taskRoleMemory(runId, taskCode, role, actorBotId);
      if (!isCurrentRequest(seq, request)) return;
      setMemory(data);
      setDraft(data.manual_text || "");
      setWritesBlocked(false);
      setState("ready");
    } catch (err) {
      if (!isCurrentRequest(seq, request)) return;
      setMemory(null);
      setDraft("");
      if (err instanceof ApiError && err.status === 403) {
        setState("forbidden");
      } else {
        setState("error");
        setError(loadErrorMessage(err));
      }
    }
  }, [actorBotId, isCurrentRequest, role, runId, taskCode]);

  useEffect(() => {
    // A scope change starts a new request generation: invalidate in-flight
    // writes, drop transient notices, and never let an old write's settlement
    // clear the new scope's busy state.
    writeSeq.current += 1;
    writeInFlight.current = false;
    setPendingWrite(null);
    setWritesBlocked(false);
    setMemory(null);
    setDraft("");
    setNotice("");
    setError("");
    void load();
    return () => {
      // Invalidate in-flight requests when the props change or the panel unmounts.
      requestSeq.current += 1;
      writeSeq.current += 1;
    };
  }, [load]);

  /** Re-read the server revision without touching the user's unsaved draft. */
  const reloadKeepingDraft = useCallback(
    async (request: RequestIdentity): Promise<TaskRoleMemory | null> => {
      const seq = ++requestSeq.current;
      try {
        const data = await api.taskRoleMemory(
          request.runId,
          request.taskCode,
          request.role,
          request.actorBotId,
        );
        if (!isCurrentRequest(seq, request)) return null;
        setMemory(data);
        return data;
      } catch {
        return null;
      }
    },
    [isCurrentRequest],
  );

  const performWrite = async (action: "save" | "clear") => {
    if (!memory || !isLeader || writesBlocked || writeInFlight.current) return;
    if (action === "save" && codePointLength(draft) > MAX_MANUAL_CODE_POINTS) {
      setError(
        `人工补充最多 ${MAX_MANUAL_CODE_POINTS} 个字符（按 code point 计），请精简后再保存。`,
      );
      return;
    }
    const request: RequestIdentity = { runId, taskCode, role, actorBotId };
    const seq = ++writeSeq.current;
    writeInFlight.current = true;
    setPendingWrite(action);
    setError("");
    setNotice("");
    try {
      const data =
        action === "save"
          ? await api.saveTaskRoleMemory(
              runId,
              taskCode,
              role,
              { expected_revision: memory.revision, manual_text: draft },
              actorBotId,
            )
          : await api.deleteTaskRoleMemory(runId, taskCode, role, memory.revision, actorBotId);
      if (seq !== writeSeq.current || !propsStillCurrent(request)) return;
      setMemory(data);
      if (action === "save") {
        setDraft(data.manual_text || "");
        setNotice("已保存，供后续新建尝试使用。");
      } else {
        setDraft("");
        setNotice("已清空本任务该角色的手动补充（仅升 revision，不保留历史原文备份）。");
      }
    } catch (err) {
      if (seq !== writeSeq.current || !propsStillCurrent(request)) return;
      if (err instanceof ApiError && err.status === 403) {
        // A forbidden write means the actor lost access: drop the old-scope
        // sensitive body immediately instead of leaving it on screen.
        setMemory(null);
        setDraft("");
        setNotice("");
        setState("forbidden");
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        if (err.category === "run_busy") {
          // The execution batch holds the run lock: fail fast, keep the draft
          // and the current revision, and never auto-retry or reload over it.
          setError(
            action === "save"
              ? "任务正在执行，本次未保存；当前执行批次结束后请重试。"
              : "任务正在执行，本次未清空；当前执行批次结束后请重试。",
          );
          return;
        }
        if (err.category === "role_mismatch") {
          // The task card now maps to another role: stop writing with the stale
          // role instead of echoing a generic edit conflict.
          setWritesBlocked(true);
          setError("任务角色已变化，请刷新任务选择后再试；本次未保存。");
          return;
        }
        const latest = await reloadKeepingDraft(request);
        if (seq !== writeSeq.current || !propsStillCurrent(request)) return;
        if (err.category === "revision_conflict" || !err.category) {
          setError(
            latest
              ? `版本冲突：服务器当前为 revision ${latest.revision}，你的草稿已保留；请核对后再保存。`
              : "版本冲突：服务器版本已变化，你的草稿已保留；请刷新后核对再保存。",
          );
        } else {
          setError("状态已变化，本次写入未完成；已读取最新版本，请核对草稿后重试。");
        }
        return;
      }
      if (err instanceof ApiError && (err.status === 400 || err.status === 422)) {
        // Do not copy the validation payload: it can quote the submitted text.
        setError(`内容未通过校验（HTTP ${err.status}），请检查长度与格式后重试；本次未保存。`);
        return;
      }
      if (err instanceof ApiError && err.status >= 500) {
        // The backend may have staged the snapshot before failing, so do not
        // claim the write was fully discarded; keep the draft and re-read.
        setError(
          "保存请求未成功（服务器错误），此次写入结果未确认；草稿已保留，请稍后重新读取版本后核对。",
        );
        return;
      }
      setError("操作失败，请稍后重试；草稿已保留。");
    } finally {
      if (seq === writeSeq.current && propsStillCurrent(request)) {
        writeInFlight.current = false;
        setPendingWrite(null);
      }
    }
  };

  const draftCodePoints = codePointLength(draft);
  const overLimit = draftCodePoints > MAX_MANUAL_CODE_POINTS;
  const busy = pendingWrite !== null;

  return (
    <section
      data-testid="task-role-memory"
      aria-label={`任务 ${taskCode} 的 ${role} 角色记忆`}
      style={{
        marginTop: 16,
        padding: 12,
        border: "1px solid rgba(82,115,140,.18)",
        borderRadius: 14,
        background: "rgba(255,255,255,.55)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <strong style={{ color: "var(--glass-ink, #122d42)" }}>任务记忆 · {role}</strong>
        <span style={{ fontSize: 11, color: "var(--glass-muted, #405c71)" }}>
          任务 {taskCode} · revision {memory?.revision ?? "—"}
        </span>
      </div>

      {state === "loading" && <p role="status">正在加载任务记忆…</p>}
      {state === "forbidden" && (
        <p role="alert" data-testid="task-role-memory-forbidden">
          没有权限读取该任务记忆。
        </p>
      )}
      {state === "error" && (
        <p role="alert" data-testid="task-role-memory-error">
          {error}
        </p>
      )}

      {state === "ready" && memory && (
        <>
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 650, color: "var(--glass-secondary, #304b60)" }}>
              自动角色边界（只读）
            </div>
            <pre
              data-testid="task-role-memory-role-section"
              style={{
                margin: "6px 0 0",
                whiteSpace: "pre-wrap",
                fontFamily: "inherit",
                fontSize: 12,
                lineHeight: 1.55,
                color: "var(--glass-secondary, #304b60)",
                maxHeight: 220,
                overflow: "auto",
              }}
            >
              {memory.role_section.text}
            </pre>
            <div style={{ fontSize: 11, color: "var(--glass-muted, #405c71)", marginTop: 4 }}>
              来源 hash：{shortHash(memory.role_section.sha256)} · context {shortHash(memory.context_hash)}
              {memory.frozen
                ? " · 已记录上下文版本（是否注入取决于执行路径，当前接口未提供消费证明）"
                : ""}
            </div>
          </div>

          <label style={{ display: "block", marginTop: 12 }}>
            <span style={{ fontSize: 12, fontWeight: 650, color: "var(--glass-secondary, #304b60)" }}>
              人工补充（仅本任务、本角色）
            </span>
            <textarea
              aria-label="任务角色人工补充"
              data-testid="task-role-memory-input"
              rows={4}
              value={draft}
              readOnly={!isLeader || writesBlocked}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                isLeader
                  ? "补充约束、偏好或注意事项；不会覆盖系统与安全规则。"
                  : "只读：只有项目 Leader 可以编辑。"
              }
              style={{
                width: "100%",
                marginTop: 6,
                boxSizing: "border-box",
                padding: 8,
                borderRadius: 10,
                border: "1px solid rgba(82,115,140,.24)",
                background: isLeader ? "rgba(255,255,255,.72)" : "rgba(240,244,248,.72)",
                color: "var(--glass-ink, #122d42)",
                font: "inherit",
              }}
            />
            <span
              data-testid="task-role-memory-count"
              style={{
                display: "block",
                marginTop: 4,
                fontSize: 11,
                textAlign: "right",
                color: overLimit ? "#9b2c2c" : "var(--glass-muted, #405c71)",
              }}
            >
              {draftCodePoints} / {MAX_MANUAL_CODE_POINTS}
            </span>
          </label>
          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
            <button
              type="button"
              className="disc-btn"
              data-testid="task-role-memory-save"
              disabled={busy || !isLeader || writesBlocked || overLimit}
              title={isLeader ? undefined : "只有项目 Leader 可以编辑任务记忆"}
              onClick={() => void performWrite("save")}
            >
              {pendingWrite === "save" ? "保存中…" : "保存"}
            </button>
            <button
              type="button"
              className="disc-btn disc-btn-danger"
              data-testid="task-role-memory-clear"
              disabled={busy || !memory.manual_text || !isLeader || writesBlocked}
              title={isLeader ? undefined : "只有项目 Leader 可以编辑任务记忆"}
              onClick={() => void performWrite("clear")}
            >
              {pendingWrite === "clear" ? "清空中…" : "清空"}
            </button>
            <span style={{ fontSize: 11, color: "var(--glass-muted, #405c71)" }}>
              {!isLeader
                ? "只读：只有项目 Leader 可以编辑"
                : writesBlocked
                  ? "任务角色已变化，请刷新任务选择"
                  : overLimit
                    ? "超出长度上限，请精简后再保存"
                    : memory.effective === "next_attempt"
                      ? "当前执行中；修改从下次尝试生效"
                      : "保存后用于后续新建尝试"}
            </span>
          </div>
          {notice && (
            <p role="status" data-testid="task-role-memory-notice" style={{ fontSize: 12 }}>
              {notice}
            </p>
          )}
          {error && (
            <p role="alert" data-testid="task-role-memory-conflict" style={{ fontSize: 12, color: "#9b2c2c" }}>
              {error}
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default TaskRoleMemoryPanel;