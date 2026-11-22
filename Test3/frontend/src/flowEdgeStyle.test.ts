import { describe, expect, it } from "vitest";
import { FLOW_EDGE_COLORS, readableFlowEdge } from "./flowEdgeStyle";

describe("readableFlowEdge", () => {
  it("uses a solid blue-grey line and a matching, enlarged arrow", () => {
    const edge = readableFlowEdge({ id: "stage", source: "STAGE-0", target: "STAGE-1" });

    expect(edge.animated).toBe(false);
    expect(edge.style).toMatchObject({
      stroke: FLOW_EDGE_COLORS.default,
      strokeWidth: 2.5,
      opacity: 1,
    });
    expect(edge.style?.strokeDasharray).toBeUndefined();
    expect(edge.markerEnd).toMatchObject({
      color: FLOW_EDGE_COLORS.default,
      width: 18,
      height: 18,
    });
  });

  it("keeps inactive paths visible and reserves dashes for them", () => {
    const edge = readableFlowEdge({ id: "skip", source: "A", target: "B", inactive: true });

    expect(edge.style).toMatchObject({
      stroke: FLOW_EDGE_COLORS.inactive,
      strokeWidth: 2.25,
      strokeDasharray: "6 4",
      opacity: 1,
    });
    expect(edge.className).toContain("flow-edge--inactive");
  });

  it("draws derived links dashed without fading them to the inactive colour", () => {
    const edge = readableFlowEdge({ id: "task", source: "A", target: "B", dashed: true });

    expect(edge.style).toMatchObject({
      stroke: FLOW_EDGE_COLORS.default,
      strokeWidth: 2.5,
      strokeDasharray: "5 4",
      opacity: 1,
    });
    expect(edge.className).toContain("flow-edge--dashed");
  });

  it("highlights both predecessor and successor edges and dims unrelated edges", () => {
    const incoming = readableFlowEdge({ id: "in", source: "A", target: "B", focusNodeId: "B" });
    const outgoing = readableFlowEdge({ id: "out", source: "B", target: "C", focusNodeId: "B" });
    const unrelated = readableFlowEdge({ id: "other", source: "D", target: "E", focusNodeId: "B" });

    for (const edge of [incoming, outgoing]) {
      expect(edge.className).toContain("flow-edge--connected");
      expect(edge.style).toMatchObject({ stroke: FLOW_EDGE_COLORS.connected, strokeWidth: 3 });
      expect(edge.markerEnd).toMatchObject({ color: FLOW_EDGE_COLORS.connected, width: 20, height: 20 });
    }
    expect(unrelated.className).toContain("flow-edge--dimmed");
    expect(unrelated.style).toMatchObject({ stroke: FLOW_EDGE_COLORS.dimmed, opacity: 0.18 });
  });
});
