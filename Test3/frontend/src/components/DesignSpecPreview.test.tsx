import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DesignSpecPreview from "./DesignSpecPreview";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("DesignSpecPreview persisted provenance", () => {
  it("keeps preset generation and simulated execution labels from artifacts after remount", () => {
    const artifacts = {
      design_input_status: "awaiting_confirmation",
      provenance: {
        generation: "preset",
        generation_label: "预置测试输出（scripted）",
        execution: "simulated",
        execution_label: "模拟执行（预置工具调用）",
      },
    };
    const { unmount } = render(<DesignSpecPreview result={null} artifacts={artifacts} />);
    expect(screen.getByTestId("design-provenance").textContent).toContain("预置测试输出");
    expect(screen.getByTestId("design-provenance").textContent).toContain("模拟执行");
    unmount();
    render(<DesignSpecPreview result={null} artifacts={artifacts} />);
    expect(screen.getByTestId("design-provenance").textContent).toMatch(/预置测试输出/);
    expect(screen.getByTestId("design-provenance").textContent).toMatch(/模拟执行/);
  });
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

describe("DesignSpecPreview error taxonomy", () => {
  it.each([
    ["connection", "无法连接模型服务，未完成整理", "确认运行结束后重试"],
    ["auth", "模型配置或凭据不可用", "检查 Test3/.env 中对应模型的 API Key，保存后重启后端并重新提交"],
    ["rate_limit", "模型服务繁忙或请求受限", "稍后重试"],
    ["timeout", "整理超过 10 分钟，未进入设计确认", "保留原文，再次提交"],
    ["missing_fields", "文档缺项", "修改原文"],
    ["invalid_structure", "模型输出未通过结构校验", "查看具体校验项"],
  ] as const)("shows lasting %s title and next step, not a lumped structure failure", (category, title, nextStep) => {
    render(
      <DesignSpecPreview
        result={null}
        artifacts={{
          design_input_status: category === "missing_fields" || category === "invalid_structure" ? "needs_input" : "failed",
          design_input_error_category: category,
          design_input_missing: category === "missing_fields" ? ["未给出并发上限"] : [],
          design_input_errors: category === "invalid_structure" ? ["DESIGN: 模块来源不存在: M1/F999"] : ["整理失败"],
          design_input: { source: { kind: "text" }, chars: 10, sha256: "abc" },
        }}
      />,
    );
    const hint = screen.getByTestId("design-error-hint");
    expect(hint.textContent).toContain(title);
    expect(hint.textContent).toContain(nextStep);
    expect(hint.textContent).not.toContain("结构检查未通过");
    const statusBanner = screen.getByTestId("design-import-status").textContent || "";
    expect(statusBanner).toContain("未进入");
    if (category === "missing_fields") {
      expect(hint.textContent).toContain("未给出并发上限");
      expect(statusBanner).toContain("缺少必要内容");
    }
    if (category === "invalid_structure") {
      expect(hint.textContent).toContain("模块来源不存在");
      expect(statusBanner).not.toContain("缺少必要内容");
    }
    if (category === "timeout" || category === "connection" || category === "auth" || category === "rate_limit") {
      expect(statusBanner).not.toContain("整理完成");
    }
  });

  it("does not keep an in-flight importing result over refreshed needs_input artifacts", () => {
    render(
      <DesignSpecPreview
        result={{ run_id: "run-missing", status: "importing", message: "正在整理" }}
        artifacts={{
          design_input_status: "needs_input",
          design_input_error_category: "missing_fields",
          design_input_missing: ["未给出并发上限"],
          design_input: { source: { kind: "text" }, chars: 10, sha256: "abc" },
        }}
      />,
    );
    expect(screen.getByTestId("design-import-status").textContent).toContain("缺少必要内容");
    expect(screen.getByTestId("design-import-status").textContent).not.toContain("正在整理");
  });

  it("reads error_category from the live result as well as artifacts", () => {
    render(
      <DesignSpecPreview
        artifacts={{}}
        result={{
          status: "failed",
          error_category: "auth",
          errors: ["模型配置或凭据不可用"],
          message: "模型配置或凭据不可用",
        }}
      />,
    );
    expect(screen.getByTestId("design-error-hint").textContent).toContain("模型配置或凭据不可用");
    expect(screen.getByTestId("design-error-hint").textContent).toContain("检查 Test3/.env 中对应模型的 API Key，保存后重启后端并重新提交");
  });
});
