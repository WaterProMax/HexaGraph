import { ApiError } from "../../api/client";

const ERROR_TEXT: Record<string, string> = {
  membership_exists: "已经是项目成员",
  membership_not_found: "该成员已不在项目里",
  leader_already_set: "项目已有 Leader",
  bot_archived: "Bot 已归档",
  bot_not_found: "找不到该 Bot",
  project_not_found: "找不到该项目",
};

/** Human-readable reason for a failed membership call. */
export function memberErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const category = err.category || "";
    return ERROR_TEXT[category] || category || `HTTP ${err.status}`;
  }
  return (err as any)?.message || "未知错误";
}
