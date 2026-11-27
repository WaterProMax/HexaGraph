import { useMemo, useState } from "react";
import {
  Background, BackgroundVariant, Controls, Handle, Position, ReactFlow,
  type Node, type NodeProps,
} from "@xyflow/react";
import {
  buildArchitectureGraph, type ArchitectureDesign, type ArchitectureModule, type ArchitecturePlan,
  type PlannedTask,
} from "../architectureGraph";
import {
  FLOW_MAX_ZOOM, FLOW_MIN_ZOOM, FlowAutoFit, FlowResetButton, useFlowViewportMemory, useMeasuredElement,
} from "../FlowViewport";
import { readableFlowEdge } from "../flowEdgeStyle";
import { layoutLayered, structureKey } from "../flowLayout";
import { layeredEdgeTypes } from "../LayeredEdge";
import { useFlowNodeHover } from "../useFlowNodeHover";
import { mapTaskState } from "../workstationGraph";

type TaskMeta = { state?: string; intraDeps: string[] };

type ModuleNode = Node<{
  module: ArchitectureModule;
  taskMeta: Record<string, TaskMeta>;
  onSelectTask: (code: string) => void;
}, "architectureModule">;

/** Uniform card size keeps the layered layout intact; rows are clamped and overflow goes to detail. */
const ARCH_NODE_WIDTH = 252;
const ARCH_HEAD_HEIGHT = 76;
const ARCH_ROW_HEIGHT = 25;
const ARCH_ROWS_MAX = 8;
/** Architecture cards are large; allow the auto-fit to go below the normal 0.6 floor. */
const ARCH_READABLE_ZOOM = 0.42;

function dotClass(state: string | undefined): string {
  const mapped = mapTaskState(state ?? "pending");
  if (mapped === "completed" || mapped === "in_progress" || mapped === "awaiting" || mapped === "error") {
    return mapped;
  }
  return "pending";
}

function taskRowTitle(task: PlannedTask, meta: TaskMeta | undefined): string {
  const bits = [task.title || task.code];
  if (meta?.intraDeps.length) bits.push(`依赖 ${meta.intraDeps.join("、")}`);
  return bits.join(" · ");
}

function ArchitectureNode({ data, selected }: NodeProps<ModuleNode>) {
  const { module, taskMeta, onSelectTask } = data;
  const shown = module.tasks.slice(0, ARCH_ROWS_MAX);
  const hidden = module.tasks.length - shown.length;
  return (
    <div
      className={`flow-node arch-node${selected ? " selected" : ""}`}
      title={module.name}
      aria-label={`${module.code} ${module.name}，${module.tasks.length} 项任务`}
    >
      {/* 连接点放节点内：ReactFlow 按 DOM 实测位置布线；用节点级 handles 属性会在首帧用错坐标（边先直后曲）。 */}
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="head">
        <span className="code">{module.code}</span>
        <span className="state">{module.tasks.length} 项任务</span>
      </div>
      <div className="title" title={module.name}>{module.name}</div>
      <div className="sub" title={module.responsibility}>{module.responsibility}</div>
      <ul className="arch-tasks">
        {module.tasks.length === 0 && <li className="arch-task-more">暂无分配任务</li>}
        {shown.map((task) => {
          const meta = taskMeta[task.code];
          return (
            <li key={task.code}>
              <button
                type="button"
                className="arch-task"
                title={taskRowTitle(task, meta)}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectTask(task.code);
                }}
              >
                <span className={`dot ${dotClass(meta?.state)}`} aria-hidden="true" />
                <span className="mono">{task.code}</span>
                <span className="arch-task-title">{task.title}</span>
                {!!meta?.intraDeps.length && (
                  <span className="arch-task-deps mono" title={`依赖 ${meta.intraDeps.join("、")}`}>
                    ←{meta.intraDeps.join("、")}
                  </span>
                )}
              </button>
            </li>
          );
        })}
        {hidden > 0 && <li className="arch-task-more">还有 {hidden} 项任务，点选模块查看</li>}
      </ul>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { architectureModule: ArchitectureNode };

