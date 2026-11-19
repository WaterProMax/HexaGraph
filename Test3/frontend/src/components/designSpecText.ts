export const RUNTIME_BOUNDARY_HEADING = "## 本次真实运行边界";

/**
 * 去掉旧版 DeepSeek 专用入口在提交时追加的“本次真实运行边界”小节。
 *
 * 该入口已下线，但历史运行的 design_input.text 里可能仍带有这个拼接块；
 * 回填只读原文时剥离它，避免把系统追加内容误当成用户原文。
 */
export function stripRuntimeBoundary(text: string): string {
  const index = text.indexOf(RUNTIME_BOUNDARY_HEADING);
  const body = index >= 0 ? text.slice(0, index) : text;
  return body.replace(/\s+$/, "");
}