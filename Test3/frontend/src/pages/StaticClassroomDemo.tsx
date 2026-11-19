import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Button, Empty, Tag, Tooltip } from "antd";
import {
  ArrowRightOutlined,
  CheckOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StepForwardOutlined,
} from "@ant-design/icons";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Link } from "react-router-dom";
import TaskPlanPreview from "../components/TaskPlanPreview";
import { readableFlowEdge } from "../flowEdgeStyle";
import {
  FLOW_MAX_ZOOM,
  FLOW_MIN_ZOOM,
  FlowAutoFit,
  FlowResetButton,
  nodesBounds,
  useFlowViewportMemory,
  useMeasuredElement,
} from "../FlowViewport";
import { LEFT_PANEL_ID, WorkstationLayoutControls, WorkstationSplitter } from "../components/WorkstationSplitter";
import { useWorkstationLayout } from "../workstationLayout";
import {
  canAdvanceStaticDemo,
  createStaticDemoState,
  currentStaticGate,
  getStaticTasks,
  loadStaticDemoState,
  saveStaticDemoState,
  staticArtifactVisibility,
  staticDemoReducer,
  STATIC_DEMO_AUTOPLAY_MS,
  STATIC_GATE_TITLE,
  type StaticDemoState,
  type StaticGate,
  type StaticTaskState,
} from "../demo/staticClassroom";
import {
  STATIC_ACCEPTANCE,
  STATIC_DESIGN,
  STATIC_DISCUSSION_CONCLUSION,
  STATIC_PLAN,
  STATIC_REQUIREMENT,
  STATIC_SPEC,
  STATIC_TASK_DETAILS,
  STATIC_UTTERANCES,
} from "../demo/staticClassroomData";
import "../static-classroom.css";

const STATE_LABEL: Record<StaticTaskState, string> = {
  pending: "pending",
  ready: "ready",
  running: "running",
  done: "done",
};

const STAGE_NODES = [
  { id: "DISCUSSION", code: "STAGE-1", title: "多智能体讨论", subtitle: "10 条人工编写发言" },
  { id: "SPEC", code: "SPEC", title: "需求规格基线", subtitle: "F1–F3 · 等待人工确认" },
  { id: "DESIGN", code: "DESIGN", title: "架构与设计规格", subtitle: "M1–M4 · C1 查询契约" },
  { id: "PLAN", code: "PLAN", title: "任务分解与 DAG", subtitle: "5 项任务 · 分叉与汇合" },
  { id: "execution", code: "STAGE-4", title: "模拟执行", subtitle: "预置事件 · 未真实执行" },
  { id: "acceptance", code: "ACCEPT", title: "静态验收总结", subtitle: "预置结果 · 非执行证明" },
] as const;

function taskVisualState(state: StaticTaskState) {
  if (state === "done") return "completed";
  if (state === "running" || state === "ready") return "in_progress";
  return "pending";
}

