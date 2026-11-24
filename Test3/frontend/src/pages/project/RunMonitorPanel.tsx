import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Modal, Tooltip, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, controlEnabled } from "../../api/client";
import type { MonitorTask } from "../../api/types";
import { useRunEvents } from "../../hooks/useRunEvents";
import { isTerminalRunStatus, pauseResumeKind } from "../workstationControls";
import {
  MONITOR_FILTERS,
  REASON_REQUIRED_ACTIONS,
  TASK_ACTIONS,
  TASK_ACTION_LABELS,
  buildMonitorGroups,
  eventLabel,
  fallbackMonitorTasks,
  formatClock,
  formatDuration,
  formatNumber,
  type FallbackMonitorTask,
  type MonitorFilter,
} from "./runMonitor";
import { useRunMonitor } from "./useRunMonitor";
import "./runMonitor.css";

const TERMINAL_TASK_STATES = new Set(["done", "skipped", "cancelled"]);

type Props = {
  runId?: string;
  tasks: FallbackMonitorTask[];
  onLocateTask?: (code: string) => void;
  onRefresh?: () => void;
};

function statusLabel(state: string): string {
  const labels: Record<string, string> = {
    pending: "待开始",
    ready: "就绪",
    running: "运行中",
    verifying: "校验中",
    done: "已完成",
    failed: "失败",
    needs_human: "需处理",
    blocked: "阻塞",
    skipped: "已跳过",
    cancelled: "已取消",
    stale: "已过期",
  };
  return labels[state] || state;
}

