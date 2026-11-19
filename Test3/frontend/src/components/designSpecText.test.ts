import { describe, expect, it } from "vitest";
import { RUNTIME_BOUNDARY_HEADING, stripRuntimeBoundary } from "./designSpecText";

describe("designSpecText", () => {
  it("strips the block that was appended by the retired dedicated entry", () => {
    expect(stripRuntimeBoundary(`# 规格\n\n正文\n\n${RUNTIME_BOUNDARY_HEADING}\n- 目标语言：略`)).toBe("# 规格\n\n正文");
  });

  it("keeps a document without the boundary heading untouched", () => {
    expect(stripRuntimeBoundary("# 规格\n\n正文\n")).toBe("# 规格\n\n正文");
  });

  it("strips whitespace after the body", () => {
    expect(stripRuntimeBoundary("# 规格\n\n正文\n\n\n")).toBe("# 规格\n\n正文");
  });
});