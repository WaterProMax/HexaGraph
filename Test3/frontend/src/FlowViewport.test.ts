import { describe, expect, it } from "vitest";
import { FLOW_READABLE_ZOOM, computeFitViewport, nodesBounds } from "./FlowViewport";

describe("computeFitViewport", () => {
  it("centres a graph that fits and never zooms in past 1", () => {
    const v = computeFitViewport({ width: 400, height: 200 }, { w: 1000, h: 600 });
    expect(v.zoom).toBe(1);
    expect(v.x).toBe(300);
    expect(v.y).toBe(200);
  });

  it("scales down to fit while text stays readable", () => {
    const v = computeFitViewport({ width: 1400, height: 400 }, { w: 1000, h: 600 });
    expect(v.zoom).toBeGreaterThanOrEqual(FLOW_READABLE_ZOOM);
    expect(v.zoom).toBeLessThan(1);
    expect(1400 * v.zoom).toBeLessThanOrEqual(1000);
  });

  it("keeps readable zoom and anchors a very wide graph at its start", () => {
    const v = computeFitViewport({ width: 3000, height: 800 }, { w: 900, h: 600 });
    expect(v.zoom).toBe(FLOW_READABLE_ZOOM);
    expect(v.x).toBe(32);
    expect(v.y).toBeGreaterThanOrEqual(0);
  });

  it("anchors a very tall graph at the top", () => {
    const v = computeFitViewport({ width: 600, height: 4000 }, { w: 900, h: 600 });
    expect(v.zoom).toBe(FLOW_READABLE_ZOOM);
    expect(v.y).toBe(32);
  });
});

describe("nodesBounds", () => {
  it("covers fixed-size nodes and is empty without nodes", () => {
    expect(nodesBounds([], 224, 88)).toEqual({ width: 0, height: 0 });
    expect(nodesBounds([{ x: 0, y: 0 }, { x: 280, y: 100 }], 224, 88)).toEqual({ width: 504, height: 188 });
  });
});
