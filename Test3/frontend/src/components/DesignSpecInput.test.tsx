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
});
