import dagre from "@dagrejs/dagre";

export interface Point {
  x: number;
  y: number;
}

/** Horizontal run through a node column, at a y that dagre reserved for this edge. */
export interface Lane {
  x0: number;
  x1: number;
  y: number;
}

export type EdgeRoute =
  /** `lift` bows the last curve vertically; used to fan out parallel edges in one column gap. */
  | { kind: "forward"; lanes: Lane[]; lift?: number }
  | { kind: "back"; exitX: number; corridorY: number; entryX: number };

export interface LayeredEdgeInput {
  id: string;
  source: string;
  target: string;
}

export interface LayeredOptions {
  nodeWidth?: number;
  nodeHeight?: number;
  /** Horizontal gap between columns; derived from fan-in when omitted. */
  rankGap?: number;
  nodeGap?: number;
  /** Canvas width / height, used only to shape the grid of unconnected nodes. */
  aspect?: number;
  /** Keep several edges between the same node pair (each gets its own route) instead of dropping them. */
  parallelEdges?: boolean;
}

export interface LayeredLayout {
  positions: Record<string, Point>;
  routes: Record<string, EdgeRoute>;
  width: number;
  height: number;
  nodeWidth: number;
  nodeHeight: number;
  /** Edge ids skipped because an endpoint is unknown or the edge is a self loop. */
  dropped: string[];
}

export const LAYOUT_NODE_WIDTH = 224;
export const LAYOUT_NODE_HEIGHT = 88;
export const LAYOUT_NODE_GAP = 56;
const RANK_GAP_MIN = 96;
const RANK_GAP_MAX = 140;
const EDGE_GAP = 24;
const BACK_CORRIDOR_STEP = 14;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** Wider column gaps when many edges converge, so their curves stay apart. */
export function rankGapFor(edges: LayeredEdgeInput[]): number {
  const fanIn = new Map<string, number>();
  for (const edge of edges) fanIn.set(edge.target, (fanIn.get(edge.target) || 0) + 1);
  const maxFanIn = Math.max(1, ...fanIn.values());
  return clamp(RANK_GAP_MIN + (maxFanIn - 1) * 8, RANK_GAP_MIN, RANK_GAP_MAX);
}

/**
 * Left-to-right layered layout. Connected nodes go through dagre (ranking, crossing
 * reduction, coordinates); long edges keep dagre's reserved slots as lanes so they never
 * pass through a node. Nodes without any edge are placed on a grid instead of one tall column.
 */
