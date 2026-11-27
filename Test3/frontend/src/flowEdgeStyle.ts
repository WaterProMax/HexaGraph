import { MarkerType, type Edge } from "@xyflow/react";

export const FLOW_EDGE_COLORS = {
  default: "#52738c",
  inactive: "#718b9f",
  connected: "#0066fa",
  dimmed: "#a9bfce",
} as const;

interface ReadableFlowEdgeOptions {
  id: string;
  source: string;
  target: string;
  type?: Edge["type"];
  inactive?: boolean;
  /** Dashed variant for derived links (e.g. task dependencies next to solid contract edges). */
  dashed?: boolean;
  focusNodeId?: string | null;
}

/** Shared, static edge treatment for the stage flow and task dependency graph. */
export function readableFlowEdge({
  id,
  source,
  target,
  type = "smoothstep",
  inactive = false,
  dashed = false,
  focusNodeId = null,
}: ReadableFlowEdgeOptions): Edge {
  const hasFocus = Boolean(focusNodeId);
  const connected = hasFocus && (source === focusNodeId || target === focusNodeId);
  const dimmed = hasFocus && !connected;
  const color = dimmed
    ? FLOW_EDGE_COLORS.dimmed
    : connected
      ? FLOW_EDGE_COLORS.connected
      : inactive
        ? FLOW_EDGE_COLORS.inactive
        : FLOW_EDGE_COLORS.default;
  const className = [
    "flow-edge-readable",
    connected && "flow-edge--connected",
    dimmed && "flow-edge--dimmed",
    inactive && "flow-edge--inactive",
    dashed && "flow-edge--dashed",
  ]
    .filter(Boolean)
    .join(" ");

  return {
    id,
    source,
    target,
    type,
    animated: false,
    className,
    style: {
      stroke: color,
      strokeWidth: connected ? 3 : inactive ? 2.25 : 2.5,
      strokeDasharray: dashed ? "5 4" : inactive ? "6 4" : undefined,
      opacity: dimmed ? 0.18 : 1,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color,
      width: connected ? 20 : 18,
      height: connected ? 20 : 18,
    },
  };
}
