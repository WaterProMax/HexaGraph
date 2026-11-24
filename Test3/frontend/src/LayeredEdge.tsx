import { BaseEdge, type EdgeProps } from "@xyflow/react";
import { routePath, routePathOrtho, type EdgeRoute } from "./flowLayout";

/** Draws the lane-based route computed by layoutLayered; falls back to a straight line without one. */
export default function LayeredEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, style, data, label }: EdgeProps) {
  const payload = data as { route?: EdgeRoute; ortho?: boolean; sourceOffset?: number; targetOffset?: number } | undefined;
  const route = payload?.route;
  const ortho = Boolean(payload?.ortho);
  const source = { x: sourceX, y: sourceY + (payload?.sourceOffset || 0) };
  // Leave a small gap before the node so the arrowhead is not painted under the card.
  const target = { x: targetX - 20, y: targetY + (payload?.targetOffset || 0) };
  const path = route
    ? ortho
      ? routePathOrtho(route, source, target)
      : routePath(route, source, target)
    : `M${sourceX},${sourceY} L${targetX},${targetY}`;
  // Labels sit on the edge's own geometry: the first lane of a forward route, the corridor of a
  // back route, or - for a plain curve - its (possibly lifted) midpoint. Parallel edges thus get
  // separate label spots instead of stacking above the source node.
  const midX = (sourceX + targetX) / 2;
  const midY = (sourceY + targetY) / 2;
  const labelX = !route ? midX : route.kind === "back" ? route.exitX : route.lanes[0]?.x0 ?? midX;
  const labelY = !route
    ? sourceY - 15
    : route.kind === "back"
      ? route.corridorY - 16
      : (route.lanes[0]?.y ?? midY + (route.lift ?? 0) * 0.75) - 12;
  return (
    <BaseEdge
      id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={16}
      label={label} labelX={labelX} labelY={labelY}
    />
  );
}

export const layeredEdgeTypes = { layered: LayeredEdge };
