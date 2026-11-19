import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkstationLayoutControls, WorkstationSplitter } from "./WorkstationSplitter";
import { LAYOUT_STORAGE_KEY, LEFT_DEFAULT, LEFT_MAX, LEFT_MIN, useWorkstationLayout } from "../workstationLayout";

function Harness({ attention }: { attention?: string }) {
  const layout = useWorkstationLayout();
  return (
    <div className={layout.bodyClassName} style={layout.bodyStyle} ref={layout.bodyRef} data-testid="body">
      <aside ref={layout.leftRef} id="ws-left-panel" tabIndex={-1}>info</aside>
      <WorkstationSplitter layout={layout} />
      <section>
        <WorkstationLayoutControls layout={layout} attention={attention} />
      </section>
    </div>
  );
}

const splitter = () => screen.getByRole("separator", { name: "调整信息栏宽度" });
const now = () => Number(splitter().getAttribute("aria-valuenow"));
const stored = () => JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY) || "null");

// jsdom has no PointerEvent; a MouseEvent carrying pointerId is enough for the splitter.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
  }
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("PointerEvent", TestPointerEvent);
});
afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
  window.localStorage.clear();
});

describe("workstation splitter", () => {
  it("starts at 320px and exposes its range to assistive tech", () => {
    render(<Harness />);
    expect(now()).toBe(LEFT_DEFAULT);
    expect(splitter().getAttribute("aria-valuemin")).toBe(String(LEFT_MIN));
    expect(splitter().getAttribute("aria-valuemax")).toBe(String(LEFT_MAX));
    expect(splitter().tabIndex).toBe(0);
    expect(screen.getByTestId("body").style.getPropertyValue("--ws-left-w")).toBe("320px");
  });

  it("resizes with the arrow keys (Shift = larger step), clamps to 280–560, Home restores the default", () => {
    render(<Harness />);
    fireEvent.keyDown(splitter(), { key: "ArrowRight" });
    expect(now()).toBe(336);
    fireEvent.keyDown(splitter(), { key: "ArrowLeft", shiftKey: true });
    expect(now()).toBe(LEFT_MIN); // 336 - 64 = 272, clamped
    for (let i = 0; i < 30; i += 1) fireEvent.keyDown(splitter(), { key: "ArrowLeft", shiftKey: true });
    expect(now()).toBe(LEFT_MIN);
    for (let i = 0; i < 30; i += 1) fireEvent.keyDown(splitter(), { key: "ArrowRight", shiftKey: true });
    expect(now()).toBe(LEFT_MAX);
    fireEvent.keyDown(splitter(), { key: "Home" });
    expect(now()).toBe(LEFT_DEFAULT);
  });

  it("drags with pointer capture and persists the width under its own key", () => {
    render(<Harness />);
    const el = splitter();
    el.setPointerCapture = () => undefined;
    el.hasPointerCapture = () => true;
    el.releasePointerCapture = () => undefined;
    fireEvent.pointerDown(el, { clientX: 400, button: 0, pointerId: 1 });
    expect(screen.getByTestId("body").className).toContain("dragging");
    fireEvent.pointerMove(el, { clientX: 460, pointerId: 1 });
    expect(now()).toBe(380);
    fireEvent.pointerMove(el, { clientX: 100000, pointerId: 1 });
    expect(now()).toBe(LEFT_MAX);
    fireEvent.pointerUp(el, { clientX: 100000, pointerId: 1 });
    expect(screen.getByTestId("body").className).not.toContain("dragging");
    expect(stored()).toMatchObject({ width: LEFT_MAX, collapsed: false });
    expect(window.localStorage.getItem("hexagraph.static-classroom-demo.v1")).toBeNull();
  });

  it("restores the saved width after a reload and offers a reset", () => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({ width: 420, collapsed: false, drawerOpen: false }));
    render(<Harness />);
    expect(now()).toBe(420);
    const reset = screen.getByRole("button", { name: "恢复默认布局" }) as HTMLButtonElement;
    expect(reset.disabled).toBe(false);
    fireEvent.click(reset);
    expect(now()).toBe(LEFT_DEFAULT);
    expect(stored()).toEqual({ width: LEFT_DEFAULT, collapsed: false, drawerOpen: false });
    expect((screen.getByRole("button", { name: "恢复默认布局" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("collapses and expands the info column, remembers it, and surfaces a pending gate while hidden", () => {
    const { unmount } = render(<Harness attention="待确认：DESIGN基线确认" />);
    expect(screen.queryByTestId("ws-attention")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "收起信息栏" }));
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.getByTestId("body").className).toContain("left-hidden");
    expect(screen.getByRole("button", { name: "展开信息栏" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("ws-attention").textContent).toContain("DESIGN基线确认");
    expect(stored().collapsed).toBe(true);
    unmount();

    render(<Harness attention="待确认：DESIGN基线确认" />);
    expect(screen.getByTestId("body").className).toContain("left-hidden");
    act(() => {
      fireEvent.click(screen.getByTestId("ws-attention"));
    });
    expect(screen.getByRole("separator")).toBeTruthy();
    expect(screen.queryByTestId("ws-attention")).toBeNull();
  });
});
