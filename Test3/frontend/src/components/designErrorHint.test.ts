import { describe, expect, it } from "vitest";
import { designErrorHint, ERROR_CATEGORY_HINTS } from "./designErrorHint";

describe("designErrorHint", () => {
  it.each([
    ["connection", "无法连接模型服务，未完成整理", "确认运行结束后重试"],
    ["auth", "模型配置或凭据不可用", "检查 Test3/.env 中对应模型的 API Key，保存后重启后端并重新提交"],
    ["rate_limit", "模型服务繁忙或请求受限", "稍后重试"],
    ["timeout", "整理超过 10 分钟，未进入设计确认", "保留原文，再次提交"],
    ["missing_fields", "文档缺项", "修改原文"],
    ["invalid_structure", "模型输出未通过结构校验", "查看具体校验项"],
    ["environment", "本地运行环境错误，未完成整理", "检查依赖与代理设置"],
  ] as const)("maps %s to title and next step", (category, title, nextStep) => {
    const hint = designErrorHint({ errorCategory: category, missing: ["未给出并发上限"], errors: ["SPEC: 缺验收"] });
    expect(hint).toEqual(expect.objectContaining({ title, nextStep }));
    expect(ERROR_CATEGORY_HINTS[category].title).toBe(title);
  });

  it("lists missing items for missing_fields", () => {
    const hint = designErrorHint({
      errorCategory: "missing_fields",
      missing: ["未给出并发上限", "未给出开放时段"],
      errors: [],
    });
    expect(hint?.details).toEqual(["未给出并发上限", "未给出开放时段"]);
  });

  it("lists structure errors for invalid_structure", () => {
    const hint = designErrorHint({
      errorCategory: "invalid_structure",
      missing: [],
      errors: ["SPEC: 缺验收", "DESIGN: 模块来源不存在: M1/F999"],
    });
    expect(hint?.details).toEqual(["SPEC: 缺验收", "DESIGN: 模块来源不存在: M1/F999"]);
  });

  it("returns null when there is no category so generic fails are not labeled structure errors", () => {
    expect(designErrorHint({ errorCategory: undefined, errors: ["设计规格整理失败"] })).toBeNull();
  });
});
