import { useEffect, useRef, useState } from "react";

/** Keep hover highlighting stable when pointer events cross SVG edge boundaries. */
export function useFlowNodeHover() {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelPendingLeave = () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current);
    leaveTimer.current = null;
  };

  const hoverNode = (nodeId: string) => {
    cancelPendingLeave();
    setHoveredNodeId(nodeId);
  };

  const leaveNode = (nodeId: string) => {
    cancelPendingLeave();
    leaveTimer.current = setTimeout(() => {
      setHoveredNodeId((current) => (current === nodeId ? null : current));
      leaveTimer.current = null;
    }, 120);
  };

  useEffect(() => cancelPendingLeave, []);

  return { hoveredNodeId, hoverNode, leaveNode };
}
