import { useCallback, useEffect, useRef, type MutableRefObject } from "react";
import { useReactFlow } from "@xyflow/react";

export const FLOW_MIN_ZOOM = 0.3;
export const FLOW_MAX_ZOOM = 1.6;
/** Auto/reset fit never zooms out past this; a graph too large to fit is centred on its anchor node. */
export const FLOW_READABLE_ZOOM = 0.6;
const FIT_PADDING = 32;

export interface Size {
  w: number;
  h: number;
}

export interface FlowBounds {
  width: number;
  height: number;
  /** Top-left of the layout in graph coordinates; defaults to (0, 0). */
  minX?: number;
  minY?: number;
}

export interface ViewportAnchor {
  x: number;
  y: number;
}

export interface ViewportTarget {
  x: number;
  y: number;
  zoom: number;
}

/**
 * Viewport for "show the graph": fit it when that stays readable, otherwise keep text readable
 * and centre on ``anchor`` (the current task) so a graph that cannot fit still opens on something
 * meaningful. ``readableZoom`` is the floor; views with large nodes may lower it.
 *
 * A large layered DAG spreads over tens of thousands of pixels and its geometric top-left corner
 * can contain no node at all, so "anchor at the origin" would open on empty canvas; hence the
 * explicit ``anchor`` when the whole graph cannot be shown.
 */
export function computeFitViewport(
  bounds: FlowBounds,
  size: Size,
  padding = FIT_PADDING,
  readableZoom: number = FLOW_READABLE_ZOOM,
  anchor: ViewportAnchor | null = null,
): ViewportTarget {
  const availW = Math.max(1, size.w - padding * 2);
  const availH = Math.max(1, size.h - padding * 2);
  const minX = bounds.minX ?? 0;
  const minY = bounds.minY ?? 0;
  const fit = Math.min(availW / Math.max(1, bounds.width), availH / Math.max(1, bounds.height));
  if (fit >= readableZoom) {
    const zoom = Math.min(fit, 1);
    return {
      zoom,
      x: (size.w - bounds.width * zoom) / 2 - minX * zoom,
      y: (size.h - bounds.height * zoom) / 2 - minY * zoom,
    };
  }
  const zoom = readableZoom;
  if (anchor && Number.isFinite(anchor.x) && Number.isFinite(anchor.y)) {
    return { zoom, x: size.w / 2 - anchor.x * zoom, y: size.h / 2 - anchor.y * zoom };
  }
  const scaledH = bounds.height * zoom;
  return { zoom, x: padding - minX * zoom, y: (scaledH <= availH ? (size.h - scaledH) / 2 : padding) - minY * zoom };
}

/** Bounding box of absolutely positioned fixed-size nodes. */
export function nodesBounds(positions: { x: number; y: number }[], nodeWidth: number, nodeHeight: number): FlowBounds {
  if (positions.length === 0) return { width: 0, height: 0 };
  const minX = Math.min(...positions.map((p) => p.x));
  const minY = Math.min(...positions.map((p) => p.y));
  const maxX = Math.max(...positions.map((p) => p.x + nodeWidth));
  const maxY = Math.max(...positions.map((p) => p.y + nodeHeight));
  return { width: maxX - Math.min(0, minX), height: maxY - Math.min(0, minY) };
}

/** Callback ref that tracks an element's size in a ref (no re-render per pixel). */
export function useMeasuredElement(onChange?: (w: number, h: number) => void) {
  const size = useRef<Size>({ w: 0, h: 0 });
  const observer = useRef<ResizeObserver | null>(null);
  const notify = useRef(onChange);
  notify.current = onChange;
  const attach = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      const h = Math.round(entry.contentRect.height);
      size.current = { w, h };
      notify.current?.(w, h);
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  const getSize = useCallback(() => size.current, []);
  return { attach, getSize };
}

/**
 * Tracks whether the user has taken over the viewport (pan, wheel zoom, +/- buttons).
 * Programmatic moves arrive with a null event and do not count.
 */
export function useFlowViewportMemory() {
  const userMoved = useRef(false);
  const onMoveStart = useCallback((event: unknown) => {
    if (event) userMoved.current = true;
  }, []);
  const markUserMoved = useCallback(() => {
    userMoved.current = true;
  }, []);
  return { userMoved, onMoveStart, markUserMoved };
}

interface FitSource {
  bounds: FlowBounds;
  getSize: () => Size;
  readableZoom?: number;
  /** Graph-space point to centre on when the whole graph cannot be shown. */
  anchor?: ViewportAnchor | null;
}

function useFitNow(source: FitSource) {
  const { setViewport } = useReactFlow();
  const latest = useRef(source);
  latest.current = source;
  /** Returns false while the container is not measured yet. */
  return useCallback(() => {
    const { bounds, getSize, readableZoom = FLOW_READABLE_ZOOM, anchor = null } = latest.current;
    const size = getSize();
    if (!size.w || !size.h) return false;
    if (bounds.width > 0 && bounds.height > 0) {
      void setViewport(computeFitViewport(bounds, size, FIT_PADDING, readableZoom, anchor), { duration: 200 });
    }
    return true;
  }, [setViewport]);
}

/**
 * Fits when the graph *structure* (or the run) changes, but only while the user has not panned or
 * zoomed. Container size, polling, hover, selection and splitter drags never refit.
 */
export function FlowAutoFit({
  structure,
  userMoved,
  bounds,
  getSize,
  readableZoom,
  anchor = null,
  followAnchor,
}: FitSource & {
  structure: string;
  userMoved: MutableRefObject<boolean>;
  /** Changing this key re-centres on ``anchor`` even after the user panned (dense graphs). */
  followAnchor?: string;
}) {
  const fitNow = useFitNow({ bounds, getSize, readableZoom, anchor });
  const lastStructure = useRef<string | null>(null);

  // Dense graphs cannot show every node at a readable zoom, so the viewport follows the current
  // task: selecting a row in the task tree must land on that node instead of leaving the canvas
  // parked on an unrelated region. Small graphs are unaffected (the caller passes no key).
  useEffect(() => {
    if (!followAnchor) return;
    userMoved.current = false;
    const timer = window.setTimeout(() => {
      fitNow();
    }, 60);
    return () => window.clearTimeout(timer);
  }, [followAnchor, fitNow, userMoved]);

  useEffect(() => {
    const previous = lastStructure.current;
    lastStructure.current = structure;
    if (previous !== null && previous.split("|", 1)[0] !== structure.split("|", 1)[0]) userMoved.current = false;
    if (userMoved.current) return;
    let stopped = false;
    const timers: number[] = [];
    const attempt = (n: number) => {
      if (stopped) return;
      if (!fitNow() && n < 25) timers.push(window.setTimeout(() => attempt(n + 1), 80));
    };
    timers.push(window.setTimeout(() => attempt(0), 40));
    return () => {
      stopped = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [structure, fitNow, userMoved]);

  return null;
}

/** Explicit user action: fit now and let structural changes auto-fit again. */
export function FlowResetButton({
  userMoved,
  bounds,
  getSize,
  readableZoom,
  anchor = null,
}: FitSource & { userMoved: MutableRefObject<boolean> }) {
  const fitNow = useFitNow({ bounds, getSize, readableZoom, anchor });
  return (
    <button
      type="button"
      className="graph-reset"
      onClick={() => {
        userMoved.current = false;
        fitNow();
      }}
    >
      重置视口
    </button>
  );
}