export function layoutLayered(
  nodeIds: string[],
  edgeInputs: LayeredEdgeInput[],
  options: LayeredOptions = {},
): LayeredLayout {
  const W = options.nodeWidth ?? LAYOUT_NODE_WIDTH;
  const H = options.nodeHeight ?? LAYOUT_NODE_HEIGHT;
  const nodeGap = options.nodeGap ?? LAYOUT_NODE_GAP;
  const known = new Set(nodeIds);
  const dropped: string[] = [];
  const seen = new Set<string>();
  const edges: LayeredEdgeInput[] = [];
  for (const edge of edgeInputs) {
    const pair = `${edge.source}\u0000${edge.target}`;
    if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) {
      dropped.push(edge.id);
      continue;
    }
    if (!options.parallelEdges && seen.has(pair)) {
      dropped.push(edge.id);
      continue;
    }
    seen.add(pair);
    edges.push(edge);
  }
  const rankGap = options.rankGap ?? rankGapFor(edges);

  const linked = new Set<string>();
  for (const edge of edges) {
    linked.add(edge.source);
    linked.add(edge.target);
  }
  const connected = nodeIds.filter((id) => linked.has(id));
  const isolated = nodeIds.filter((id) => !linked.has(id));

  const positions: Record<string, Point> = {};
  const routes: Record<string, EdgeRoute> = {};
  let bottom = 0;
  let right = 0;

  if (connected.length > 0) {
    const g = new dagre.graphlib.Graph({ multigraph: true });
    g.setGraph({ rankdir: "LR", nodesep: nodeGap, ranksep: rankGap, edgesep: EDGE_GAP, marginx: 0, marginy: 0 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const id of connected) g.setNode(id, { width: W, height: H });
    for (const edge of edges) g.setEdge(edge.source, edge.target, {}, edge.id);
    dagre.layout(g);

    for (const id of connected) {
      const n = g.node(id);
      positions[id] = { x: n.x - W / 2, y: n.y - H / 2 };
    }
    const columns = [...new Set(connected.map((id) => g.node(id).x))].sort((a, b) => a - b);
    const columnOf = (x: number) => columns.find((c) => Math.abs(c - x) <= W / 2 + 0.5);

    bottom = Math.max(...connected.map((id) => positions[id].y + H));
    right = Math.max(...connected.map((id) => positions[id].x + W));

    // Forward edges without an intermediate column cannot borrow a dagre lane; when several
    // such edges share one column gap, fan them out vertically so they stay readable.
    const forwardPairCount = new Map<string, number>();
    for (const edge of edges) {
      const source = g.node(edge.source);
      const target = g.node(edge.target);
      if (target.x > source.x) {
        const pair = `${edge.source}\u0000${edge.target}`;
        forwardPairCount.set(pair, (forwardPairCount.get(pair) ?? 0) + 1);
      }
    }
    const forwardPairIndex = new Map<string, number>();

    let backIndex = 0;
    for (const edge of edges) {
      const source = g.node(edge.source);
      const target = g.node(edge.target);
      if (target.x > source.x) {
        const points = g.edge({ v: edge.source, w: edge.target, name: edge.id })?.points || [];
        const lanes: Lane[] = [];
        for (const p of points.slice(1, -1)) {
          const column = columnOf(p.x);
          if (column === undefined || column <= source.x || column >= target.x) continue;
          if (lanes.some((lane) => lane.x0 === column - W / 2)) continue;
          lanes.push({ x0: column - W / 2, x1: column + W / 2, y: p.y });
        }
        lanes.sort((a, b) => a.x0 - b.x0);
        let lift = 0;
        if (lanes.length === 0) {
          const pair = `${edge.source}\u0000${edge.target}`;
          const count = forwardPairCount.get(pair) ?? 1;
          if (count > 1) {
            const index = forwardPairIndex.get(pair) ?? 0;
            forwardPairIndex.set(pair, index + 1);
            lift = (index - (count - 1) / 2) * 22;
          }
        }
        routes[edge.id] = { kind: "forward", lanes, lift };
      } else {
        backIndex += 1;
        routes[edge.id] = {
          kind: "back",
          exitX: source.x + W / 2 + rankGap / 2,
          corridorY: bottom + nodeGap / 2 + (backIndex - 1) * BACK_CORRIDOR_STEP,
          entryX: target.x - W / 2 - rankGap / 2,
        };
      }
    }
    if (backIndex > 0) bottom += nodeGap / 2 + (backIndex - 1) * BACK_CORRIDOR_STEP + 8;
  }

  if (isolated.length > 0) {
    const gapX = Math.round(rankGap / 2);
    const gapY = nodeGap;
    let cols: number;
    if (connected.length > 0) {
      cols = Math.max(1, Math.floor((right + gapX) / (W + gapX)));
    } else {
      const aspect = options.aspect && Number.isFinite(options.aspect) && options.aspect > 0 ? options.aspect : 16 / 9;
      cols = Math.round(Math.sqrt((isolated.length * aspect * (H + gapY)) / (W + gapX)));
    }
    cols = clamp(cols, 1, isolated.length);
    const top = connected.length > 0 ? bottom + nodeGap * 1.5 : 0;
    isolated.forEach((id, index) => {
      positions[id] = {
        x: (index % cols) * (W + gapX),
        y: top + Math.floor(index / cols) * (H + gapY),
      };
    });
    const rows = Math.ceil(isolated.length / cols);
    bottom = top + rows * H + (rows - 1) * gapY;
    right = Math.max(right, cols * W + (cols - 1) * gapX);
  }

  let minX = 0;
  for (const route of Object.values(routes)) if (route.kind === "back") minX = Math.min(minX, route.entryX);
  if (minX < 0) {
    for (const p of Object.values(positions)) p.x -= minX;
    for (const route of Object.values(routes)) {
      if (route.kind === "back") {
        route.exitX -= minX;
        route.entryX -= minX;
      } else {
        for (const lane of route.lanes) {
          lane.x0 -= minX;
          lane.x1 -= minX;
        }
      }
    }
    right -= minX;
  }

  return { positions, routes, width: right, height: bottom, nodeWidth: W, nodeHeight: H, dropped };
}

type Segment = { type: "line" | "curve"; a: Point; b: Point; lift?: number };

function routeSegments(route: EdgeRoute, s: Point, t: Point): Segment[] {
  if (route.kind === "back") {
    const corners = [
      s,
      { x: route.exitX, y: s.y },
      { x: route.exitX, y: route.corridorY },
      { x: route.entryX, y: route.corridorY },
      { x: route.entryX, y: t.y },
      t,
    ];
    return corners.slice(1).map((b, i) => ({ type: "line" as const, a: corners[i], b }));
  }
  const segments: Segment[] = [];
  let at = s;
  for (const lane of route.lanes) {
    segments.push({ type: "curve", a: at, b: { x: lane.x0, y: lane.y } });
    segments.push({ type: "line", a: { x: lane.x0, y: lane.y }, b: { x: lane.x1, y: lane.y } });
    at = { x: lane.x1, y: lane.y };
  }
  segments.push({ type: "curve", a: at, b: t, lift: route.lift || undefined });
  return segments;
}

/** Horizontal-tangent cubic: control points stay between a.x and b.x, i.e. inside the column gap. */
function curveControls(a: Point, b: Point): [Point, Point] {
  const mid = (b.x - a.x) / 2;
  return [
    { x: a.x + mid, y: a.y },
    { x: b.x - mid, y: b.y },
  ];
}

