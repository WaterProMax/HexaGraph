import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DesignSpecInput from "./DesignSpecInput";

const api = vi.hoisted(() => ({
  createProject: vi.fn(),
  createDesignRun: vi.fn(),
  artifacts: vi.fn(),
  run: vi.fn(),
  terminate: vi.fn(),
}));

vi.mock("../api/client", () => ({ api }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

beforeEach(() => {
  api.createProject.mockReset().mockResolvedValue({ id: "proj-1" });
  api.createDesignRun.mockReset();
  api.artifacts.mockReset().mockResolvedValue({ design_input_status: "importing", design_input_step: "spec" });
  api.run.mockReset().mockResolvedValue({ id: "run-1", status: "active" });
  api.terminate.mockReset();
});

function fillAndSubmit(text = "目标：学生查看空闲座位。") {
  fireEvent.change(screen.getByLabelText("设计规格原文"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "整理并检查" }));
}

describe("DesignSpecInput import wait", () => {
  it("shows elapsed wait copy, disables resubmit, and polls while importing", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    api.createDesignRun.mockResolvedValue({ run_id: "run-1", status: "importing", project_id: "proj-1" });
    const onCreated = vi.fn();
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={onCreated} />);

    fillAndSubmit();
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ run_id: "run-1", status: "importing" })),
    );
    await waitFor(() => expect(screen.getByTestId("design-import-wait")).toBeTruthy());

    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/正在整理/);

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/3/);
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/需求规格|正在整理/);
  });

  it("jumps to the existing run_id on 409 and does not call terminate when unmounted", async () => {
    const conflict = Object.assign(new Error("该项目已有正在整理的设计规格"), {
      status: 409,
      category: "import_in_progress",
      summary: "该项目已有正在整理的设计规格",
      run_id: "run-existing",
    });
    api.createDesignRun.mockRejectedValue(conflict);
    api.artifacts.mockResolvedValue({ design_input_status: "importing", design_input_step: "design" });
    const onCreated = vi.fn();
    const { unmount } = render(
      <DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={onCreated} />,
    );

    fillAndSubmit();
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ run_id: "run-existing" })),
    );
    unmount();
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.terminate).not.toHaveBeenCalled();
  });

  it("restores elapsed wait from artifacts after remount and keeps submit disabled", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const started = new Date("2026-11-16T00:00:00.000Z");
    vi.setSystemTime(started);
    const artifacts = {
      design_input_status: "importing",
      design_input_step: "spec",
      design_input_started_at: started.toISOString(),
    };

    const { unmount } = render(
      <DesignSpecInput
        projectName="p"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        watchingImport
        importArtifacts={artifacts}
      />,
    );
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/正在整理需求规格/);
    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);

    unmount();
    vi.setSystemTime(new Date(started.getTime() + 12_000));
    render(
      <DesignSpecInput
        projectName="p"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        watchingImport
        importArtifacts={{ ...artifacts, design_input_step: "design" }}
      />,
    );
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/正在整理设计规格/);
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/12/);
    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);

    vi.setSystemTime(new Date(started.getTime() + 10 * 60 * 1000));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId("design-import-wait").textContent).toMatch(/等待已停止（未取消后端整理）/);
    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("passes error_category from artifacts into onCreated so the page can keep the hint", async () => {
    api.createDesignRun.mockResolvedValue({ run_id: "run-1", status: "importing", project_id: "proj-1" });
    api.artifacts.mockResolvedValue({
      design_input_status: "failed",
      design_input_error_category: "rate_limit",
      design_input_errors: ["模型服务繁忙或请求受限"],
      design_input_message: "模型服务繁忙或请求受限",
      design_input_missing: [],
    });
    const onCreated = vi.fn();
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={onCreated} />);
    fillAndSubmit();
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(
        expect.objectContaining({
          run_id: "run-1",
          status: "failed",
          error_category: "rate_limit",
          errors: ["模型服务繁忙或请求受限"],
          message: "模型服务繁忙或请求受限",
        }),
      ),
    );
  });
});

