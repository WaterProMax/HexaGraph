export const RUNTIME_BOUNDARY_HEADING = "## 本次真实运行边界";

const UNSPECIFIED = "未指定，请依据原文；原文也未明确时报告缺项";
const DEFAULT_DEPLOYMENT = "本地受限工作区，不假定外网、安装依赖或部署凭据";

export interface RuntimeBoundaries {
  language: string;
  framework: string;
  storage: string;
  deployment: string;
}

/**
 * 去掉上一次提交时追加的“本次真实运行边界”小节。
 *
 * 导入结果里的 design_input.text 是拼接后的全文；重试时若原样再拼一次，
 * 边界小节会越叠越多（历史上出现过 4 份重复）。
 */
export function stripRuntimeBoundary(text: string): string {
  const index = text.indexOf(RUNTIME_BOUNDARY_HEADING);
  const body = index >= 0 ? text.slice(0, index) : text;
  return body.replace(/\s+$/, "");
}

export function composeDeepSeekSubmission(text: string, boundaries: RuntimeBoundaries): string {
  const base = stripRuntimeBoundary(text.trim());
  const section = [
    RUNTIME_BOUNDARY_HEADING,
    `- 目标语言：${boundaries.language.trim() || UNSPECIFIED}`,
    `- 目标框架：${boundaries.framework.trim() || UNSPECIFIED}`,
    `- 存储：${boundaries.storage.trim() || UNSPECIFIED}`,
    `- 部署边界：${boundaries.deployment.trim() || DEFAULT_DEPLOYMENT}`,
  ].join("\n");
  return base ? `${base}\n\n${section}` : section;
}
