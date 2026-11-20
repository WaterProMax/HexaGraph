import type { GrantStatus } from "../../api/types";

export type GrantStatusBannerProps = { errorCategory?: string | null; status?: GrantStatus };

type BannerCopy = { tone: "warn" | "error" | "ok"; title: string; detail: string };

function copyFor(errorCategory?: string | null, status?: GrantStatus): BannerCopy | null {
  switch (errorCategory) {
    case "baseline_stale":
      return {
        tone: "error",
        title: "执行基线已变化（baseline_stale）",
        detail: "批准过的基线哈希与当前运行不一致，请重新审批后再调度。",
      };
    case "grant_required":
      return {
        tone: "warn",
        title: "缺少执行授权（grant_required）",
        detail: "该运行是 granted_v1，但还没有人工批准的执行授权。",
      };
    case "scope_mismatch":
      return { tone: "warn", title: "超出授权范围（scope_mismatch）", detail: "请求的任务不在已批准范围内。" };
    case "empty_request":
      return { tone: "warn", title: "没有可调度的任务（empty_request）", detail: "已批准范围内没有待执行任务。" };
    case "grant_revoked":
      return { tone: "error", title: "执行授权已撤销（grant_revoked）", detail: "请重新审批后再调度。" };
    case "grant_consumed":
      return { tone: "error", title: "执行授权已消耗（grant_consumed）", detail: "请重新审批后再调度。" };
    case "execution_safety_not_ready":
      return {
        tone: "warn",
        title: "执行安全闸未开启（execution_safety_not_ready）",
        detail: "前端只展示状态，不提供开闸入口。",
      };
    case "dag_blocked":
      return { tone: "warn", title: "前置任务未完成（dag_blocked）", detail: "后继任务必须等依赖成功后才能执行。" };
    default:
      break;
  }
  if (status === "stale") {
    return {
      tone: "error",
      title: "执行授权已过期（stale）",
      detail: "基线变化后授权失效，请重新审批后再调度。",
    };
  }
  if (status === "revoked" || status === "consumed") {
    return { tone: "error", title: `执行授权不可用（${status}）`, detail: "请重新审批后再调度。" };
  }
  if (status === "active") {
    return { tone: "ok", title: "执行授权有效（active）", detail: "任务可在批准范围内连续执行。" };
  }
  return null;
}

export function GrantStatusBanner({ errorCategory, status }: GrantStatusBannerProps) {
  const copy = copyFor(errorCategory, status);
  if (!copy) return null;
  return (
    <div className={`well grant-banner grant-${copy.tone}`} data-testid="grant-banner" role="status">
      <span className={`grant-dot grant-dot-${copy.tone}`} aria-hidden="true" />
      <strong>{copy.title}</strong>
      <span style={{ marginLeft: 10 }}>{copy.detail}</span>
    </div>
  );
}

export default GrantStatusBanner;