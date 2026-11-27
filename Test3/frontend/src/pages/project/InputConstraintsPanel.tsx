import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { GrantStatus, TaskRole } from "../../api/types";
import { TaskRoleMemoryPanel } from "./TaskRoleMemoryPanel";

/**
 * Read-only "input & constraints" view for one task on the project main path.
 *
 * The project page used to show only a task code/state plus an in-memory note;
 * this panel turns the persisted task card (role, depends_on, write_set,
 * acceptance, description, budget), the approved SPEC it came from, the frozen
 * context state of the last attempt and the task/role memory into visible input.
 *
 * It never edits anything. The full task-memory editor stays in the run monitor.
 */

export type TaskAcceptance = {
  cmd?: string[] | string;
  passCriteria?: string;
  fromCriterion?: string;
};

export type TaskBudget = {
  max_tool_steps?: number;
  max_tokens?: number;
  max_seconds?: number;
};

/** Everything this panel reads from a task card / attempt; all optional but code/title. */
export type TaskInputConstraints = {
  code: string;
  title: string;
  role?: string;
  dependsOn?: string[];
  writeSet?: string[];
  acceptance?: TaskAcceptance[];
  description?: string;
  module?: string;
  parent?: string;
  points?: number;
  budget?: TaskBudget;
  /** From the last attempt (`attempt.context_injected`); undefined when nothing ran yet. */
  contextInjected?: boolean;
  /** `attempt.execution_path`: simulated / granted_v1 / legacy_tool_agent. */
  executionPath?: string;
  /** `attempt.skill_bundle_hash`; frozen hash only, never proof of what was injected. */
  skillBundleHash?: string;
};

export type InputConstraintsPanelProps = {
  task?: TaskInputConstraints | null;
  /** Run whose approved SPEC is summarised; omit to skip the SPEC read. */
  runId?: string;
  /** Local actor, used for the read-only task/role memory read. */
  actorBotId?: string;
  grantStatus?: GrantStatus;
  grantErrorCategory?: string | null;
  /** Jump to the inline full-spec panel (the body is already on screen). */
  onShowFullSpec?: () => void;
  /** The classroom grid hides the read-only memory block; single view keeps it. */
  showMemory?: boolean;
};

type SpecState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error" }
  | { status: "ready"; spec: any; baseline?: string };

const GRANT_LABELS: Record<GrantStatus, string> = {
  active: "有效（active）",
  stale: "已过期（stale）",
  revoked: "已撤销（revoked）",
  consumed: "已消耗（consumed）",
};

const EXECUTION_PATH_LABELS: Record<string, string> = {
  simulated: "simulated（模拟执行）",
  granted_v1: "granted_v1（授权命令执行）",
  legacy_tool_agent: "legacy_tool_agent（旧版工具 Agent）",
};

function shortHash(value: string): string {
  return value ? value.slice(0, 12) : "";
}

function cmdText(cmd: TaskAcceptance["cmd"]): string {
  if (Array.isArray(cmd)) return cmd.join(" ");
  return cmd ? String(cmd) : "";
}

function specCounts(spec: any) {
  const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);
  return {
    scenarios: count(spec?.scenarios),
    features: count(spec?.features),
    nonfunc: count(spec?.nonfunc),
    outOfScope: count(spec?.out_of_scope),
    openQuestions: count(spec?.open_questions),
  };
}

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="input-meta-row">
      <dt className="input-meta-label">{label}</dt>
      <dd className="input-meta-value">{children}</dd>
    </div>
  );
}

