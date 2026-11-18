import { describe, expect, it } from "vitest";
import { composeDeepSeekSubmission, RUNTIME_BOUNDARY_HEADING, stripRuntimeBoundary } from "./designSpecText";

const empty = { language: "", framework: "", storage: "", deployment: "" };

describe("designSpecText", () => {
  it("appends exactly one runtime boundary block", () => {
    const text = composeDeepSeekSubmission("# 规格\n\n正文", { ...empty, language: "Python 3.11" });
    expect(text.startsWith("# 规格\n\n正文\n\n## 本次真实运行边界")).toBe(true);
    expect(text.match(/本次真实运行边界/g)).toHaveLength(1);
    expect(text).toContain("- 目标语言：Python 3.11");
    expect(text).toContain("- 部署边界：本地受限工作区");
  });

  it("does not stack boundary blocks when the previous submission is resubmitted", () => {
    const first = composeDeepSeekSubmission("# 规格\n\n正文", empty);
    const second = composeDeepSeekSubmission(first, empty);
    expect(second.match(/本次真实运行边界/g)).toHaveLength(1);
    expect(second.startsWith("# 规格\n\n正文\n\n## 本次真实运行边界")).toBe(true);
  });

  it("strips the block that was appended by an earlier submission", () => {
    expect(stripRuntimeBoundary(`# 规格\n\n正文\n\n${RUNTIME_BOUNDARY_HEADING}\n- 目标语言：略`)).toBe("# 规格\n\n正文");
  });

  it("keeps a document without the boundary heading untouched", () => {
    expect(stripRuntimeBoundary("# 规格\n\n正文\n")).toBe("# 规格\n\n正文");
  });

  it("returns only the boundary block when the source text is empty", () => {
    const text = composeDeepSeekSubmission("   ", empty);
    expect(text.startsWith(RUNTIME_BOUNDARY_HEADING)).toBe(true);
    expect(text.match(/本次真实运行边界/g)).toHaveLength(1);
  });
});
