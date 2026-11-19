import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { MenuFoldOutlined, MenuUnfoldOutlined, UndoOutlined } from "@ant-design/icons";
import { KEY_STEP, KEY_STEP_LARGE, LEFT_DEFAULT, LEFT_MAX, LEFT_MIN, type WorkstationLayout } from "../workstationLayout";

export const LEFT_PANEL_ID = "ws-left-panel";

/** Draggable, keyboard-operable divider between the info column and the canvas. */
export function WorkstationSplitter({ layout }: { layout: WorkstationLayout }) {
  const origin = useRef<{ x: number; width: number } | null>(null);

  if (layout.mode !== "docked") {
    // Drawer mode: a click-away backdrop. Collapsed mode: nothing to resize.
    if (layout.mode === "drawer" && layout.leftVisible) {
      return <div className="ws-drawer-backdrop" data-testid="ws-drawer-backdrop" aria-hidden="true" onClick={layout.closeDrawer} />;
    }
    return null;
  }

  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (!origin.current) return;
    origin.current = null;
    layout.setDragging(false);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    if (event.key === "ArrowLeft") layout.nudge(-step);
    else if (event.key === "ArrowRight") layout.nudge(step);
    else if (event.key === "Home" || event.key === "Enter") layout.reset();
    else if (event.key === "End") layout.setWidth(LEFT_MAX);
    else return;
    event.preventDefault();
  };

  return (
    <div
      className="ws-splitter"
      role="separator"
      aria-orientation="vertical"
      aria-label="调整信息栏宽度"
      aria-controls={LEFT_PANEL_ID}
      aria-valuemin={LEFT_MIN}
      aria-valuemax={LEFT_MAX}
      aria-valuenow={layout.width}
      title="拖动调整信息栏宽度；方向键微调，Home 恢复默认"
      tabIndex={0}
      data-testid="ws-splitter"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        origin.current = { x: event.clientX, width: layout.width };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        layout.setDragging(true);
      }}
      onPointerMove={(event) => {
        if (origin.current) layout.setWidth(origin.current.width + event.clientX - origin.current.x);
      }}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={() => {
        if (origin.current) {
          origin.current = null;
          layout.setDragging(false);
        }
      }}
      onDoubleClick={layout.reset}
      onKeyDown={onKeyDown}
    >
      <span className="ws-splitter-grip" aria-hidden="true" />
    </div>
  );
}

/** Toolbar buttons: show/hide the info column, restore the default layout, surface a hidden gate. */
export function WorkstationLayoutControls({
  layout,
  attention,
}: {
  layout: WorkstationLayout;
  /** Short text for something that needs the user while the info column is hidden (e.g. a pending gate). */
  attention?: string;
}) {
  const label = layout.leftVisible ? "收起信息栏" : "展开信息栏";
  return (
    <div className="ws-layout-controls">
      {attention && !layout.leftVisible && (
        <button type="button" className="ws-attention" onClick={layout.toggleLeft} data-testid="ws-attention">
          <span className="dot awaiting" aria-hidden="true" />
          {attention}
        </button>
      )}
      <button
        type="button"
        className="ws-icon-btn"
        aria-label={label}
        aria-expanded={layout.leftVisible}
        aria-controls={LEFT_PANEL_ID}
        title={label}
        onClick={layout.toggleLeft}
      >
        {layout.leftVisible ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
      </button>
      <button
        type="button"
        className="ws-icon-btn"
        aria-label="恢复默认布局"
        title={`恢复默认布局（信息栏 ${LEFT_DEFAULT}px）`}
        disabled={layout.atDefault}
        onClick={layout.reset}
      >
        <UndoOutlined />
      </button>
    </div>
  );
}
