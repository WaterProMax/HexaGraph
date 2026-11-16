import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DesignSpecPreview from "./DesignSpecPreview";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("DesignSpecPreview persisted import status", () => {
  it.each([
    ["needs_input", "缺少必要内容，未进入 DESIGN 确认或任务分解"],
    ["needs_split", "输入需要拆分，未进入 DESIGN 确认或任务分解"],
    ["failed", "整理失败，未进入 DESIGN 确认或任务分解"],
    ["awaiting_confirmation", "整理完成，等待 DESIGN 确认；尚未进入任务分解或调度"],
    ["design_confirmed", "DESIGN 已确认，等待 PLAN 确认；尚未进入调度"],
    ["plan_confirmed", "PLAN 已确认，任务已建立；调度状态以任务列表为准"],
    ["importing", "正在整理"],
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

  it("shows step wait and elapsed from started_at so remount still displays the wait UI", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const started = new Date("2026-11-16T00:00:00.000Z");
    vi.setSystemTime(started);
    const artifacts = {
      design_input_status: "importing",
      design_input_step: "spec",
      design_input_started_at: started.toISOString(),
      design_input: { source: { kind: "text" }, chars: 10, sha256: "abc" },
    };
    const { unmount } = render(<DesignSpecPreview result={null} artifacts={artifacts} />);
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/正在整理需求规格/);

    unmount();
    vi.setSystemTime(new Date(started.getTime() + 8_000));
    render(
      <DesignSpecPreview
        result={null}
        artifacts={{ ...artifacts, design_input_step: "design" }}
      />,
    );
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/正在整理设计规格/);
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/8/);

    vi.setSystemTime(new Date(started.getTime() + 10 * 60 * 1000));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/等待已停止（未取消后端整理）/);
  });
});
