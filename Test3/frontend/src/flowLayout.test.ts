import { describe, expect, it } from "vitest";
import {
  LAYOUT_NODE_HEIGHT,
  LAYOUT_NODE_WIDTH,
  layoutLayered,
  rankGapFor,
  routePath,
  routePathOrtho,
  sampleRoute,
  structureKey,
  type LayeredEdgeInput,
  type LayeredLayout,
} from "./flowLayout";

const W = LAYOUT_NODE_WIDTH;
const H = LAYOUT_NODE_HEIGHT;

function edges(pairs: [string, string][]): LayeredEdgeInput[] {
  return pairs.map(([source, target]) => ({ id: `${source}>${target}`, source, target }));
}

function rect(layout: LayeredLayout, id: string) {
  const p = layout.positions[id];
  return { left: p.x, top: p.y, right: p.x + W, bottom: p.y + H };
}

function overlaps(a: ReturnType<typeof rect>, b: ReturnType<typeof rect>) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/** No node overlaps another, and no drawn edge passes through any node other than its two ends. */
function expectClean(ids: string[], list: LayeredEdgeInput[], layout: LayeredLayout) {
  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      expect(overlaps(rect(layout, ids[i]), rect(layout, ids[j])), `${ids[i]} overlaps ${ids[j]}`).toBe(false);
    }
  }
  const tolerance = 1;
  for (const edge of list) {
    const s = layout.positions[edge.source];
    const t = layout.positions[edge.target];
    const route = layout.routes[edge.id];
    expect(route, `route for ${edge.id}`).toBeDefined();
    const points = sampleRoute(route, { x: s.x + W, y: s.y + H / 2 }, { x: t.x, y: t.y + H / 2 }, 40);
    for (const id of ids) {
      const r = rect(layout, id);
      const inside = points.some(
        (p) => p.x > r.left + tolerance && p.x < r.right - tolerance && p.y > r.top + tolerance && p.y < r.bottom - tolerance,
      );
      expect(inside, `edge ${edge.id} passes through ${id}`).toBe(false);
    }
  }
}

describe("layoutLayered", () => {
  it("lays out a 5-node fork and join left to right without overlap or crossing a node", () => {
    const ids = ["A", "B", "C", "D", "E"];
    const list = edges([["A", "B"], ["A", "C"], ["A", "D"], ["B", "E"], ["C", "E"], ["D", "E"]]);
    const layout = layoutLayered(ids, list);
    expectClean(ids, list, layout);
    expect(layout.positions.A.x).toBeLessThan(layout.positions.B.x);
    expect(layout.positions.B.x).toBe(layout.positions.C.x);
    expect(layout.positions.C.x).toBe(layout.positions.D.x);
    expect(layout.positions.E.x).toBeGreaterThan(layout.positions.D.x);
    // Ranks are separated by a real gap; nothing is wrapped into a second column of the same rank.
    expect(layout.positions.B.x - (layout.positions.A.x + W)).toBeGreaterThanOrEqual(96);
    expect(new Set(["B", "C", "D"].map((id) => layout.positions[id].y)).size).toBe(3);
  });

  it("keeps a 20-node fan-out/fan-in graph with long edges clear of every node", () => {
    const ids = Array.from({ length: 20 }, (_, i) => `T-${String(i + 1).padStart(2, "0")}`);
    const t = (n: number) => ids[n - 1];
    const list = edges([
      [t(1), t(2)], [t(1), t(3)], [t(1), t(4)], [t(1), t(5)], [t(1), t(6)],
      [t(2), t(7)], [t(3), t(7)], [t(4), t(8)], [t(5), t(9)], [t(6), t(9)],
      [t(7), t(10)], [t(8), t(10)], [t(9), t(10)],
      [t(10), t(11)], [t(10), t(12)], [t(10), t(13)], [t(10), t(14)], [t(10), t(15)],
      [t(11), t(16)], [t(12), t(16)], [t(13), t(17)], [t(14), t(18)], [t(15), t(18)],
      [t(16), t(19)], [t(17), t(19)], [t(18), t(19)],
      [t(19), t(20)],
      [t(1), t(20)], // long edge across every rank
      [t(2), t(16)], // skips ranks
    ]);
    const layout = layoutLayered(ids, list);
    expectClean(ids, list, layout);
    for (const edge of list) {
      expect(layout.positions[edge.target].x, edge.id).toBeGreaterThan(layout.positions[edge.source].x);
    }
    expect(layout.dropped).toEqual([]);
  });

  it("routes a dependency that points backwards through a corridor below every node", () => {
    const ids = ["A", "B", "C"];
    const list = edges([["A", "B"], ["B", "C"], ["C", "A"]]);
    const layout = layoutLayered(ids, list);
    const back = layout.routes["C>A"];
    expect(back.kind).toBe("back");
    expectClean(ids, list, layout);
    const bottom = Math.max(...ids.map((id) => layout.positions[id].y + H));
    if (back.kind === "back") expect(back.corridorY).toBeGreaterThan(bottom);
    expect(layout.height).toBeGreaterThan(bottom);
  });

  it("places edge-less nodes on a grid instead of one tall column", () => {
    const ids = ["M1", "M2", "M3", "M4", "M5", "M6"];
    const layout = layoutLayered(ids, [], { aspect: 2 });
    const xs = new Set(ids.map((id) => layout.positions[id].x));
    expect(xs.size).toBeGreaterThan(1);
    expectClean(ids, [], layout);
    expect(layout.width).toBeGreaterThan(W);
  });

  it("puts connected nodes first and unconnected ones below, without overlap", () => {
    const ids = ["M1", "M2", "M3", "M4"];
    const list = edges([["M1", "M3"]]);
    const layout = layoutLayered(ids, list);
    expectClean(ids, list, layout);
    const connectedBottom = Math.max(layout.positions.M1.y, layout.positions.M3.y) + H;
    expect(layout.positions.M2.y).toBeGreaterThanOrEqual(connectedBottom);
  });

  it("drops edges to unknown nodes, self loops and duplicates instead of inventing nodes", () => {
    const layout = layoutLayered(["A", "B"], [
      { id: "ok", source: "A", target: "B" },
      { id: "ghost", source: "A", target: "Z" },
      { id: "self", source: "B", target: "B" },
      { id: "dup", source: "A", target: "B" },
    ]);
    expect(layout.dropped.sort()).toEqual(["dup", "ghost", "self"]);
    expect(Object.keys(layout.routes)).toEqual(["ok"]);
  });

  it("is deterministic for the same input", () => {
    const ids = ["A", "B", "C", "D"];
    const list = edges([["A", "B"], ["A", "C"], ["B", "D"], ["C", "D"]]);
    expect(layoutLayered(ids, list)).toEqual(layoutLayered(ids, list));
  });

  it("keeps parallel edges between adjacent columns, each fanned to its own route", () => {
    const ids = ["A", "B"];
    const list = [
      { id: "contract", source: "A", target: "B" },
      { id: "task1", source: "A", target: "B" },
      { id: "task2", source: "A", target: "B" },
    ];
    const dropped = layoutLayered(ids, list);
    expect(dropped.dropped).toEqual(["task1", "task2"]);
    const layout = layoutLayered(ids, list, { parallelEdges: true });
    expect(layout.dropped).toEqual([]);
    expect(layout.routes.contract).toEqual({ kind: "forward", lanes: [], lift: -22 });
    expect(layout.routes.task1).toEqual({ kind: "forward", lanes: [], lift: 0 });
    expect(layout.routes.task2).toEqual({ kind: "forward", lanes: [], lift: 22 });
  });
});

