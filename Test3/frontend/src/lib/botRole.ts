/** Chinese display names for the built-in bot role templates (see BotForm role presets). */
const ROLE_LABELS: Record<string, string> = {
  leader: "Leader",
  pm: "产品经理",
  backend: "后端工程师",
  qa: "测试运维",
  coder: "通用工程师",
};

/** Human-facing role title; unknown roles fall back to the raw template key. */
export function roleLabel(roleTemplate: string): string {
  return ROLE_LABELS[roleTemplate] ?? roleTemplate;
}
