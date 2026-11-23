import { Tag } from "antd";
import { taskWaitReason } from "../taskWaitReason";

interface Props {
  plan: any;
  tasks: any[];
  provenance?: any;
  onSelect?: (code: string) => void;
}

const STATE_LABEL: Record<string, string> = {
  pending: "待开始",
  ready: "可调度",
  running: "执行中",
  verifying: "验证中",
  done: "已完成",
  failed: "失败",
  needs_human: "需要人工",
  blocked: "已阻塞",
  skipped: "已跳过",
  cancelled: "已取消",
  stale: "计划已变更",
};

function waitReason(card: any, runtime: any, byCode: Map<string, any>): string {
  if (!runtime) return "等待确认任务计划";
  if (runtime.state === "needs_human") return runtime.last_error || "需要人工裁决";
  return taskWaitReason(runtime, { dependsOn: card?.depends_on || [] }, byCode);
}

export default function TaskPlanPreview({ plan, tasks, provenance, onSelect }: Props) {
  const cards: any[] = plan?.tasks || [];
  const byCode = new Map<string, any>((tasks || []).map((t: any) => [t.code, t]));
  const done = cards.filter((c) => byCode.get(c.code)?.state === "done").length;
  const total = cards.length;

  if (!plan) {
    return (
      <div className="well muted" style={{ padding: 14 }} data-testid="task-plan-preview">
        尚未生成任务计划。设计确认后才会调用任务分解。
      </div>
    );
  }

  return (
    <div className="task-plan-preview" data-testid="task-plan-preview">
      <div className="section-title">
        <span>任务计划</span>
        <span className="hint">
          {total} 个任务 · 已完成 {done} · 容量 {plan.capacity || 40} 点
          {provenance?.generation_label ? ` · ${provenance.generation_label}` : ""}
        </span>
      </div>
      {provenance?.execution_label && (
        <div className="notice" style={{ marginBottom: 8 }}>
          <span>任务执行方式：{provenance.execution_label}</span>
        </div>
      )}
      {total === 0 && <div className="well muted" style={{ padding: 12 }}>任务图为空，不能开始执行</div>}
      <div className="task-plan-list">
        {cards.map((card: any) => {
          const runtime = byCode.get(card.code);
          const state = runtime?.state ?? "pending";
          const reason = waitReason(card, runtime, byCode);
          return (
            <button
              type="button"
              key={card.code}
              className="task-plan-card"
              onClick={() => onSelect?.(card.code)}
              data-state={state}
            >
              <span className={`dot ${state === "done" ? "completed" : ["ready", "running", "verifying"].includes(state) ? "in_progress" : ["pending", "skipped", "cancelled", "stale"].includes(state) ? "pending" : "error"}`} />
              <span className="row-main">
                <span className="row-meta">
                  <span className="code">{card.code}</span>
                  <span className="row-state">{STATE_LABEL[state] || state}</span>
                  <Tag>{card.role}</Tag>
                </span>
                <span className="row-title">
                  <span className="text">{card.title}</span>
                </span>
                <span className="row-sub">
                  依赖 {(card.depends_on || []).join("、") || "无"} · 来源 {(card.sources || []).join("、") || "-"} · 交付物{" "}
                  {(card.outputs?.length ? card.outputs : card.write_set || []).join("、") || "-"}
                </span>
                {(card.acceptance || []).length > 0 && (
                  <span className="row-sub" title="验收条件">
                    验收 {(card.acceptance || []).map((a: any) => (a.cmd || []).join(" ")).join("；")}
                  </span>
                )}
                {reason && <span className="task-plan-reason">{state === "failed" ? "失败原因" : "当前状态"} · {reason}</span>}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
