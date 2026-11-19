import { BaseEdge, type EdgeProps } from "@xyflow/react";
import { routePath, type EdgeRoute } from "./flowLayout";

/** Draws the lane-based route computed by layoutLayered; falls back to a straight line without one. */
export default function LayeredEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, style, data }: EdgeProps) {
  const route = (data as { route?: EdgeRoute } | undefined)?.route;
  const source = { x: sourceX, y: sourceY };
  const target = { x: targetX, y: targetY };
  const path = route
    ? routePath(route, source, target)
    : `M${sourceX},${sourceY} L${targetX},${targetY}`;
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={16} />;
}

export const layeredEdgeTypes = { layered: LayeredEdge };