export default function ArchitecturePreview({ design, plan, runtimeTasks, loading, failed, onSelectTask }: {
  design?: ArchitectureDesign;
  plan?: ArchitecturePlan;
  /** Runtime task list (states) once the run is scheduled; empty before PLAN confirmation. */
  runtimeTasks?: any[];
  loading?: boolean;
  failed?: boolean;
  onSelectTask: (code: string) => void;
}) {
  const { modules, connections, taskLinks } = useMemo(() => buildArchitectureGraph(design, plan), [design, plan]);
  const stateByCode = useMemo(
    () => new Map<string, string>((runtimeTasks ?? []).map((task: any) => [task.code, task.state])),
    [runtimeTasks],
  );
  const taskMeta = useMemo(() => {
    const taskModule = new Map<string, string>();
    for (const module of modules) for (const task of module.tasks) taskModule.set(task.code, module.code);
    const meta: Record<string, TaskMeta> = {};
    for (const module of modules) {
      for (const task of module.tasks) {
        meta[task.code] = {
          state: stateByCode.get(task.code),
          intraDeps: (task.depends_on ?? []).filter((dep) => taskModule.get(dep) === module.code),
        };
      }
    }
    return meta;
  }, [modules, stateByCode]);

  const ids = modules.map((module) => module.code);
  const layoutInputs = [...connections, ...taskLinks].map(({ id, source, target }) => ({ id, source, target }));

  const maxTaskRows = modules.reduce((max, module) => Math.max(max, module.tasks.length), 0);
  const rowsInNode = maxTaskRows === 0
    ? 1
    : Math.min(maxTaskRows, ARCH_ROWS_MAX) + (maxTaskRows > ARCH_ROWS_MAX ? 1 : 0);
  const nodeHeight = ARCH_HEAD_HEIGHT + rowsInNode * ARCH_ROW_HEIGHT;

  const structure = `${structureKey(ids, layoutInputs)}|h${nodeHeight}`;
  const layered = useMemo(
    () => layoutLayered(ids, layoutInputs, {
      nodeWidth: ARCH_NODE_WIDTH,
      nodeHeight,
      parallelEdges: true,
      // 架构图边多，加大列距与行距，避免平行边和标签挤在一起。
      rankGap: 150,
      nodeGap: 72,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [structure],
  );
  // 默认只展示整张架构图；点选模块后弹出悬浮详情卡，可关闭回到纯图。
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const selected = selectedCode ? modules.find((module) => module.code === selectedCode) ?? null : null;
  const { hoveredNodeId, hoverNode, leaveNode } = useFlowNodeHover();
  const viewport = useFlowViewportMemory();
  const box = useMeasuredElement();

  if (modules.length === 0) {
    return (
      <div className={`graph-empty${failed ? " tone-error" : ""}`} role="status" data-testid="architecture-empty">
        <strong>{failed ? "架构加载失败" : loading ? "正在读取架构" : "暂无架构模块"}</strong>
        {failed && <span>请刷新工作台后重试。</span>}
        {!loading && !failed && <span>设计规格生成后，模块和依赖会显示在这里。</span>}
      </div>
    );
  }

  const focusNodeId = hoveredNodeId || selectedCode;
  const nodes: ModuleNode[] = modules.map((module) => ({
    id: module.code,
    type: "architectureModule",
    position: layered.positions[module.code],
    initialWidth: layered.nodeWidth,
    initialHeight: layered.nodeHeight,
    selected: selected?.code === module.code,
    ariaLabel: `${module.code} ${module.name}，${module.tasks.length} 项任务`,
    data: { module, taskMeta, onSelectTask },
  }));
  // 任务依赖与模块契约同向时并入模块边（标签合并），只有没有模块边的方向才画虚线任务边，
  // 避免同一对模块之间叠两条线。
  const moduleEdgeByPair = new Map(connections.map((connection) => [`${connection.source}\u0000${connection.target}`, connection]));
  const taskPairsFor = (source: string, target: string) =>
    taskLinks
      .filter((link) => link.source === source && link.target === target)
      .flatMap((link) => link.pairs.map((pair) => `${pair.task}←${pair.dep}`));
  const dashedLinks = taskLinks.filter((link) => !moduleEdgeByPair.has(`${link.source}\u0000${link.target}`));

  const compactLabel = (parts: string[]) => (parts.length > 2 ? `${parts[0]} +${parts.length - 1}` : parts.join(" · "));
  // 默认只画干净直线；悬停/选中模块时，相连边才显示标签并高亮，其余淡化。
  const labelFor = (source: string, target: string, text: string) =>
    focusNodeId && (source === focusNodeId || target === focusNodeId) ? text : undefined;
  const moduleEdges = connections.map((connection) => {
    const parts = [...connection.interfaces, ...taskPairsFor(connection.source, connection.target)];
    return {
      ...readableFlowEdge({
        ...connection, type: "layered", focusNodeId,
      }),
      data: { route: layered.routes[connection.id], ortho: true },
      label: labelFor(connection.source, connection.target, compactLabel(parts)),
      ariaLabel: `${connection.source} 依赖 ${connection.target}${parts.length ? `，${parts.join("、")}` : ""}`,
    };
  });
  const taskEdges = dashedLinks.map((link) => ({
    ...readableFlowEdge({
      id: link.id, source: link.source, target: link.target, type: "layered", focusNodeId, dashed: true,
    }),
    data: { route: layered.routes[link.id], ortho: true },
    label: labelFor(
      link.source,
      link.target,
      compactLabel(link.pairs.map((pair) => `${pair.task}←${pair.dep}`)),
    ),
    ariaLabel: `任务依赖：${link.pairs.map((pair) => `${pair.task} 依赖 ${pair.dep}`).join("、")}`,
  }));
  const edges = [...moduleEdges, ...taskEdges];
  const dependencies = selected ? connections.filter((connection) => connection.source === selected.code) : [];
  const selectedLinks = selected
    ? taskLinks.filter((link) => link.source === selected.code || link.target === selected.code)
    : [];
  const moduleName = (code: string) => modules.find((module) => module.code === code)?.name ?? code;
  return (
    <section className="architecture-pane" aria-label="项目架构图" data-testid="architecture-preview">
      <header className="architecture-heading">
        <h2>项目架构图</h2>
        <span>
          {modules.length} 个模块 · {connections.length} 条依赖
          {taskLinks.length > 0 && ` · ${taskLinks.length} 条任务依赖`}
        </span>
      </header>
      <div className="architecture-canvas">
        <div className="graph-flow" ref={box.attach} data-testid="architecture-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={layeredEdgeTypes}
            minZoom={FLOW_MIN_ZOOM}
            maxZoom={FLOW_MAX_ZOOM}
            nodesDraggable={false}
            nodesConnectable={false}
            edgesFocusable={false}
            onMoveStart={viewport.onMoveStart}
            onNodesChange={(changes) => {
              for (const change of changes) {
                if (change.type === "select" && change.selected) setSelectedCode(change.id);
              }
            }}
            onNodeClick={(_, node) => setSelectedCode(node.id)}
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
              structure={structure}
              userMoved={viewport.userMoved}
              bounds={layered}
              getSize={box.getSize}
              readableZoom={ARCH_READABLE_ZOOM}
            />
            <FlowResetButton
              userMoved={viewport.userMoved}
              bounds={layered}
              getSize={box.getSize}
              readableZoom={ARCH_READABLE_ZOOM}
            />
          </ReactFlow>
        </div>
        <div className="architecture-legend" data-testid="architecture-legend">
          <span><i className="legend-line is-solid" />模块契约 / 接口 / 任务号</span>
          {dashedLinks.length > 0 && <span><i className="legend-line is-dashed" />跨模块任务依赖</span>}
          <span className="mono">调用方 → 依赖方</span>
        </div>
        {selected && (
          <aside className="architecture-detail glass-panel" aria-label="模块详情">
            <div className="architecture-detail-head">
              <span className="mono">{selected.code}</span>
              <h3>{selected.name}</h3>
              <button
                type="button"
                className="architecture-detail-close"
                aria-label="关闭模块详情"
                title="关闭模块详情"
                onClick={() => setSelectedCode(null)}
              >
                ×
              </button>
              {selected.responsibility && <p>{selected.responsibility}</p>}
            </div>
            {!!selected.sources?.length && (
              <section>
                <h4>来源需求</h4>
                <p className="mono">{selected.sources.join("、")}</p>
              </section>
            )}
            {!!dependencies.length && (
              <section>
                <h4>模块依赖</h4>
                <ul>
                  {dependencies.map(({ id, target }) => (
                    <li key={id}>
                      <button type="button" className="chip" onClick={() => setSelectedCode(target)}>
                        <span className="mono">{target}</span>
                        {modules.find((module) => module.code === target)?.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {!!selectedLinks.length && (
              <section>
                <h4>跨模块任务依赖</h4>
                <ul>
                  {selectedLinks.flatMap((link) =>
                    link.pairs.map((pair) => {
                      const outgoing = link.source === selected.code;
                      const other = outgoing ? link.target : link.source;
                      return (
                        <li key={`${link.id}-${pair.task}-${pair.dep}`}>
                          <button
                            type="button"
                            className="chip"
                            onClick={() => setSelectedCode(other)}
                            title={outgoing ? `${pair.task} 依赖 ${other} 的 ${pair.dep}` : `${pair.task} 依赖本模块的 ${pair.dep}`}
                          >
                            <span className="mono">{pair.task}←{pair.dep}</span>
                            {outgoing ? `依赖 ${moduleName(other)}` : `被 ${moduleName(other)} 依赖`}
                          </button>
                        </li>
                      );
                    }),
                  )}
                </ul>
              </section>
            )}
            {!!selected.interfaces.length && (
              <section>
                <h4>接口契约</h4>
                <ul>
                  {selected.interfaces.map((contract) => (
                    <li className="architecture-contract" key={contract.code}>
                      <strong className="mono">{contract.code}</strong>
                      <span>{contract.provider === selected.code ? "提供给" : "调用"}{" "}
                        {contract.provider === selected.code ? (contract.consumers ?? []).join("、") : contract.provider}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <section>
              <h4>拆解任务</h4>
              {selected.tasks.length ? (
                <ul>
                  {selected.tasks.map((task) => {
                    const meta = taskMeta[task.code];
                    const deps = (task.depends_on ?? []).join("、") || "无";
                    const points = task.points !== undefined ? `${task.points}pt` : null;
                    const role = task.role || null;
                    const metaText = [points, role, `依赖 ${deps}`].filter(Boolean).join(" · ");
                    return (
                      <li key={task.code}>
                        <button
                          type="button"
                          className="chip arch-task-chip"
                          onClick={() => onSelectTask(task.code)}
                          title={taskRowTitle(task, meta)}
                        >
                          <span className="arch-task-chip-head">
                            <span className={`dot ${dotClass(meta?.state)}`} aria-hidden="true" />
                            <span className="mono">{task.code}</span>
                            <span className="arch-task-chip-title">{task.title}</span>
                          </span>
                          <span className="arch-chip-meta">{metaText}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : <p>暂无分配到该模块的任务</p>}
            </section>
          </aside>
        )}
      </div>
    </section>
  );
}
