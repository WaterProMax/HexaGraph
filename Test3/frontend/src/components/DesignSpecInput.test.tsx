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

function markdownFile(contents: string, name: string) {
  const file = new File([contents], name, { type: "text/markdown" });
  Object.defineProperty(file, "text", { value: async () => contents });
  return file;
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

describe("DesignSpecInput upload and local validation", () => {
  it("loads a markdown file name, full text, and byte count without creating a run", async () => {
    const body = "# 自习室\n目标：学生查看空闲座位。\n";
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText("读取设计规格文件"), {
      target: { files: [markdownFile(body, "self-study-room.md")] },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("读取设计规格文件").closest("label")?.textContent).toMatch(/self-study-room\.md/),
    );
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe(body);
    expect((screen.getByLabelText("设计规格标题") as HTMLInputElement).value).toBe("self-study-room");
    const encoded = new TextEncoder().encode(body).length;
    expect(document.body.textContent).toMatch(new RegExp(String(encoded)));
    expect(document.body.textContent).toMatch(/字节/);
    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.createDesignRun).not.toHaveBeenCalled();
  });

  it("rejects empty organize locally and does not create a run", async () => {
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "整理并检查" }));
    await waitFor(() => expect(screen.getByText("设计规格为空")).toBeTruthy());
    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.createDesignRun).not.toHaveBeenCalled();
  });

  it("rejects oversize organize locally and does not create a run", async () => {
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText("设计规格原文"), { target: { value: "x".repeat(100 * 1024 + 1) } });
    fireEvent.click(screen.getByRole("button", { name: "整理并检查" }));
    await waitFor(() => expect(screen.getByText("设计规格超过 100 KiB 上限")).toBeTruthy());
    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.createDesignRun).not.toHaveBeenCalled();
  });

  it("rejects an oversize markdown file and keeps the previous text", async () => {
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText("设计规格原文"), { target: { value: "保留原文" } });
    fireEvent.change(screen.getByLabelText("读取设计规格文件"), {
      target: { files: [markdownFile("y".repeat(100 * 1024 + 1), "too-big.md")] },
    });
    await waitFor(() => expect(screen.getByText(/文件超过 100 KiB 上限：too-big\.md/)).toBeTruthy());
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("保留原文");
    expect(api.createDesignRun).not.toHaveBeenCalled();
  });

  it("ignores a second organize click while the first import is in flight", async () => {
    let resolveCreate: ((value: unknown) => void) | undefined;
    api.createDesignRun.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    render(<DesignSpecInput projectName="p" onProjectName={() => undefined} onCreated={() => undefined} />);
    fillAndSubmit();
    await waitFor(() => expect(api.createDesignRun).toHaveBeenCalledTimes(1));
    expect((screen.getByRole("button", { name: /整理并检查/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /整理并检查/ }));
    expect(api.createDesignRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCreate?.({ run_id: "run-1", status: "importing", project_id: "proj-1" });
    });
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

describe("DesignSpecInput compact source panel", () => {
  const restored = {
    design_input_status: "awaiting_confirmation",
    design_input: { title: "自习室规格", text: "目标：学生查看空闲座位。", source: { kind: "text", name: "" } },
  };
  const props = { projectName: "p", onProjectName: () => undefined, onCreated: () => undefined };
  const rawDetails = () => screen.getByLabelText("设计规格原文").closest("details") as HTMLDetailsElement;

  it("starts with a short, open textarea and a collapsed hint", () => {
    render(<DesignSpecInput {...props} />);
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).rows).toBe(5);
    expect(rawDetails().open).toBe(true);
    expect((screen.getByTestId("design-demo-hint") as HTMLDetailsElement).open).toBe(false);
  });

  it("folds the original text once an import has a status but keeps it in the form for editing", () => {
    render(<DesignSpecInput {...props} importArtifacts={restored} />);
    expect(rawDetails().open).toBe(false);
    expect((screen.getByLabelText("设计规格原文") as HTMLTextAreaElement).value).toBe("目标：学生查看空闲座位。");
  });

  it("opens and focuses the text when the preview asks to edit the source", async () => {
    const { rerender } = render(<DesignSpecInput {...props} importArtifacts={restored} />);
    expect(rawDetails().open).toBe(false);
    rerender(<DesignSpecInput {...props} importArtifacts={restored} editSourceSignal={1} />);
    await waitFor(() => expect(rawDetails().open).toBe(true));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("设计规格原文")));
  });

  it("does not fold the text under a user who is typing when the status arrives", () => {
    const { rerender } = render(<DesignSpecInput {...props} />);
    const textarea = screen.getByLabelText("设计规格原文") as HTMLTextAreaElement;
    textarea.focus();
    fireEvent.change(textarea, { target: { value: "正在输入的内容" } });
    rerender(<DesignSpecInput {...props} importArtifacts={{ design_input_status: "failed" }} />);
    expect(rawDetails().open).toBe(true);
    expect(document.activeElement).toBe(textarea);
    expect(textarea.value).toBe("正在输入的内容");
  });
});
