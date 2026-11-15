import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import DesignSpecPreview from "./DesignSpecPreview";

afterEach(cleanup);

describe("DesignSpecPreview persisted import status", () => {
  it.each([
    ["needs_input", "缺少必要内容，未进入 DESIGN 确认或任务分解"],
    ["needs_split", "输入需要拆分，未进入 DESIGN 确认或任务分解"],
    ["failed", "整理失败，未进入 DESIGN 确认或任务分解"],
    ["awaiting_confirmation", "整理完成，等待 DESIGN 确认；尚未进入任务分解或调度"],
    ["design_confirmed", "DESIGN 已确认，等待 PLAN 确认；尚未进入调度"],
    ["plan_confirmed", "PLAN 已确认，任务已建立；调度状态以任务列表为准"],
  ])("renders %s from refreshed artifacts", (status, message) => {
    render(
      <DesignSpecPreview
        result={null}
        artifacts={{
          design_input_status: status,
          design_input: { source: { kind: "text" }, chars: 10, sha256: "abc" },
        }}
      />,
    );
    expect(screen.getByTestId("design-import-status").textContent).toContain(message);
  });
});
