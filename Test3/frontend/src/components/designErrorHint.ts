export const ERROR_CATEGORY_HINTS: Record<string, { title: string; nextStep: string }> = {
  connection: { title: "无法连接模型服务，未完成整理", nextStep: "确认运行结束后重试" },
  auth: { title: "模型配置或凭据不可用", nextStep: "检查配置，不改文档" },
  rate_limit: { title: "模型服务繁忙或请求受限", nextStep: "稍后重试" },
  timeout: { title: "整理超过 10 分钟，未进入设计确认", nextStep: "保留原文，再次提交" },
  missing_fields: { title: "文档缺项", nextStep: "修改原文" },
  invalid_structure: { title: "模型输出未通过结构校验", nextStep: "查看具体校验项" },
  environment: { title: "本地运行环境错误，未完成整理", nextStep: "检查依赖与代理设置" },
};

export interface DesignErrorHint {
  title: string;
  nextStep: string;
  details: string[];
}

export function designErrorHint(input: {
  errorCategory?: string | null;
  missing?: string[];
  errors?: string[];
}): DesignErrorHint | null {
  const mapped = ERROR_CATEGORY_HINTS[input.errorCategory || ""];
  if (!mapped) return null;
  const missing = input.missing || [];
  const errors = input.errors || [];
  const details = input.errorCategory === "missing_fields" && missing.length ? missing : errors;
  return { title: mapped.title, nextStep: mapped.nextStep, details };
}