export function RunMonitorPanel({ runId, tasks, onLocateTask, onRefresh }: Props) {
  const monitor = useRunMonitor(runId);
  const { events, connection, connectionError, reconnect } = useRunEvents(runId, () => {
    void monitor.refresh(true);
  });
  const [filter, setFilter] = useState<MonitorFilter>("all");
  const [selected, setSelected] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [runBusy, setRunBusy] = useState("");
  const [feedback, setFeedback] = useState("");

  const fallback = useMemo(() => fallbackMonitorTasks(tasks), [tasks]);
  const rows = monitor.data?.tasks || fallback;
  const groups = useMemo(
    () => buildMonitorGroups(monitor.data, fallback, filter),
    [monitor.data, fallback, filter],
  );
  const selectedTask = rows.find((task) => task.code === selected) || null;
  const summary = monitor.data?.run;
  const counts = summary || {
    total: rows.length,
    done: rows.filter((task) => task.status === "done").length,
    running: rows.filter((task) => task.status === "running").length,
    failed: rows.filter((task) => task.status === "failed").length,
    blocked: rows.filter((task) => task.status === "blocked").length,
    progress: rows.length
      ? Math.round((rows.filter((task) => task.status === "done").length * 100) / rows.length)
      : 0,
    tokens_used: rows.reduce((sum, task) => sum + task.tokens_used, 0),
    repair_rounds: rows.reduce((sum, task) => sum + task.repair_rounds, 0),
    fallback_count: 0,
    elapsed_seconds: null as number | null,
  };
  const recentEvents = events.slice(-24).reverse();
  const terminalRun = isTerminalRunStatus(summary?.status);
  const pauseKind = summary ? pauseResumeKind(summary) : null;
  const readyCount = Number(summary?.state_counts?.ready || 0);
  const canSchedule = Boolean(summary && !terminalRun && !summary.paused && readyCount > 0);

  useEffect(() => {
    if (selected && !rows.some((task) => task.code === selected)) setSelected("");
  }, [rows, selected]);

  const refreshAll = async () => {
    await monitor.refresh();
    onRefresh?.();
  };

  const applyAction = async (task: MonitorTask, action: string) => {
    setBusyAction(action);
    setFeedback("");
    try {
      await api.control(task.code, action, task.revision, reason);
      setFeedback(`${task.code} ${TASK_ACTION_LABELS[action] || action}已提交`);
      message.success(`${task.code} ${TASK_ACTION_LABELS[action] || action}已提交`);
      setReason("");
      await refreshAll();
    } catch (err: any) {
      const text = err?.message || "控制失败";
      setFeedback(text);
      message.error(text);
    } finally {
      setBusyAction("");
    }
  };

  const confirmTaskAction = (task: MonitorTask, action: string) => {
    const label = TASK_ACTION_LABELS[action] || action;
    if (!controlEnabled(action, task.state)) return;
    if (REASON_REQUIRED_ACTIONS.has(action) && !reason.trim()) {
      setFeedback(`${label}必须填写理由`);
      return;
    }
    MetaConfirm({
      title: `确认${label}任务 ${task.code}？`,
      content: `当前状态：${statusLabel(task.state)}。${reason.trim() ? `理由：${reason.trim()}` : "未填写控制理由。"}`,
      danger: action === "skip" || action === "force-pass" || action === "takeover" || action === "submit-takeover",
      onOk: () => applyAction(task, action),
    });
  };

  const runAction = async (action: "pause" | "resume" | "schedule" | "terminate") => {
    if (!runId) return;
    setRunBusy(action);
    setFeedback("");
    try {
      if (action === "pause") await api.pauseRun(runId);
      else if (action === "resume") await api.resumeRun(runId);
      else if (action === "schedule") await api.schedule(runId);
      else await api.terminate(runId);
      const labels = { pause: "暂停", resume: "恢复", schedule: "调度", terminate: "终止" };
      setFeedback(`运行${labels[action]}已提交`);
      message.success(`运行${labels[action]}已提交`);
      await refreshAll();
    } catch (err: any) {
      const text = err?.message || "运行控制失败";
      setFeedback(text);
      message.error(text);
    } finally {
      setRunBusy("");
    }
  };

  const confirmRunAction = (action: "pause" | "resume" | "schedule" | "terminate") => {
    const labels = { pause: "暂停", resume: "恢复", schedule: "调度", terminate: "终止" };
    MetaConfirm({
      title: `确认${labels[action]}当前运行？`,
      content:
        action === "terminate"
          ? "终止后本次运行不能继续，未完成的任务会被取消。"
          : action === "schedule"
            ? "将调度一轮已就绪任务。"
            : `运行将${labels[action]}。`,
      danger: action === "terminate",
      onOk: () => runAction(action),
    });
  };

  return (
    <div className="run-monitor" data-testid="run-monitor">
      <div className="mon-head">
        <div>
          <div className="mon-kicker">运行监控</div>
          <div className="mon-head-title">
            <span className="mono">{runId || "未绑定运行"}</span>
            <span className={`mon-connection ${connection}`}>{connection === "live" ? "实时" : connection === "error" ? "连接断开" : "连接中"}</span>
          </div>
        </div>
        <div className="mon-run-actions">
          <Tooltip title="刷新监控数据">
            <Button size="small" type="text" icon={<ReloadOutlined />} aria-label="刷新监控" onClick={() => void refreshAll()} />
          </Tooltip>
          {summary && (
            <>
              {pauseKind && (
                <Button
                  size="small"
                  loading={runBusy === pauseKind}
                  onClick={() => confirmRunAction(pauseKind)}
                >
                  {pauseKind === "resume" ? "恢复运行" : "暂停运行"}
                </Button>
              )}
              <Button
                size="small"
                type="primary"
                disabled={!canSchedule || terminalRun}
                loading={runBusy === "schedule"}
                onClick={() => confirmRunAction("schedule")}
              >
                调度执行
              </Button>
              <Button
                size="small"
                danger
                disabled={terminalRun}
                loading={runBusy === "terminate"}
                onClick={() => confirmRunAction("terminate")}
              >
                终止
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="mon-kpis" data-testid="monitor-kpis">
        <div className="mon-kpi"><span>任务进度</span><strong>{counts.done}/{counts.total || 0}</strong><em>{counts.progress}%</em></div>
        <div className="mon-kpi tone-running"><span>运行中</span><strong>{counts.running}</strong><em>实时执行</em></div>
        <div className="mon-kpi tone-failed"><span>失败/需处理</span><strong>{counts.failed}</strong><em>等待处理</em></div>
        <div className="mon-kpi tone-blocked"><span>阻塞</span><strong>{counts.blocked}</strong><em>依赖未就绪</em></div>
        <div className="mon-kpi"><span>Token</span><strong>{formatNumber(counts.tokens_used)}</strong><em>{formatDuration(counts.elapsed_seconds)}</em></div>
        <div className="mon-kpi"><span>修复 / 回退</span><strong>{counts.repair_rounds} / {counts.fallback_count}</strong><em>轮次 / 次</em></div>
      </div>

      {monitor.error && (
        <Alert
          type="warning"
          showIcon
          message={monitor.error}
          description={monitor.data ? "已保留上一帧监控数据。" : "当前显示任务列表兜底数据。"}
          style={{ marginBottom: 12 }}
        />
      )}
      {feedback && <div className="mon-feedback" role="status">{feedback}</div>}

      <div className="mon-body">
        <div className="mon-task-column">
          <div className="mon-toolbar">
            <div className="mon-filters" role="group" aria-label="任务筛选">
              {MONITOR_FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`mon-filter ${filter === item.key ? "active" : ""}`}
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <span className="mon-count">{groups.reduce((sum, group) => sum + group.tasks.length, 0)} 个任务</span>
          </div>

          {!runId && <div className="mon-note">还没有绑定运行，以下为项目最新任务列表。</div>}
          <div className="mon-packages">
            {groups.map((group) => {
              const key = group.code || "loose";
              const isCollapsed = Boolean(collapsed[key]);
              return (
                <section className="mon-package" key={key} data-testid={`monitor-package-${key}`}>
                  <button
                    type="button"
                    className="mon-package-head"
                    aria-expanded={!isCollapsed}
                    onClick={() => setCollapsed((prev) => ({ ...prev, [key]: !isCollapsed }))}
                  >
                    <span className="mon-chevron">{isCollapsed ? "▸" : "▾"}</span>
                    <span className="mon-package-code mono">{group.code || "—"}</span>
                    <span className="mon-package-title">{group.title}</span>
                    <span className="mon-package-counts">
                      {group.done}/{group.total} · {group.progress}%
                    </span>
                  </button>
                  {!isCollapsed && (
                    <div className="mon-package-tasks">
                      {group.tasks.length === 0 && <div className="mon-note">没有符合筛选的任务。</div>}
                      {group.tasks.map((task) => {
                        const terminal = TERMINAL_TASK_STATES.has(task.state);
                        return (
                          <button
                            type="button"
                            key={task.code}
                            className={`mon-task ${selected === task.code ? "selected" : ""}`}
                            onClick={() => {
                              setSelected(task.code);
                              setReason("");
                              setFeedback("");
                            }}
                          >
                            <span className={`mon-state-dot ${task.status}`} aria-hidden="true" />
                            <span className="mono mon-task-code">{task.code}</span>
                            <span className="mon-task-title" title={task.title}>{task.title}</span>
                            <span className={`mon-state ${task.status}`}>{terminal ? statusLabel(task.state) : task.status === "running" ? "运行中" : statusLabel(task.state)}</span>
                            <span className="mon-task-meta">{task.role || "—"} · {formatNumber(task.tokens_used)} tok · 修复 {task.repair_rounds}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </div>

        <aside className="mon-inspector" aria-label="任务控制">
          <div className="mon-inspector-head">
            <strong>任务控制</strong>
            {selectedTask && onLocateTask && (
              <Button size="small" type="link" onClick={() => onLocateTask(selectedTask.code)}>
                在任务树中定位
              </Button>
            )}
          </div>
          {!selectedTask ? (
            <div className="mon-empty">
              <strong>选择一个任务</strong>
              <span>查看状态、理由输入和执行控制。</span>
            </div>
          ) : (
            <div className="mon-inspector-body">
              <div className="mon-inspector-title">
                <span className="mono">{selectedTask.code}</span>
                <span className={`mon-state ${selectedTask.status}`}>{statusLabel(selectedTask.state)}</span>
              </div>
              <h3>{selectedTask.title}</h3>
              <div className="mon-metrics">
                <span>角色 <b>{selectedTask.role || "—"}</b></span>
                <span>模型 <b>{selectedTask.model || "—"}</b></span>
                <span>Token <b>{formatNumber(selectedTask.tokens_used)}</b></span>
                <span>修复 <b>{selectedTask.repair_rounds}</b></span>
                <span>证据 <b>{selectedTask.evidence_count}</b></span>
                <span>耗时 <b>{formatDuration(selectedTask.duration_seconds)}</b></span>
              </div>
              {selectedTask.last_error && (
                <div className="mon-error" title={selectedTask.last_error}>
                  最近失败：{selectedTask.last_error}
                </div>
              )}
              {selectedTask.blocked_by.length > 0 && (
                <div className="mon-blocked">被阻塞：{selectedTask.blocked_by.join(", ")}</div>
              )}
              <label className="mon-reason-label">
                <span>控制理由（跳过、强制通过必填）</span>
                <Input.TextArea
                  aria-label="任务控制理由"
                  rows={2}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="说明为什么要执行这次控制"
                />
              </label>
              <div className="mon-actions">
                {TASK_ACTIONS.map((action) => {
                  const enabled = controlEnabled(action, selectedTask.state);
                  const needsReason = REASON_REQUIRED_ACTIONS.has(action);
                  const blocked = !enabled || (needsReason && !reason.trim());
                  const hint = !enabled
                    ? `${TASK_ACTION_LABELS[action]}不适用于当前状态`
                    : needsReason && !reason.trim()
                      ? "请先填写控制理由"
                      : TASK_ACTION_LABELS[action];
                  return (
                    <Tooltip key={action} title={hint}>
                      <span>
                        <Button
                          size="small"
                          danger={action === "skip" || action === "force-pass"}
                          disabled={blocked || Boolean(busyAction)}
                          loading={busyAction === action}
                          onClick={() => confirmTaskAction(selectedTask, action)}
                        >
                          {TASK_ACTION_LABELS[action]}
                        </Button>
                      </span>
                    </Tooltip>
                  );
                })}
              </div>
            </div>
          )}

          <div className="mon-events" data-testid="monitor-events">
            <div className="mon-events-head">
              <strong>实时事件</strong>
              {connection === "error" && (
                <Button size="small" type="link" onClick={reconnect}>重连</Button>
              )}
            </div>
            {connectionError && <div className="mon-note">{connectionError}</div>}
            {recentEvents.length === 0 && <div className="mon-note">还没有事件。</div>}
            {recentEvents.map((event) => (
              <div className="mon-event" key={`${event.seq}-${event.kind}`}>
                <time>{formatClock(event.ts)}</time>
                <span className="mon-event-kind">{eventLabel(event.kind)}</span>
                <span className="mon-event-subject" title={String(event.subject || "")}>{event.subject || "—"}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

function MetaConfirm(opts: { title: string; content: string; danger?: boolean; onOk: () => Promise<void> | void }) {
  Modal.confirm({
    title: opts.title,
    content: opts.content,
    okText: "确认",
    cancelText: "取消",
    okButtonProps: { danger: opts.danger },
    onOk: async () => {
      await opts.onOk();
    },
  });
}