export function InputConstraintsPanel({
  task,
  runId,
  actorBotId,
  grantStatus,
  grantErrorCategory = null,
  onShowFullSpec,
  showMemory = true,
}: InputConstraintsPanelProps) {
  const [spec, setSpec] = useState<SpecState>({ status: "idle" });

  useEffect(() => {
    if (!runId) {
      setSpec({ status: "idle" });
      return;
    }
    let cancelled = false;
    setSpec({ status: "loading" });
    api
      .artifacts(runId)
      .then((artifacts: any) => {
        if (cancelled) return;
        const loaded = artifacts?.spec;
        if (!loaded) {
          setSpec({ status: "empty" });
          return;
        }
        setSpec({ status: "ready", spec: loaded, baseline: artifacts?.baseline_SPEC });
      })
      .catch(() => {
        if (!cancelled) setSpec({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const memoryRole: TaskRole | null = useMemo(() => {
    const role = String(task?.role || "");
    return role === "coder" || role === "tester" ? (role as TaskRole) : null;
  }, [task?.role]);

  if (!task) {
    return (
      <section className="input-constraints" data-testid="input-constraints" aria-label="输入与约束">
        <div className="muted" data-testid="input-constraints-empty">
          在左侧选择一个任务，查看它的输入、依赖、写入范围与验收约束。
        </div>
      </section>
    );
  }

  const dependsOn = Array.isArray(task.dependsOn) ? task.dependsOn.filter(Boolean) : [];
  const writeSet = Array.isArray(task.writeSet) ? task.writeSet.filter(Boolean) : [];
  const acceptance = Array.isArray(task.acceptance) ? task.acceptance : [];
  const budget = task.budget || {};
  const counts = spec.status === "ready" ? specCounts(spec.spec) : null;
  const features: any[] = spec.status === "ready" && Array.isArray(spec.spec?.features) ? spec.spec.features : [];

  const injection = (() => {
    if (task.contextInjected === true) {
      if (!task.skillBundleHash) {
        return {
          tone: "warn",
          title: "已注入任务上下文（角色/手动段）",
          detail: "已注入角色/手动段；公共 skill 包未导入或加载失败",
        };
      }
      return {
        tone: "ok",
        title: "已记录向模型提示词注入任务上下文",
        detail: `已注入角色/手动段；冻结的 skill 包哈希：${shortHash(task.skillBundleHash)}。该哈希只表示本次冻结记录，不代表已加载的技能数量。`,
      };
    }
    if (task.contextInjected === false) {
      return {
        tone: "muted",
        title: "未向模型提示词注入任务上下文",
        detail: "本尝试仅冻结上下文哈希，未向模型提示词注入任务上下文（路径：simulated / granted_v1）",
      };
    }
    return {
      tone: "muted",
      title: "尚无执行尝试记录",
      detail: "无法确认是否向模型提示词注入任务上下文。",
    };
  })();

  return (
    <section className="input-constraints" data-testid="input-constraints" aria-labelledby="input-constraints-heading">
      <div className="section-title input-head">
        <span id="input-constraints-heading">输入与约束</span>
        <span className="input-head-code mono">{task.code}</span>
      </div>

      <div className="input-body">
        <h3 className="input-task-title">{task.title}</h3>

        <dl className="input-meta" data-testid="input-task-meta">
          <MetaRow label="角色">{task.role || "未标注角色"}</MetaRow>
          <MetaRow label="依赖">
            {dependsOn.length > 0 ? (
              <span className="mono">{dependsOn.join("、")}</span>
            ) : (
              "无前置依赖（根任务）"
            )}
          </MetaRow>
          <MetaRow label="写入范围">
            {writeSet.length > 0 ? (
              <span className="mono">{writeSet.join("、")}</span>
            ) : (
              "任务卡未声明写入范围"
            )}
          </MetaRow>
          <MetaRow label="模块 / 父任务 / 点数">
            {[task.module || "未标注模块", task.parent ? `父任务 ${task.parent}` : "无父任务", task.points != null ? `${task.points} 点` : "点数未提供"].join(" · ")}
          </MetaRow>
          <MetaRow label="迭代预算">
            {task.budget
              ? [
                  budget.max_tool_steps != null ? `最多 ${budget.max_tool_steps} 个工具步骤` : "",
                  budget.max_tokens != null ? `最多 ${budget.max_tokens} 令牌` : "",
                  budget.max_seconds != null ? `最多 ${budget.max_seconds} 秒` : "",
                ]
                  .filter(Boolean)
                  .join(" · ") || "预算字段为空"
              : "任务卡未提供预算"}
          </MetaRow>
        </dl>

        {task.description && (
          <p className="input-task-description" data-testid="input-task-description">
            {task.description}
          </p>
        )}

        <section className="input-section" aria-labelledby="input-acceptance-heading">
          <div className="section-title">
            <span id="input-acceptance-heading">验收标准</span>
          </div>
          {acceptance.length === 0 ? (
            <p className="input-note">任务卡未提供验收标准。</p>
          ) : (
            <ul className="input-acceptance" data-testid="input-acceptance">
              {acceptance.map((item, index) => (
                <li key={index}>
                  <code className="mono">{cmdText(item.cmd) || "（无命令）"}</code>
                  <span className="input-acceptance-note">通过条件：{item.passCriteria || "未提供"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="input-section" aria-labelledby="input-spec-heading" data-testid="input-spec-summary">
          <div className="section-title">
            <span id="input-spec-heading">已批准 SPEC 摘要</span>
          </div>
          {spec.status === "idle" && <p className="input-note">没有绑定运行，无法读取已批准 SPEC。</p>}
          {spec.status === "loading" && (
            <p className="input-note" role="status">
              正在载入已批准规格…
            </p>
          )}
          {spec.status === "error" && (
            <p className="input-note" role="alert" data-testid="input-spec-error">
              暂时无法载入已批准规格
            </p>
          )}
          {spec.status === "empty" && <p className="input-note">尚未生成已批准 SPEC（等待 SPEC 关卡批准）。</p>}
          {spec.status === "ready" && counts && (
            <div data-testid="input-spec-body">
              <p className="input-spec-line">{spec.baseline ? `已批准 SPEC · 基线 v${spec.baseline}` : "已批准 SPEC"}</p>
              <p className="input-spec-counts">
                场景 {counts.scenarios} · 功能 {counts.features} · 非功能 {counts.nonfunc} · 范围外 {counts.outOfScope} · 待定问题 {counts.openQuestions}
              </p>
              {features.length > 0 && (
                <ul className="input-spec-features">
                  {features.slice(0, 3).map((feature) => (
                    <li key={feature.code || feature.title}>
                      <span className="mono">{feature.code}</span> {feature.title}
                    </li>
                  ))}
                  {features.length > 3 && <li className="input-note">还有 {features.length - 3} 项功能</li>}
                </ul>
              )}
            </div>
          )}
          {onShowFullSpec && runId && (
            <button
              type="button"
              className="chip input-spec-full-link"
              data-testid="input-spec-full-link"
              onClick={onShowFullSpec}
            >
              在规格栏查看全文
            </button>
          )}
        </section>

        <section className="input-section" aria-labelledby="input-context-heading" data-testid="input-context-injection">
          <div className="section-title">
            <span id="input-context-heading">上下文注入状态</span>
            <span className="hint">{EXECUTION_PATH_LABELS[String(task.executionPath || "")] || task.executionPath || "路径未知"}</span>
          </div>
          <p
            className="input-context-state"
            data-testid="input-context-state"
            data-tone={injection.tone}
          >
            <strong>{injection.title}。 </strong>
            {injection.detail}
          </p>
        </section>

        <section className="input-section" aria-labelledby="input-profile-heading" data-testid="input-execution-profile">
          <div className="section-title">
            <span id="input-profile-heading">授权与执行剖面</span>
          </div>
          <p className="input-note">
            执行授权：{grantStatus ? GRANT_LABELS[grantStatus] : "未读取到执行授权状态（以页面顶部提示为准）"}
            {grantErrorCategory ? ` · 授权异常：${grantErrorCategory}` : ""}
          </p>
        </section>

        {showMemory && runId && actorBotId && memoryRole && (
          <div className="input-section input-memory">
            <p className="input-note">只读视图：角色记忆的编辑在「执行监控」的任务控制区进行。</p>
            <TaskRoleMemoryPanel
              runId={runId}
              taskCode={task.code}
              role={memoryRole}
              actorBotId={actorBotId}
              isLeader={false}
            />
          </div>
        )}
      </div>
    </section>
  );
}

export default InputConstraintsPanel;