const fmt = (n: number) => Math.round(n * 10) / 10;

/** Polyline of straight segments with slightly rounded corners (keeps the line crisp, not curvy). */
function roundedPolyline(pts: Point[], r: number): string {
  let d = `M${fmt(pts[0].x)},${fmt(pts[0].y)}`;
  for (let i = 1; i < pts.length - 1; i += 1) {
    const prev = pts[i - 1];
    const cur = pts[i];
    const next = pts[i + 1];
    const inLen = Math.hypot(cur.x - prev.x, cur.y - prev.y);
    const outLen = Math.hypot(next.x - cur.x, next.y - cur.y);
    const k = Math.min(r, inLen / 2, outLen / 2);
    const p1 = { x: cur.x - ((cur.x - prev.x) / (inLen || 1)) * k, y: cur.y - ((cur.y - prev.y) / (inLen || 1)) * k };
    const p2 = { x: cur.x + ((next.x - cur.x) / (outLen || 1)) * k, y: cur.y + ((next.y - cur.y) / (outLen || 1)) * k };
    d += ` L${fmt(p1.x)},${fmt(p1.y)} Q${fmt(cur.x)},${fmt(cur.y)} ${fmt(p2.x)},${fmt(p2.y)}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L${fmt(last.x)},${fmt(last.y)}`;
}

export function routePath(route: EdgeRoute, s: Point, t: Point): string {
  const segments = routeSegments(route, s, t);
  if (route.kind === "back") {
    return roundedPolyline([segments[0].a, ...segments.map((seg) => seg.b)], 10);
  }
  let d = `M${fmt(s.x)},${fmt(s.y)}`;
  for (const seg of segments) {
    if (seg.type === "line") {
      d += ` L${fmt(seg.b.x)},${fmt(seg.b.y)}`;
    } else {
      const [c1, c2] = curveControls(seg.a, seg.b);
      if (seg.lift) {
        c1.y += seg.lift;
        c2.y += seg.lift;
      }
      d += ` C${fmt(c1.x)},${fmt(c1.y)} ${fmt(c2.x)},${fmt(c2.y)} ${fmt(seg.b.x)},${fmt(seg.b.y)}`;
    }
  }
  return d;
}

/**
 * 架构图专用：全直线折线。水平走列间隙、垂直换道，拐角小圆角；
 * 相邻列（无车道）时就是一条水平直线，平行边在中间做垂直错位。
 */
export function routePathOrtho(route: EdgeRoute, s: Point, t: Point): string {
  if (route.kind === "back") return routePath(route, s, t);
  const pts: Point[] = [s];
  let at = s;
  for (const lane of route.lanes) {
    pts.push({ x: lane.x0, y: at.y });
    pts.push({ x: lane.x0, y: lane.y });
    pts.push({ x: lane.x1, y: lane.y });
    at = { x: lane.x1, y: lane.y };
  }
  const lift = route.lift ?? 0;
  if (lift && route.lanes.length === 0) {
    const midX = (s.x + t.x) / 2;
    pts.push({ x: midX, y: s.y });
    pts.push({ x: midX, y: s.y + lift });
    at = { x: midX, y: s.y + lift };
  }
  if (Math.abs(at.y - t.y) > 0.5) {
    // Finish the vertical move before the target, then enter it horizontally so the
    // arrowhead points at the connection dot instead of stabbing down/up into it.
    const elbowX = Math.max(at.x, Math.min(t.x, t.x - 24));
    pts.push({ x: elbowX, y: at.y });
    pts.push({ x: elbowX, y: t.y });
  }
  pts.push(t);
  const clean = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
  return roundedPolyline(clean, 8);
}

/** Points along the drawn route, for geometry checks. */
export function sampleRoute(route: EdgeRoute, s: Point, t: Point, steps = 24): Point[] {
  const out: Point[] = [];
  for (const seg of routeSegments(route, s, t)) {
    for (let i = 0; i <= steps; i += 1) {
      const u = i / steps;
      if (seg.type === "line") {
        out.push({ x: seg.a.x + (seg.b.x - seg.a.x) * u, y: seg.a.y + (seg.b.y - seg.a.y) * u });
      } else {
        const [c1, c2] = curveControls(seg.a, seg.b);
        if (seg.lift) {
          c1.y += seg.lift;
          c2.y += seg.lift;
        }
        const v = 1 - u;
        out.push({
          x: v * v * v * seg.a.x + 3 * v * v * u * c1.x + 3 * v * u * u * c2.x + u * u * u * seg.b.x,
          y: v * v * v * seg.a.y + 3 * v * v * u * c1.y + 3 * v * u * u * c2.y + u * u * u * seg.b.y,
        });
      }
    }
  }
  return out;
}

/** Stable key for "did the graph structure change", ignoring status, hover and selection. */
export function structureKey(nodeIds: string[], edges: { id: string }[]): string {
  return `${[...nodeIds].sort().join(",")}|${edges.map((e) => e.id).sort().join(",")}`;
}