function StaticFlowNode({ data }: { data: any }) {
  const status = data.status || "pending";
  return (
    <div className={`flow-node ${data.selected ? "selected" : ""}`} data-status={status}>
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span className={`dot ${status}`} />
        <span className="code">{data.code}</span>
        <span className="state">{data.rawState}</span>
      </div>
      <div className="title" title={data.title}>{data.title}</div>
      <div className="sub" title={data.subtitle}>{data.subtitle}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { staticDemoNode: StaticFlowNode };

function stageStatus(state: StaticDemoState, id: string): "completed" | "in_progress" | "pending" {
  const approved = state.approvedGates;
  if (id === "DISCUSSION") return approved.includes("DISCUSSION") ? "completed" : state.started ? "in_progress" : "pending";
  if (id === "SPEC" || id === "DESIGN" || id === "PLAN") {
    if (approved.includes(id)) return "completed";
    if (state.stage === id) return "in_progress";
    return "pending";
  }
  if (id === "execution") {
    if (state.stage === "acceptance") return "completed";
    return state.stage === "execution" ? "in_progress" : "pending";
  }
  return state.stage === "acceptance" ? "completed" : "pending";
}

function stageRawState(state: StaticDemoState, id: string) {
  const status = stageStatus(state, id);
  if (status === "completed") return "done";
  if (status === "in_progress") return currentStaticGate(state) && state.stage === id ? "await_gate" : "in_progress";
  return "pending";
}

function initialStorage() {
  return typeof window === "undefined" ? undefined : window.localStorage;
}

export default function StaticClassroomDemo() {
  const [state, dispatch] = useReducer(staticDemoReducer, undefined, () => loadStaticDemoState(initialStorage()));
  const [activeTab, setActiveTab] = useState("graph");
  const [selectedId, setSelectedId] = useState("DISCUSSION");
  const [playing, setPlaying] = useState(false);
  const [advanceLocked, setAdvanceLocked] = useState(false);
  const advanceLockRef = useRef(false);
  const lockTimerRef = useRef<number | null>(null);
  const layout = useWorkstationLayout();
  const viewport = useFlowViewportMemory();
  const graphBox = useMeasuredElement();
  const gate = currentStaticGate(state);
  const tasks = useMemo(() => getStaticTasks(state), [state]);
  const visibility = staticArtifactVisibility(state);

  useEffect(() => saveStaticDemoState(initialStorage(), state), [state]);

  useEffect(() => {
    if (!canAdvanceStaticDemo(state)) setPlaying(false);
    if (state.stage === "acceptance") setActiveTab("acceptance");
  }, [state]);

  useEffect(
    () => () => {
      if (lockTimerRef.current !== null) window.clearTimeout(lockTimerRef.current);
    },
    [],
  );

  const requestNext = useCallback(() => {
    if (advanceLockRef.current || !canAdvanceStaticDemo(state)) return;
    advanceLockRef.current = true;
    setAdvanceLocked(true);
    dispatch({ type: "NEXT" });
    lockTimerRef.current = window.setTimeout(() => {
      advanceLockRef.current = false;
      setAdvanceLocked(false);
    }, 320);
  }, [state]);

  useEffect(() => {
    if (!playing || !canAdvanceStaticDemo(state)) return;
    const timer = window.setTimeout(requestNext, STATIC_DEMO_AUTOPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, requestNext, state]);

  const approve = (approvedGate: StaticGate) => {
    if (gate !== approvedGate) return;
    setPlaying(false);
    dispatch({ type: "APPROVE", gate: approvedGate });
    if (approvedGate === "DISCUSSION" || approvedGate === "SPEC") setActiveTab("specs");
    if (approvedGate === "DESIGN") setActiveTab("plan");
    if (approvedGate === "PLAN") {
      setSelectedId("T-01");
      setActiveTab("graph");
    }
  };

  const reset = () => {
    setPlaying(false);
    advanceLockRef.current = false;
    setAdvanceLocked(false);
    if (lockTimerRef.current !== null) window.clearTimeout(lockTimerRef.current);
    dispatch({ type: "RESET" });
    setSelectedId("DISCUSSION");
    setActiveTab("graph");
  };

  const { flowNodes, flowEdges } = useMemo(() => {
    let nodes: Node[] = [];
    let edges: Edge[] = [];
    if (visibility.plan) {
      const positions: Record<string, { x: number; y: number }> = {
        "T-01": { x: 30, y: 160 },
        "T-02": { x: 310, y: 50 },
        "T-03": { x: 310, y: 270 },
        "T-04": { x: 590, y: 160 },
        "T-05": { x: 870, y: 160 },
      };
      nodes = tasks.map((task) => ({
        id: task.code,
        type: "staticDemoNode",
        position: positions[task.code],
        data: {
          code: task.code,
          title: task.card.title,
          subtitle: `${task.card.role} · 依赖 ${task.card.depends_on.join("、") || "无"}`,
          status: taskVisualState(task.state),
          rawState: STATE_LABEL[task.state],
          selected: selectedId === task.code,
        },
      }));
      tasks.forEach((task) => {
        task.card.depends_on.forEach((dependency: string) => {
          edges.push(
            readableFlowEdge({
              id: `${dependency}-${task.code}`,
              source: dependency,
              target: task.code,
              focusNodeId: selectedId,
            }),
          );
        });
      });
    } else {
      nodes = STAGE_NODES.map((stage, index) => ({
        id: stage.id,
        type: "staticDemoNode",
        position: { x: 30 + (index % 3) * 270, y: 70 + Math.floor(index / 3) * 230 },
        data: {
          ...stage,
          status: stageStatus(state, stage.id),
          rawState: stageRawState(state, stage.id),
          selected: selectedId === stage.id,
        },
      }));
      for (let index = 1; index < STAGE_NODES.length; index += 1) {
        const source = STAGE_NODES[index - 1].id;
        const target = STAGE_NODES[index].id;
        edges.push(readableFlowEdge({ id: `${source}-${target}`, source, target, focusNodeId: selectedId }));
      }
    }
    return { flowNodes: nodes, flowEdges: edges };
  }, [visibility.plan, tasks, state, selectedId]);

  const flowBounds = useMemo(() => nodesBounds(flowNodes.map((node) => node.position), 224, 88), [flowNodes]);

  const selectedTask = tasks.find((task) => task.code === selectedId);
  const selectedStage = STAGE_NODES.find((stage) => stage.id === selectedId) || STAGE_NODES[0];
  const selected = selectedTask ? { code: selectedTask.code, title: selectedTask.card.title } : selectedStage;
  const doneTasks = tasks.filter((task) => task.state === "done").length;
  const progress = state.stage === "acceptance" ? 100 : Math.round(((state.approvedGates.length + doneTasks) / 9) * 100);

  const tabs = [
    { key: "graph", label: "流程图" },
    { key: "discussion", label: "讨论", count: state.discussionCount },
    { key: "plan", label: "任务计划", count: visibility.plan ? STATIC_PLAN.tasks.length : undefined },
    { key: "details", label: "节点详情" },
    { key: "specs", label: "规格产物" },
    { key: "activity", label: "活动", count: state.activities.length },
    { key: "acceptance", label: "验收" },
  ];

  const selectStage = (id: string) => {
    setSelectedId(id);
    if (id === "DISCUSSION") setActiveTab("discussion");
    else if (id === "SPEC" || id === "DESIGN" || id === "PLAN") setActiveTab("specs");
    else setActiveTab("graph");
  };

  return (
    <div className="ws static-demo" data-testid="static-classroom-demo">
      <header className="topbar">
        <div className="topbar-left">
          <span className="crumb">工作台 / <strong>自习室座位查询课堂案例</strong></span>
          <span className="pill static-demo-badge">静态课堂演示 · 预置数据 · 不调用真实模型</span>
        </div>
        <div className="topbar-right static-playback" aria-label="静态演示播放控制">
          <Button
            size="small"
            icon={<StepForwardOutlined />}
            disabled={!canAdvanceStaticDemo(state) || advanceLocked}
            onClick={requestNext}
            aria-label="下一步"
          >
            下一步
          </Button>
          <Button
            size="small"
            type={playing ? "default" : "primary"}
            icon={playing ? <PauseOutlined /> : <PlayCircleOutlined />}
            disabled={!state.started || state.stage === "acceptance" || Boolean(gate)}
            onClick={() => setPlaying((value) => !value)}
            aria-label={playing ? "暂停播放" : "自动播放"}
          >
            {playing ? "暂停播放" : "自动播放"}
          </Button>
          <Button size="small" icon={<ReloadOutlined />} disabled={!state.started} onClick={reset} aria-label="重新演示">
            重新演示
          </Button>
          <Tooltip title="这是演示时间线控制，不是真实运行调度；本静态案例不支持暂停运行。">
            <Button size="small" disabled aria-label="暂停运行（静态案例不支持）">暂停运行</Button>
          </Tooltip>
        </div>
      </header>

      <div className={layout.bodyClassName} style={layout.bodyStyle} ref={layout.bodyRef}>
        <aside className="ws-left" id={LEFT_PANEL_ID} aria-label="静态课堂演示面板" ref={layout.leftRef} tabIndex={-1}>
          <section className="composer glass-panel static-requirement" aria-labelledby="static-demo-heading">
            <div className="panel-heading"><h2 id="static-demo-heading">静态课堂演示</h2></div>
            <p className="static-intro">人工编写的完整教学案例；不创建真实项目、不读取密钥、不执行开发任务。</p>
            <details className="static-requirement-text">
              <summary>查看固定需求完整原文</summary>
              <p>{STATIC_REQUIREMENT}</p>
            </details>
            {!state.started ? (
              <Button type="primary" icon={<ArrowRightOutlined />} aria-label="开始静态演示" onClick={() => dispatch({ type: "START" })}>
                开始静态演示
              </Button>
            ) : (
              <div className="static-run-meta">
                <span className="mono">{state.runId}</span>
                <span>第 {state.replay} 次播放 · 刷新后恢复当前进度</span>
              </div>
            )}
            <Link to="/workstation" className="static-exit-link">返回真实运行工作台</Link>
          </section>

          <div className="notice static-provenance" data-testid="static-demo-provenance">
            <span>静态课堂演示 · 预置数据 · 不调用真实模型</span>
          </div>

          {gate && (
            <section className="gate-card glass-panel" aria-labelledby="static-gate-heading" data-testid="static-gate">
              <div>
                <div className="gate-kicker">等待你确认 · 自动播放已暂停</div>
                <h2 className="gate-head" id="static-gate-heading"><span className="dot awaiting" />{STATIC_GATE_TITLE[gate]}</h2>
              </div>
              <p className="static-gate-copy">请先查看对应{gate === "DISCUSSION" ? "讨论与结论" : "预置产物"}，再由人工批准。</p>
              <div className="gate-actions">
                <Button type="primary" size="small" icon={<CheckOutlined />} onClick={() => approve(gate)} aria-label="批准并推进">
                  批准并推进
                </Button>
                <Tooltip title="主演示仅覆盖批准继续；静态案例不支持驳回重写。">
                  <Button size="small" danger disabled aria-label="驳回重写（静态案例不支持）">驳回重写</Button>
                </Tooltip>
              </div>
            </section>
          )}

          <section className="progress-section" aria-labelledby="static-progress-heading">
            <div className="progress-summary glass-panel">
              <div className="section-title">
                <h2 id="static-progress-heading">演示进度</h2>
                <span className="hint mono">{state.approvedGates.length}/4 关卡 · {doneTasks}/5 任务 · {progress}%</span>
              </div>
              <div className="meter brand" role="progressbar" aria-label="静态演示进度" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${progress}%` }} />
              </div>
            </div>
            <div className="phase-list">
              <section className="phase glass-panel">
                <div className="phase-head"><span className="phase-no">Phase 1</span><h3 className="phase-title">讨论与规格确认</h3></div>
                <div className="phase-items">
                  {STAGE_NODES.slice(0, 4).map((stage) => {
                    const status = stageStatus(state, stage.id);
                    return (
                      <button type="button" key={stage.id} className={`row ${selectedId === stage.id ? "active" : ""}`} data-status={status} aria-pressed={selectedId === stage.id} onClick={() => selectStage(stage.id)}>
                        <span className={`dot ${status}`} />
                        <span className="row-main"><span className="row-title"><span className="code">{stage.code}</span><span className="text">{stage.title}</span></span></span>
                      </button>
                    );
                  })}
                </div>
              </section>
              <section className="phase glass-panel">
                <div className="phase-head"><span className="phase-no">Phase 2</span><h3 className="phase-title">模拟执行与验收</h3><span className="phase-pct">{doneTasks}/5</span></div>
                <div className="phase-items">
                  {visibility.plan ? tasks.map((task) => {
                    const status = taskVisualState(task.state);
                    return (
                      <button type="button" key={task.code} className={`row ${selectedId === task.code ? "active" : ""}`} data-status={status} aria-pressed={selectedId === task.code} onClick={() => { setSelectedId(task.code); setActiveTab("graph"); }}>
                        <span className={`dot ${status}`} />
                        <span className="row-main"><span className="row-title"><span className="code">{task.code}</span><span className="text">{task.card.title}</span></span></span>
                      </button>
                    );
                  }) : <div className="phase-empty">确认 DESIGN 后展示五项任务</div>}
                  <button type="button" className={`row ${selectedId === "acceptance" ? "active" : ""}`} data-status={stageStatus(state, "acceptance")} onClick={() => { setSelectedId("acceptance"); setActiveTab("acceptance"); }}>
                    <span className={`dot ${stageStatus(state, "acceptance")}`} />
                    <span className="row-main"><span className="row-title"><span className="code">ACCEPT</span><span className="text">静态验收总结</span></span></span>
                  </button>
                </div>
              </section>
            </div>
          </section>
        </aside>

        <WorkstationSplitter layout={layout} />

        <section className="canvas">
          <div className="canvas-toolbar">
            <WorkstationLayoutControls layout={layout} attention={gate ? `待确认：${STATIC_GATE_TITLE[gate]}` : undefined} />
            <div className="chips">
              {tabs.map((tab) => (
                <button type="button" key={tab.key} className={`chip ${activeTab === tab.key ? "active" : ""}`} aria-pressed={activeTab === tab.key} onClick={() => setActiveTab(tab.key)}>
                  {tab.label}{tab.count !== undefined && <span className="count">{tab.count}</span>}
                </button>
              ))}
            </div>
            {activeTab === "graph" && <span className="static-canvas-label">{visibility.plan ? "模拟执行／预置结果" : "人工编写的静态阶段图"}</span>}
          </div>

          <div className="canvas-body">
            {activeTab === "graph" && (
              <div className="graph-pane">
                <div className="graph-flow" data-testid="static-demo-graph" ref={graphBox.attach}>
                  <ReactFlow
                    nodes={flowNodes}
                    edges={flowEdges}
                    nodeTypes={nodeTypes}
                    defaultViewport={{ x: 24, y: 24, zoom: 1 }}
                    minZoom={FLOW_MIN_ZOOM}
                    maxZoom={FLOW_MAX_ZOOM}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    onMoveStart={viewport.onMoveStart}
                    onNodeClick={(_, node) => setSelectedId(node.id)}
                  >
                    <Background variant={BackgroundVariant.Dots} gap={22} size={0.7} color="#e3ebf0" />
                    <Controls
                      position="top-right"
                      showInteractive={false}
                      onZoomIn={viewport.markUserMoved}
                      onZoomOut={viewport.markUserMoved}
                    />
                    {/* Structure only: stage changes, node selection and container resizes never refit. */}
                    <FlowAutoFit
                      structure={`static|${visibility.plan ? "plan" : "stages"}`}
                      userMoved={viewport.userMoved}
                      bounds={flowBounds}
                      getSize={graphBox.getSize}
                    />
                    <FlowResetButton userMoved={viewport.userMoved} bounds={flowBounds} getSize={graphBox.getSize} />
                  </ReactFlow>
                </div>
                <div className="dock">
                  <div className="dock-info">
                    <span className="mono muted">{selected.code}</span>
                    <span className="title">{selected.title}</span>
                    <span className="mono">{selectedTask ? STATE_LABEL[selectedTask.state] : stageRawState(state, selectedStage.id)}</span>
                  </div>
                  <div className="dock-actions"><Button size="small" onClick={() => setActiveTab("details")}>查看节点详情</Button></div>
                </div>
              </div>
            )}

            {activeTab === "discussion" && (
              <div className="canvas-scroll static-discussion" data-testid="static-discussion-panel">
                <div className="stack static-content-wide">
                  <div className="notice"><span>人工编写的角色讨论示例 · 不代表真实模型发言或思考过程</span></div>
                  <div className="section-title"><span>提出方案 → 讨论分歧 → 形成结论</span><span className="hint">{state.discussionCount}/10 条</span></div>
                  {state.discussionCount === 0 && <Empty description="点击“下一步”或“自动播放”，逐条展示预置讨论" />}
                  {STATIC_UTTERANCES.slice(0, state.discussionCount).map((utterance) => (
                    <article className="static-utterance" key={utterance.seq} data-testid={`utterance-${utterance.seq}`}>
                      <div className="static-utterance-meta">
                        <span className="mono">#{String(utterance.seq).padStart(2, "0")}</span>
                        <strong>{utterance.speaker}</strong>
                        <Tag color={utterance.phase === "讨论分歧" ? "orange" : utterance.phase === "形成结论" ? "green" : "blue"}>{utterance.phase}</Tag>
                        {utterance.issue && <span className="mono static-issue">{utterance.issue}</span>}
                      </div>
                      <p>{utterance.body}</p>
                    </article>
                  ))}
                  {state.discussionCount === STATIC_UTTERANCES.length && (
                    <section className="static-conclusion" data-testid="discussion-conclusion">
                      <div className="section-title"><span>讨论结论</span><span className="hint">与 SPEC / DESIGN / PLAN 一致</span></div>
                      <div className="static-conclusion-grid">
                        <div><h3>已采纳</h3><ul>{STATIC_DISCUSSION_CONCLUSION.adopted.map((item) => <li key={item}>{item}</li>)}</ul></div>
                        <div><h3>暂缓事项</h3><ul>{STATIC_DISCUSSION_CONCLUSION.deferred.map((item) => <li key={item}>{item}</li>)}</ul></div>
                        <div><h3>验收要点</h3><ul>{STATIC_DISCUSSION_CONCLUSION.acceptance.map((item) => <li key={item}>{item}</li>)}</ul></div>
                      </div>
                    </section>
                  )}
                </div>
              </div>
            )}

            {activeTab === "plan" && (
              <div className="canvas-scroll"><div className="stack static-content-wide">
                <div className="notice"><span>人工编写的静态任务计划 · 状态为模拟执行／预置结果</span></div>
                <TaskPlanPreview
                  plan={visibility.plan ? STATIC_PLAN : null}
                  tasks={visibility.plan ? tasks : []}
                  provenance={{ generation_label: "人工编写的静态任务", execution_label: "模拟执行／预置结果（未真实执行）" }}
                  onSelect={(code) => { setSelectedId(code); setActiveTab("details"); }}
                />
              </div></div>
            )}

            {activeTab === "details" && (
              <div className="canvas-scroll"><div className="stack static-content-wide">
                <div className="detail-head"><span className="mono muted">{selected.code}</span><h2>{selected.title}</h2></div>
                {selectedTask ? (
                  <>
                    <div className="notice"><span>模拟执行／预置结果 · 预置内容／未真实执行</span></div>
                    <div className="kv">
                      <div className="k">任务状态</div><div className="mono">{STATE_LABEL[selectedTask.state]}</div>
                      <div className="k">执行角色</div><div>{selectedTask.card.role}</div>
                      <div className="k">上游依赖</div><div className="mono">{selectedTask.card.depends_on.join("、") || "无"}</div>
                      <div className="k">等待原因</div><div>{selectedTask.state === "pending" && selectedTask.card.depends_on.length ? `等待依赖：${selectedTask.card.depends_on.filter((code) => tasks.find((task) => task.code === code)?.state !== "done").join("、") || "无"}` : "不适用（已开始、就绪或已完成）"}</div>
                    </div>
                    <section><div className="section-title">预置执行摘要</div><p className="static-detail-copy">{STATIC_TASK_DETAILS[selectedTask.code].summary}</p></section>
                    <section><div className="section-title">示例产物与模拟测试结果</div><pre className="code-well">{JSON.stringify({ provenance: "预置内容／未真实执行", ...STATIC_TASK_DETAILS[selectedTask.code] }, null, 2)}</pre></section>
                  </>
                ) : (
                  <>
                    <div className="notice"><span>人工编写的静态阶段节点 · 不是后端真实运行节点</span></div>
                    <div className="kv"><div className="k">阶段状态</div><div className="mono">{stageRawState(state, selectedStage.id)}</div><div className="k">内容说明</div><div>{selectedStage.subtitle}</div><div className="k">运行编号</div><div className="mono">{state.runId}</div></div>
                  </>
                )}
              </div></div>
            )}

            {activeTab === "specs" && (
              <div className="canvas-scroll"><div className="stack static-content-wide">
                <div className="notice"><span>SPEC / DESIGN / PLAN 均为人工编写的预置产物</span></div>
                {[
                  { title: "需求规格", hint: "SPEC 基线", visible: visibility.spec, data: STATIC_SPEC, empty: "讨论结论批准后展示 SPEC" },
                  { title: "设计规格", hint: "DESIGN 模块与接口", visible: visibility.design, data: STATIC_DESIGN, empty: "SPEC 批准后展示 DESIGN" },
                  { title: "开发任务分解", hint: "PLAN 任务图", visible: visibility.plan, data: STATIC_PLAN, empty: "DESIGN 批准后展示 PLAN" },
                ].map((artifact) => (
                  <section key={artifact.title}>
                    <div className="section-title"><span>{artifact.title}</span><span className="hint">{artifact.hint}</span></div>
                    {artifact.visible ? <pre className="code-well static-artifact">{JSON.stringify(artifact.data, null, 2)}</pre> : <div className="well muted static-empty-copy">{artifact.empty}</div>}
                  </section>
                ))}
              </div></div>
            )}

            {activeTab === "activity" && (
              <div className="canvas-scroll"><div className="stack static-content-wide">
                <div className="notice"><span>静态课堂演示事件 · 不是模型调用或真实工具日志</span></div>
                {state.activities.length === 0 && <Empty description="开始演示后显示预置事件" />}
                {[...state.activities].reverse().map((activity) => (
                  <div className="event" key={`${state.replay}-${activity.seq}`}>
                    <span className="seq">#{activity.seq}</span>
                    <div><div><span className="kind">{activity.kind}</span><span className="mono muted static-event-subject">{activity.subject}</span></div><div className="static-event-detail">{activity.detail}</div><div className="mono muted static-event-source">{activity.provenance}</div></div>
                  </div>
                ))}
              </div></div>
            )}

            {activeTab === "acceptance" && (
              <div className="canvas-scroll"><div className="stack static-content-wide" data-testid="static-acceptance-panel">
                {state.stage !== "acceptance" ? <Empty description="五项任务完成后展示静态验收总结" /> : (
                  <>
                    <div className="notice static-acceptance-banner"><span>{STATIC_ACCEPTANCE.provenance}</span></div>
                    <section><div className="section-title"><span>{STATIC_ACCEPTANCE.title}</span><span className="hint">预置验收结果</span></div><p className="static-detail-copy">{STATIC_REQUIREMENT}</p></section>
                    <section className="static-summary-block"><h3>讨论决策</h3><ul>{STATIC_DISCUSSION_CONCLUSION.adopted.map((item) => <li key={item}>{item}</li>)}</ul></section>
                    <section className="static-summary-block"><h3>任务依赖与并行片段</h3><p>T-01 → T-02 / T-03 → T-04 → T-05</p><p>{STATIC_ACCEPTANCE.parallelEvidence}</p></section>
                    <section>
                      <div className="section-title"><span>预置场景结果</span><span className="hint">不计入仓库真实测试统计</span></div>
                      <div className="static-acceptance-list">{STATIC_ACCEPTANCE.scenarios.map((scenario) => <article key={scenario.code}><div><span className="mono">{scenario.code}</span><strong>{scenario.name}</strong><Tag color="blue">{scenario.result}</Tag></div><p>{scenario.evidence}</p></article>)}</div>
                    </section>
                    <section className="static-summary-block"><h3>演示限制</h3><ul>{STATIC_ACCEPTANCE.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>
                  </>
                )}
              </div></div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
