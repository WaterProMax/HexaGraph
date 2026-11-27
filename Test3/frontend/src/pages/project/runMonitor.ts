import type { MonitorAgent, MonitorSnapshot, MonitorTask } from "../../api/types";

export type MonitorFilter = "all" | "running" | "failed" | "blocked";

export const MONITOR_FILTERS: Array<{ key: MonitorFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "running", label: "运行中" },
  { key: "failed", label: "失败/需处理" },
  { key: "blocked", label: "阻塞" },
];

export const TASK_ACTION_LABELS: Record<string, string> = {
  pause: "暂停",
  resume: "恢复",
  retry: "重试",
  skip: "跳过",
  "force-pass": "强制通过",
  takeover: "接管",
  "submit-takeover": "提交接管",
};

export const TASK_ACTIONS = Object.keys(TASK_ACTION_LABELS);
export const REASON_REQUIRED_ACTIONS = new Set(["skip", "force-pass"]);

export type FallbackMonitorTask = { code: string; title: string; progress: number; status: string };

export type MonitorGroup = {
  code: string;
  title: string;
  module: string;
  total: number;
  done: number;
  running: number;
  failed: number;
  blocked: number;
  pending: number;
  skipped: number;
  progress: number;
  tasks: MonitorTask[];
};

export function normalizeTaskStatus(state: string): string {
  if (state === "done") return "done";
  if (state === "running" || state === "verifying") return "running";
  if (state === "failed" || state === "needs_human") return "failed";
  if (state === "blocked") return "blocked";
  if (state === "pending" || state === "ready") return "pending";
  if (state === "skipped" || state === "cancelled" || state === "stale") return "skipped";
  return state || "pending";
}

export function fallbackMonitorTasks(tasks: FallbackMonitorTask[]): MonitorTask[] {
  return tasks.map((task) => ({
    code: task.code,
    title: task.title,
    state: task.status,
    status: normalizeTaskStatus(task.status),
    role: "",
    slot: "",
    model: "",
    module: "",
    parent: "",
    points: 0,
    tokens_used: 0,
    repair_rounds: 0,
    last_error: "",
    blocked_by: [],
    waiting_on: [],
    evidence_count: 0,
    review_issue_count: 0,
    revision: 0,
    paused: false,
    duration_seconds: null,
    execution_path: "",
    context_injected: false,
    execution_step_count: 0,
    last_execution_step: null,
    assignee_bot_id: null,
    assignee_display_name: null,
  }));
}

export function taskMatchesFilter(task: MonitorTask, filter: MonitorFilter): boolean {
  if (filter === "all") return true;
  if (filter === "failed") return task.status === "failed";
  return task.status === filter;
}

export function filterMonitorTasks(tasks: MonitorTask[], filter: MonitorFilter): MonitorTask[] {
  return tasks.filter((task) => taskMatchesFilter(task, filter));
}

function rollup(tasks: MonitorTask[]) {
  const count = (status: string) => tasks.filter((task) => task.status === status).length;
  const done = count("done");
  return {
    total: tasks.length,
    done,
    running: count("running"),
    failed: count("failed"),
    blocked: count("blocked"),
    pending: count("pending"),
    skipped: count("skipped"),
    progress: tasks.length ? Math.round((done * 100) / tasks.length) : 0,
  };
}

export function buildMonitorGroups(
  snapshot: MonitorSnapshot | null,
  fallback: MonitorTask[],
  filter: MonitorFilter,
): MonitorGroup[] {
  const tasks = filterMonitorTasks(snapshot?.tasks || fallback, filter);
  const packages = snapshot?.work_packages || [];
  if (!packages.length) {
    return [{ code: "", title: "全部任务", module: "", ...rollup(tasks), tasks }];
  }
  const known = new Set(packages.map((item) => item.code));
  const groups = packages.map((item) => {
    const rows = tasks.filter((task) => task.parent === item.code);
    return {
      code: item.code,
      title: item.title,
      module: item.module,
      ...rollup(rows),
      tasks: rows,
    };
  });
  const loose = tasks.filter((task) => !known.has(task.parent));
  if (loose.length) {
    groups.push({ code: "", title: "未归入工作包", module: "", ...rollup(loose), tasks: loose });
  }
  return filter === "all" ? groups : groups.filter((group) => group.tasks.length > 0);
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatClock(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

export function eventLabel(kind: string): string {
  const labels: Record<string, string> = {
    "task.state_changed": "任务状态",
    "task.evidence": "任务证据",
    "task.spawned": "派生任务",
    "task.write_denied": "写入被拒",
    // A1 dispatch overlay events: annotation only, the memory subject stays role-scoped.
    "task.assigned": "任务已派发",
    "task.assignment_cleared": "已取消派发",
    // I0 step events: high-frequency, summarised only; no I/O text beyond the
    // pre-truncated payload fields.
    "task.llm_step": "模型步骤",
    "task.tool_step": "工具步骤",
    "task.granted_command": "授权命令",
    "gate.created": "关卡创建",
    "gate.resolved": "关卡处理",
    "llm.fallback": "模型回退",
    "schedule.rejected": "调度被拒",
    "schedule.started": "调度开始",
    "baseline.hash": "基线哈希",
    "baseline.frozen": "基线冻结",
    "stage.changed": "阶段变化",
    "system.limit_changed": "限额调整",
    "task.late_result_ignored": "迟到结果已忽略",
    "budget.warn": "预算预警",
    "budget.exceeded": "预算超限",
    "control.pause": "暂停",
    "control.resume": "恢复",
    "control.retry": "重试",
    "control.skip": "跳过",
    "control.force-pass": "强制通过",
    "control.takeover": "接管",
    "control.submit-takeover": "提交接管",
    "control.terminate": "终止",
  };
  return labels[kind] || kind;
}

function csvCell(value: unknown): string {
  let text = String(value ?? "");
  // Prevent spreadsheet formula injection in exported evaluation files.
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function agentsToCsv(agents: MonitorAgent[]): string {
  const header = [
    "角色",
    "模型",
    "槽位",
    "任务数",
    "完成",
    "失败",
    "成功率(%)",
    "Token",
    "平均修复轮次",
    "模型回退",
    "平均耗时(s)",
    "失败原因",
  ];
  const rows = agents.map((agent) => [
    agent.role,
    agent.model,
    agent.slot,
    agent.total,
    agent.done,
    agent.failed,
    agent.success_rate,
    agent.tokens_used,
    agent.avg_repair_rounds,
    agent.fallback_count,
    agent.avg_task_seconds ?? "",
    agent.failure_reasons.map((item) => `${item.reason}×${item.count}`).join("；"),
  ]);
  return [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}