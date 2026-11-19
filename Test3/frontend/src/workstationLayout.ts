import { useCallback, useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

/** Own key. Never reuse the static classroom key `hexagraph.static-classroom-demo.v1`. */
export const LAYOUT_STORAGE_KEY = "hexagraph.workstation.layout.v1";

export const LEFT_DEFAULT = 320;
export const LEFT_MIN = 280;
export const LEFT_MAX = 560;
/** The canvas never gets narrower than this while the info column is docked. */
export const CANVAS_MIN = 480;
export const SPLITTER_WIDTH = 8;
export const KEY_STEP = 16;
export const KEY_STEP_LARGE = 64;
/** Below this viewport width the global navigation folds itself. */
export const COMPACT_VIEWPORT = 1100;

export interface StoredLayout {
  width: number;
  /** User hid the docked info column. */
  collapsed: boolean;
  /** Drawer is open while there is no room to dock the info column. */
  drawerOpen: boolean;
}

export type LayoutMode = "docked" | "collapsed" | "drawer";

export const DEFAULT_LAYOUT: StoredLayout = { width: LEFT_DEFAULT, collapsed: false, drawerOpen: false };

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** Largest info-column width that still leaves CANVAS_MIN for the graph. `available` is the body width. */
export function maxLeftFor(available: number): number {
  if (!(available > 0)) return LEFT_MAX;
  return Math.min(LEFT_MAX, available - CANVAS_MIN - SPLITTER_WIDTH);
}

export function resolveLayout(
  available: number,
  stored: StoredLayout,
): { mode: LayoutMode; width: number; leftVisible: boolean } {
  const max = maxLeftFor(available);
  // available === 0 means "not measured yet" (first paint, jsdom): behave like a roomy desktop.
  if (max < LEFT_MIN) {
    return { mode: "drawer", width: LEFT_DEFAULT, leftVisible: stored.drawerOpen };
  }
  const width = clamp(Math.round(stored.width), LEFT_MIN, max);
  if (stored.collapsed) return { mode: "collapsed", width, leftVisible: false };
  return { mode: "docked", width, leftVisible: true };
}

function isStored(value: unknown): value is Partial<StoredLayout> {
  return Boolean(value) && typeof value === "object";
}

export function loadLayout(storage?: Pick<Storage, "getItem"> | null): StoredLayout {
  try {
    const raw = storage?.getItem(LAYOUT_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_LAYOUT };
    const parsed: unknown = JSON.parse(raw);
    if (!isStored(parsed)) return { ...DEFAULT_LAYOUT };
    const width = typeof parsed.width === "number" && Number.isFinite(parsed.width) ? parsed.width : LEFT_DEFAULT;
    return {
      width: clamp(Math.round(width), LEFT_MIN, LEFT_MAX),
      collapsed: parsed.collapsed === true,
      drawerOpen: parsed.drawerOpen === true,
    };
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

export function saveLayout(storage: Pick<Storage, "setItem"> | null | undefined, layout: StoredLayout) {
  try {
    storage?.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Storage may be full or blocked; the layout simply is not remembered.
  }
}

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export interface WorkstationLayout {
  bodyRef: RefObject<HTMLDivElement>;
  leftRef: RefObject<HTMLElement>;
  mode: LayoutMode;
  width: number;
  leftVisible: boolean;
  dragging: boolean;
  bodyClassName: string;
  bodyStyle: CSSProperties;
  atDefault: boolean;
  setDragging: (dragging: boolean) => void;
  setWidth: (width: number) => void;
  nudge: (delta: number) => void;
  toggleLeft: () => void;
  closeDrawer: () => void;
  reset: () => void;
}

/**
 * Drag-resizable info column. Width and collapsed/drawer state are persisted; the effective
 * width is always re-clamped against the real container so the canvas keeps CANVAS_MIN.
 */
export function useWorkstationLayout(): WorkstationLayout {
  const bodyRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLElement>(null);
  const [stored, setStored] = useState<StoredLayout>(() => loadLayout(browserStorage()));
  const [available, setAvailable] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => setAvailable(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    saveLayout(browserStorage(), stored);
  }, [stored]);

  const resolved = resolveLayout(available, stored);

  const setWidth = useCallback(
    (width: number) => {
      const max = Math.max(LEFT_MIN, maxLeftFor(available));
      setStored((current) => ({ ...current, width: clamp(Math.round(width), LEFT_MIN, max) }));
    },
    [available],
  );

  const nudge = useCallback(
    (delta: number) => {
      const max = Math.max(LEFT_MIN, maxLeftFor(available));
      setStored((current) => {
        const base = clamp(current.width, LEFT_MIN, max);
        return { ...current, width: clamp(base + delta, LEFT_MIN, max) };
      });
    },
    [available],
  );

  const toggleLeft = useCallback(() => {
    setStored((current) => {
      const drawer = maxLeftFor(available) < LEFT_MIN;
      return drawer ? { ...current, drawerOpen: !current.drawerOpen } : { ...current, collapsed: !current.collapsed };
    });
  }, [available]);

  const closeDrawer = useCallback(() => setStored((current) => ({ ...current, drawerOpen: false })), []);
  const reset = useCallback(() => setStored({ ...DEFAULT_LAYOUT }), []);

  const drawerOpen = resolved.mode === "drawer" && resolved.leftVisible;
  useEffect(() => {
    if (!drawerOpen) return;
    leftRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen, closeDrawer]);

  const bodyClassName = [
    "ws-body",
    `ws-mode-${resolved.mode}`,
    resolved.leftVisible ? "" : "left-hidden",
    dragging ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return {
    bodyRef,
    leftRef,
    mode: resolved.mode,
    width: resolved.width,
    leftVisible: resolved.leftVisible,
    dragging,
    bodyClassName,
    bodyStyle: { ["--ws-left-w" as string]: `${resolved.width}px` },
    atDefault: stored.width === LEFT_DEFAULT && !stored.collapsed && !stored.drawerOpen,
    setDragging,
    setWidth,
    nudge,
    toggleLeft,
    closeDrawer,
    reset,
  };
}
