import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import { readableFlowEdge } from "../../flowEdgeStyle";
import { useFlowNodeHover } from "../../useFlowNodeHover";
import { layoutLayered, structureKey } from "../../flowLayout";
import { layeredEdgeTypes } from "../../LayeredEdge";
import {
  FLOW_MAX_ZOOM,
  FLOW_MIN_ZOOM,
  FlowAutoFit,
  FlowResetButton,
  useFlowViewportMemory,
  useMeasuredElement,
} from "../../FlowViewport";
import type { ItemStatus } from "../../workstationGraph";

/**
 * Shared task-dependency graph.
 *
 * Extracted from `pages/Workstation.tsx` so the project main path
 * (`/projects/:id` → 任务图 tab) can show the same layered DAG as the full
 * `/workstation/:id` canvas instead of a plain text list. Layout, edge style,
 * viewport fitting and node card markup are shared, not re-implemented.
 */

/** Minimal read-only task shape the graph needs. `id` defaults to `code`. */
export interface WorkstationTaskLike {
  /** Stable node id. For tasks the code is normally used as the id. */
  id?: string;
  code: string;
  title: string;
  status: ItemStatus;
  rawState?: string;
  subtitle?: string;
  kind?: "stage" | "spec" | "design" | "package" | "task" | (string & {});
  /** Only these links become edges when `edges` is not supplied. */
  dependsOn?: string[];
  /**
   * A2 read-only dispatch badge: the assignee display name, or `null` for
   * "未派发".  `undefined` means the caller has no assignment data (e.g. the
   * full Workstation canvas) and no badge is rendered at all.
   */
  assignee?: string | null;
}

export interface DependencyGraphEdge {
  id: string;
  source: string;
  target: string;
}

export interface TaskDependencyGraphProps {
  tasks: WorkstationTaskLike[];
  /**
   * Explicit edges, e.g. work-package rollup edges. When omitted the graph
   * derives one edge per `dependsOn` link whose both endpoints are listed.
   */
  edges?: DependencyGraphEdge[];
  /** Node id to highlight (for tasks, usually the task code). */
  selected?: string | null;
  /**
   * Node id used for edge focus/dimming. Defaults to `selected`; Workstation
   * passes its raw selection so the fallback node highlight never moves edges.
   */
  focusNodeId?: string | null;
  /** Receives the clicked/focused node id (task scenes: the task code). */
  onSelect?: (nodeId: string) => void;
  /** Layout affinity; "packages" keeps the wider column/card gaps. */
  kind?: "packages" | "tasks" | "modules" | "empty";
  ariaLabel?: string;
  /**
   * Empty-list copy. Defaults to a Chinese hint; pass `null` to keep an empty
   * canvas (Workstation renders its own stage-aware empty notice instead).
   */
  emptyText?: string | null;
  /** Reset the auto-fit when this identity changes (e.g. the active run id). */
  fitKey?: string;
  className?: string;
  style?: CSSProperties;
  /** Extra layer inside the canvas container, e.g. the workstation empty notice. */
  overlay?: ReactNode;
}

const STATUS_LABELS: Record<ItemStatus, string> = {
  completed: "已完成",
  in_progress: "进行中",
  awaiting: "待确认",
  pending: "待开始",
  error: "失败/需处理",
  skipped: "不适用",
};

/** Screen-reader-only description list so every dependency is reachable as text. */
const DENSE_GRAPH_TASKS = 150;
const VISUALLY_HIDDEN: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  margin: -1,
  padding: 0,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