describe("DesignSpecInput restore and resubmit", () => {
  const restored = {
    design_input_status: "failed",
    design_input: {
      title: "自习室规格",
      text: "目标：学生查看空闲座位。",
      source: { kind: "file", name: "study.md" },
    },
  };

  it("restores title, source file name, and text from design_input after refresh", () => {
    render(
      <DesignSpecInput
        projectName="p"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        importArtifacts={restored}
      />,
    );
    expect((screen.getByLabelText("设计规格标题") as HTMLInputElement).value).toBe("自习室规格");
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe(
      "目标：学生查看空闲座位。",
    );
    expect(screen.getByText(/study\.md/)).toBeTruthy();
  });

  it("does not clobber in-progress user edits when importing artifacts refresh", () => {
    const artifacts = {
      design_input_status: "importing",
      design_input: { title: "旧标题", text: "旧原文", source: { kind: "text", name: "" } },
    };
    const { rerender } = render(
      <DesignSpecInput
        projectName="p"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        watchingImport
        importArtifacts={artifacts}
      />,
    );
    fireEvent.change(screen.getByLabelText("设计规格原文"), { target: { value: "用户正在改的原文" } });
    fireEvent.change(screen.getByLabelText("设计规格标题"), { target: { value: "用户标题" } });
    rerender(
      <DesignSpecInput
        projectName="p"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        watchingImport
        importArtifacts={{
          ...artifacts,
          design_input_step: "design",
          design_input: { title: "旧标题", text: "服务端仍是旧原文", source: { kind: "text", name: "" } },
        }}
      />,
    );
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("用户正在改的原文");
    expect((screen.getByLabelText("设计规格标题") as HTMLInputElement).value).toBe("用户标题");
  });

  it("restores the next run original text when the run id changes", () => {
    const { rerender } = render(
      <DesignSpecInput
        projectName="p"
        runId="run-a"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        importArtifacts={{
          design_input_status: "failed",
          design_input: { title: "A", text: "A原文", source: { kind: "text" } },
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("设计规格原文"), { target: { value: "改过的A" } });
    rerender(
      <DesignSpecInput
        projectName="p"
        runId="run-b"
        onProjectName={() => undefined}
        onCreated={() => undefined}
        importArtifacts={{
          design_input_status: "failed",
          design_input: { title: "B", text: "B原文", source: { kind: "text" } },
        }}
      />,
    );
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("B原文");
    expect((screen.getByLabelText("设计规格标题") as HTMLInputElement).value).toBe("B");
  });

  it.each(["failed", "needs_input", "timeout"])(
    "offers 修改原文后重新提交 after %s and starts a new run on the same project",
    async (status) => {
      api.createDesignRun.mockResolvedValue({ run_id: "run-2", status: "importing", project_id: "proj-1" });
      const onCreated = vi.fn();
      render(
        <DesignSpecInput
          projectName="p"
          projectId="proj-1"
          onProjectName={() => undefined}
          onCreated={onCreated}
          importArtifacts={{
            design_input_status: status,
            design_input: restored.design_input,
          }}
        />,
      );
      const button = screen.getByRole("button", { name: "修改原文后重新提交" });
      expect((button as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(button);
      await waitFor(() => expect(api.createDesignRun).toHaveBeenCalled());
      expect(api.createProject).not.toHaveBeenCalled();
      expect(api.createDesignRun.mock.calls[0][0]).toBe("proj-1");
      expect(api.createDesignRun.mock.calls[0][1]).toBe("目标：学生查看空闲座位。");
      await waitFor(() =>
        expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ run_id: "run-2" })),
      );
    },
  );

  it("reuses the session project on organize so same-project 409 can fire", async () => {
    const conflict = Object.assign(new Error("该项目已有正在整理的设计规格"), {
      status: 409,
      category: "import_in_progress",
      summary: "该项目已有正在整理的设计规格",
      run_id: "run-existing",
    });
    api.createDesignRun.mockRejectedValue(conflict);
    const onCreated = vi.fn();
    render(
      <DesignSpecInput
        projectName="p"
        projectId="proj-keep"
        onProjectName={() => undefined}
        onCreated={onCreated}
      />,
    );
    fillAndSubmit();
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ run_id: "run-existing" })),
    );
    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.createDesignRun.mock.calls[0][0]).toBe("proj-keep");
  });

  it("still creates a project on the first organize when no project id exists", async () => {
    api.createDesignRun.mockResolvedValue({ run_id: "run-1", status: "importing", project_id: "proj-1" });
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fillAndSubmit();
    await waitFor(() => expect(api.createProject).toHaveBeenCalledWith("p"));
    await waitFor(() => expect(api.createDesignRun).toHaveBeenCalled());
  });
});

describe("DesignSpecInput offline demo hint", () => {
  it("points at self-study-room.md and does not claim club-signup generated seat tasks", () => {
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    const hint = screen.getByTestId("design-demo-hint").textContent || "";
    expect(hint).toMatch(/self-study-room\.md/);
    expect(hint).toMatch(/预置/);
    expect(hint).toMatch(/club-signup\.md/);
    expect(hint).not.toMatch(/社团文档生成座位/);
  });
});