describe("routePath", () => {
  it("starts at the source and ends at the target", () => {
    const ids = ["A", "B"];
    const list = edges([["A", "B"]]);
    const layout = layoutLayered(ids, list);
    const s = { x: layout.positions.A.x + W, y: layout.positions.A.y + H / 2 };
    const t = { x: layout.positions.B.x, y: layout.positions.B.y + H / 2 };
    const d = routePath(layout.routes["A>B"], s, t);
    expect(d.startsWith(`M${s.x},${s.y}`)).toBe(true);
    expect(d.endsWith(`${t.x},${t.y}`)).toBe(true);
  });
});

describe("routePathOrtho", () => {
  it("draws only straight segments and keeps start/end", () => {
    const ids = ["A", "B"];
    const list = edges([["A", "B"]]);
    const layout = layoutLayered(ids, list);
    const s = { x: layout.positions.A.x + W, y: layout.positions.A.y + H / 2 };
    const t = { x: layout.positions.B.x, y: layout.positions.B.y + H / 2 };
    const d = routePathOrtho(layout.routes["A>B"], s, t);
    expect(d.startsWith(`M${s.x},${s.y}`)).toBe(true);
    expect(d.endsWith(`${t.x},${t.y}`)).toBe(true);
    // 直线折线：没有三次贝塞尔曲线命令。
    expect(/[a-z]/i.test(d.replace(/[MLQ\d.,\s-]/g, ""))).toBe(false);
    expect(d.includes(" C")).toBe(false);
  });

  it("offsets parallel edges with a straight vertical step", () => {
    const ids = ["A", "B"];
    const list = [
      { id: "a", source: "A", target: "B" },
      { id: "b", source: "A", target: "B" },
    ];
    const layout = layoutLayered(ids, list, { parallelEdges: true });
    const s = { x: layout.positions.A.x + W, y: layout.positions.A.y + H / 2 };
    const t = { x: layout.positions.B.x, y: layout.positions.B.y + H / 2 };
    const d1 = routePathOrtho(layout.routes.a, s, t);
    const d2 = routePathOrtho(layout.routes.b, s, t);
    expect(d1.includes(" C")).toBe(false);
    expect(d2.includes(" C")).toBe(false);
    expect(d1).not.toBe(d2);
  });
});

describe("rankGapFor / structureKey", () => {
  it("widens the column gap with fan-in but stays within 96–140", () => {
    const small = rankGapFor(edges([["A", "B"]]));
    const big = rankGapFor(edges(Array.from({ length: 20 }, (_, i) => [`S${i}`, "T"] as [string, string])));
    expect(small).toBe(96);
    expect(big).toBeGreaterThan(small);
    expect(big).toBeLessThanOrEqual(140);
  });

  it("ignores order and status; changes when a node or an edge changes", () => {
    const a = structureKey(["B", "A"], [{ id: "e2" }, { id: "e1" }]);
    expect(structureKey(["A", "B"], [{ id: "e1" }, { id: "e2" }])).toBe(a);
    expect(structureKey(["A", "B", "C"], [{ id: "e1" }, { id: "e2" }])).not.toBe(a);
    expect(structureKey(["A", "B"], [{ id: "e1" }])).not.toBe(a);
  });
});