function TwinTaskNode({ data }: { data: any }) {
  const status: ItemStatus = data.status || "pending";
  return (
    <div
      className={`flow-node ${data.selected ? "selected" : ""} ${data.kind === "package" ? "package-node" : ""}`}
      data-status={status}
      title={`${data.code} · ${data.title}（${STATUS_LABELS[status] || STATUS_LABELS.pending}）`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="head">
        <span className={`dot ${status}`} />
        <span className="code">{data.code}</span>
        <span className="state">{data.kind === "package" ? "展开 ›" : data.rawState || STATUS_LABELS[status]}</span>
      </div>
      <div className="title" title={data.title}>
        {data.title}
      </div>
      {data.subtitle && <div className="sub" title={data.subtitle}>{data.subtitle}</div>}
      {data.assignee !== undefined && data.kind !== "package" && (
        <div className="assignee" data-testid={`graph-assignee-${data.code}`} title="派发对象（项目成员，课上可见）">
          {data.assignee ? `派发：${data.assignee}` : "未派发"}
        </div>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { twinTask: TwinTaskNode };

/** Quantised so small container changes (splitter drags) do not reshuffle edge-less grids. */
function aspectBucket(w: number, h: number): number {
  if (!w || !h) return 0;
  return Math.min(3, Math.max(1, Math.round((w / h) * 2) / 2));
}

function nodeIdOf(task: WorkstationTaskLike): string {
  return task.id || task.code;
}

export function TaskDependencyGraph({
  tasks,
  edges,
  selected,
  focusNodeId,
  onSelect,
  kind,
  ariaLabel = "任务依赖图",
  emptyText = "还没有任务依赖图。生成任务计划后，节点会按依赖关系显示在这里。",
  fitKey = "",
  className,
  style,
  overlay,
}: TaskDependencyGraphProps) {
  const nodeIds = useMemo(() => tasks.map(nodeIdOf), [tasks]);
  const known = useMemo(() => new Set(nodeIds), [nodeIds]);

  const edgeSpecs = useMemo<DependencyGraphEdge[]>(() => {
    if (edges) {
      const seen = new Set<string>();
      return edges.filter((edge) => {
        if (seen.has(edge.id)) return false;
        if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) return false;
        seen.add(edge.id);
        return true;
      });
    }
    // Same id convention as buildMainGraph, so both call sites share one graph shape.
    const byId = new Map<string, DependencyGraphEdge>();
    for (const task of tasks) {
      const target = nodeIdOf(task);
      for (const dep of task.dependsOn || []) {
        if (!known.has(dep) || dep === target) continue;
        const id = `e-${dep}-${target}`;
        if (!byId.has(id)) byId.set(id, { id, source: dep, target });
      }
    }
    return [...byId.values()];
  }, [edges, known, tasks]);

  const codeById = useMemo(() => new Map(tasks.map((task) => [nodeIdOf(task), task.code])), [tasks]);
  /** Accessible dependency sentences: "T-02 依赖 T-01". */
  const edgeDescriptions = useMemo(
    () =>
      edgeSpecs.map((edge) => ({
        id: edge.id,
        text: `${codeById.get(edge.target) || edge.target} 依赖 ${codeById.get(edge.source) || edge.source}`,
      })),
    [codeById, edgeSpecs],
  );

  const graphStructure = structureKey(nodeIds, edgeSpecs);
  const [canvasAspect, setCanvasAspect] = useState(0);
  const graphBox = useMeasuredElement((w, h) => setCanvasAspect((previous) => previous || aspectBucket(w, h)));
  const viewport = useFlowViewportMemory();
  const { hoveredNodeId, hoverNode, leaveNode } = useFlowNodeHover();

  // Re-layout only when the structure (or the quantised container shape) changes, not on status polls.
  const layered = useMemo(
    () =>
      layoutLayered(nodeIds, edgeSpecs, {
        aspect: canvasAspect || undefined,
        rankGap: kind === "packages" ? 172 : undefined,
        nodeGap: kind === "packages" ? 72 : undefined,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graphStructure, canvasAspect, kind],
  );


  /**
   * When the graph cannot fit the canvas we centre on the selected task instead of the layout
   * origin: a wide layered DAG's geometric corner can be empty, which would open on blank canvas.
   */
  /** Above this size the whole graph cannot be readable at once; follow the selection instead. */
  const denseGraph = tasks.length > DENSE_GRAPH_TASKS;

  const viewportAnchor = useMemo(() => {
    const focusId = selected || nodeIds[0] || "";
    const point = layered.positions[focusId];
    if (!point) return null;
    return { x: point.x + (layered.nodeWidth || 0) / 2, y: point.y + (layered.nodeHeight || 0) / 2 };
  }, [layered, nodeIds, selected]);

  const flowNodes = useMemo<Node[]>(
    () =>
      tasks.map((task, index) => ({
        id: nodeIds[index],
        type: "twinTask",
        position: layered.positions[nodeIds[index]] || { x: 0, y: 0 },
        // Layout owns the node size; seeding it keeps nodes visible across parent
        // re-renders instead of waiting for a fresh ResizeObserver measurement.
        initialWidth: layered.nodeWidth,
        initialHeight: layered.nodeHeight,
        draggable: false,
        connectable: false,
        ariaLabel: `${task.code} ${task.title}，${STATUS_LABELS[task.status] || STATUS_LABELS.pending}`,
        data: { ...task, selected: Boolean(selected) && selected === nodeIds[index] },
      })),
    [layered, nodeIds, selected, tasks],
  );

  const edgePorts = useMemo(() => {
    const sourceOffsets = new Map<string, number>();
    const targetOffsets = new Map<string, number>();
    const assign = (end: "source" | "target") => {
      const groups = new Map<string, string[]>();
      for (const edge of edgeSpecs) {
        const node = end === "source" ? edge.source : edge.target;
        groups.set(node, [...(groups.get(node) || []), edge.id]);
      }
      const offsets = new Map<string, number>();
      for (const ids of groups.values()) {
        if (ids.length < 2) continue;
        ids.sort((left, right) => {
          const edgeLeft = edgeSpecs.find((edge) => edge.id === left)!;
          const edgeRight = edgeSpecs.find((edge) => edge.id === right)!;
          const otherLeft = end === "source" ? edgeLeft.target : edgeLeft.source;
          const otherRight = end === "source" ? edgeRight.target : edgeRight.source;
          const delta = (layered.positions[otherLeft]?.y ?? 0) - (layered.positions[otherRight]?.y ?? 0);
          return delta || left.localeCompare(right);
        });
        const spacing = Math.min(9, 56 / (ids.length - 1));
        ids.forEach((id, index) => offsets.set(id, (index - (ids.length - 1) / 2) * spacing));
      }
      return offsets;
    };
    return { sources: assign("source"), targets: assign("target") };
  }, [edgeSpecs, layered]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      edgeSpecs.map((edge) => ({
        ...readableFlowEdge({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "layered",
          focusNodeId: hoveredNodeId || (focusNodeId !== undefined ? focusNodeId : selected) || null,
        }),
        data: {
          route: layered.routes[edge.id],
          ortho: kind === "packages" || kind === "tasks",
          sourceOffset: edgePorts.sources.get(edge.id) || 0,
          targetOffset: edgePorts.targets.get(edge.id) || 0,
        },
      })),
    [edgeSpecs, edgePorts, focusNodeId, hoveredNodeId, kind, layered, selected],
  );

  const onNodesChange = (changes: NodeChange[]) => {
    // Keyboard selection (Enter on a focused node) arrives as a select change; nothing else is applied.
    for (const change of changes) {
      if (change.type === "select" && change.selected) onSelect?.(change.id);
    }
  };

  const rootClass = ["task-dependency-graph", className].filter(Boolean).join(" ");
  // `emptyText === null` keeps the bare canvas (Workstation draws its own notice over it).
  const showCanvas = tasks.length > 0 || emptyText === null;

  return (
    <div className={rootClass} data-testid="task-dependency-graph" style={style} ref={graphBox.attach}>
      {edgeDescriptions.length > 0 && (
        <ul
          className="task-dependency-descriptions"
          data-testid="task-dependency-edges"
          aria-label="任务依赖关系"
          style={VISUALLY_HIDDEN}
        >
          {edgeDescriptions.map((edge) => (
            <li key={`desc-${edge.id}`}>{edge.text}</li>
          ))}
        </ul>
      )}
      {overlay}
      {showCanvas && denseGraph && (
        <div
          className="task-dependency-hint"
          data-testid="task-dependency-hint"
          role="status"
          style={{
            position: "absolute",
            left: 12,
            bottom: 10,
            zIndex: 3,
            maxWidth: "calc(100% - 24px)",
            padding: "4px 8px",
            borderRadius: 8,
            background: "rgba(255,255,255,.86)",
            border: "1px solid rgba(82,115,140,.18)",
            color: "var(--glass-secondary, #304b60)",
            fontSize: 11.5,
            lineHeight: 1.5,
            pointerEvents: "none",
          }}
        >
          共 {tasks.length} 个任务，依赖图超出画布，已定位到当前任务；可缩放到合适比例后拖拽查看。
        </div>
      )}
      {showCanvas ? (
        <ReactFlow
          aria-label={ariaLabel}
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          edgeTypes={layeredEdgeTypes}
          defaultViewport={{ x: 24, y: 24, zoom: 1 }}
          minZoom={FLOW_MIN_ZOOM}
          maxZoom={FLOW_MAX_ZOOM}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onMoveStart={viewport.onMoveStart}
          onNodesChange={onNodesChange}
          onNodeClick={(_, node) => onSelect?.(node.id)}
          onNodeMouseEnter={(_, node) => hoverNode(node.id)}
          onNodeMouseLeave={(_, node) => leaveNode(node.id)}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={0.7} color="#e3ebf0" />
          <Controls
            position="top-right"
            showInteractive={false}
            onZoomIn={viewport.markUserMoved}
            onZoomOut={viewport.markUserMoved}
          />
          <FlowAutoFit
            structure={`${fitKey}|${graphStructure}|${canvasAspect}`}
            userMoved={viewport.userMoved}
            bounds={{ width: layered.width, height: layered.height }}
            getSize={graphBox.getSize}
            readableZoom={0.82}
            anchor={viewportAnchor}
            followAnchor={denseGraph ? String(selected || nodeIds[0] || "") : undefined}
          />
          <FlowResetButton
            userMoved={viewport.userMoved}
            bounds={{ width: layered.width, height: layered.height }}
            getSize={graphBox.getSize}
            anchor={viewportAnchor}
          />
        </ReactFlow>
      ) : (
        <div
          className="task-dependency-empty"
          data-testid="task-dependency-empty"
          role="status"
          style={{ padding: "24px 16px", textAlign: "center", color: "var(--glass-secondary, #304b60)", fontSize: 12.5, lineHeight: 1.7 }}
        >
          {emptyText}
        </div>
      )}
    </div>
  );
}

export default TaskDependencyGraph;