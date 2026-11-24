import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Segmented, Switch, Tooltip, message } from "antd";
import {
  ArrowRightOutlined,
  CheckOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  CaretRightOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
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
  type NodeChange,
} from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, controlEnabled } from "../api/client";
import ArchitecturePreview from "../components/ArchitecturePreview";
import DesignSpecInput from "../components/DesignSpecInput";
import DesignSpecPreview from "../components/DesignSpecPreview";
import { designComposerForced } from "../components/designImportWait";
import TaskPlanPreview from "../components/TaskPlanPreview";
import { useRunEvents } from "../hooks/useRunEvents";
import { taskWaitReason } from "../taskWaitReason";
import { readableFlowEdge } from "../flowEdgeStyle";
import { useFlowNodeHover } from "../useFlowNodeHover";
import { layoutLayered, structureKey } from "../flowLayout";
import { layeredEdgeTypes } from "../LayeredEdge";
import {
  FLOW_MAX_ZOOM,
  FLOW_MIN_ZOOM,
  FlowAutoFit,
  FlowResetButton,
  useFlowViewportMemory,
  useMeasuredElement,
} from "../FlowViewport";
import { WorkstationLayoutControls, WorkstationSplitter, LEFT_PANEL_ID } from "../components/WorkstationSplitter";
import { useWorkstationLayout } from "../workstationLayout";
import {
  buildMainGraph,
  buildStageOverview,
  buildWorkstationItems,
  emptyGraphNotice,
  runStatusLine,
  type ItemStatus,
} from "../workstationGraph";
import {
  autoAdvanceAllowed,
  gateActionsLocked,
  isDesignImporting,
  pauseResumeEnabled,
  pauseResumeKind,
  provenanceMarks,
  scheduleEnabled,
  scheduleNoticeText,
} from "./workstationControls";

const DEFAULT_IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";
const WORKSTATION_TABS = ["graph", "plan", "architecture", "details", "specs", "activity"] as const;
type WorkstationTab = (typeof WORKSTATION_TABS)[number];

const STATUS_META: Record<ItemStatus, { label: string }> = {
  completed: { label: "已完成" },
  in_progress: { label: "进行中" },
  awaiting: { label: "待确认" },
  pending: { label: "待开始" },
  error: { label: "失败/需处理" },
  skipped: { label: "不适用" },
};

const TASK_ACTIONS = [
  ["pause", "暂停"],
  ["resume", "恢复"],
  ["retry", "重试"],
  ["skip", "跳过"],
  ["force-pass", "强制通过"],
  ["takeover", "接管"],
  ["submit-takeover", "提交接管"],
] as const;

const PIPELINE = ["想法", "讨论", "方案", "评审", "SPEC", "DESIGN", "PLAN", "执行", "验收"];

function TwinTaskNode({ data }: { data: any }) {
  const status: ItemStatus = data.status || "pending";
  return (
    <div
      className={`flow-node ${data.selected ? "selected" : ""} ${data.kind === "package" ? "package-node" : ""}`}
      data-status={status}
      title={`${data.code} · ${data.title}（${STATUS_META[status].label}）`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="head">
        <span className={`dot ${status}`} />
        <span className="code">{data.code}</span>
        <span className="state">{data.kind === "package" ? "展开 ›" : data.rawState || STATUS_META[status].label}</span>
      </div>
      <div className="title" title={data.title}>
        {data.title}
      </div>
      {data.subtitle && <div className="sub" title={data.subtitle}>{data.subtitle}</div>}
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

export default function Workstation() {
  const { id: routeRunId } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const routeBase = "/workstation";

  const [projectName, setProjectName] = useState("自习室空位查询小程序");
  const [ideaInput, setIdeaInput] = useState(DEFAULT_IDEA);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { hoveredNodeId, hoverNode, leaveNode } = useFlowNodeHover();
  const [controlReason, setControlReason] = useState("");
  const [gateReason, setGateReason] = useState("");
  const [supplementText, setSupplementText] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = WORKSTATION_TABS.find((tab) => tab === searchParams.get("view")) ?? "graph";
  function setActiveTab(tab: WorkstationTab) {
    if (tab === activeTab) return;
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      if (tab === "graph") next.delete("view");
      else next.set("view", tab);
      return next;
    }, { replace: true });
  }
  const [autoAdvance, setAutoAdvance] = useState(false);
  const [flowMode, setFlowMode] = useState<"idea" | "design">("idea");
  const [designResult, setDesignResult] = useState<any>(null);
  const [sessionProjectId, setSessionProjectId] = useState<string | undefined>();
  const [canvasAspect, setCanvasAspect] = useState(0);
  const [openedPackage, setOpenedPackage] = useState<string | null>(null);
  // The aspect is taken from the first measurement only (it just shapes edge-less grids), so later
  // container changes - splitter drags, window resizes - never re-lay-out or refit the view.
  const graphBox = useMeasuredElement((w, h) => setCanvasAspect((previous) => previous || aspectBucket(w, h)));
  const layout = useWorkstationLayout();
  const viewport = useFlowViewportMemory();
  const [editSourceSignal, setEditSourceSignal] = useState(0);

  const { data: runsList } = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: 3000,
  });

  const availableRuns = useMemo(
    () => (Array.isArray(runsList) ? runsList : []),
    [runsList],
  );

  const activeRunId = useMemo(() => {
    if (routeRunId) return routeRunId;
    if (!Array.isArray(availableRuns)) return undefined;
    // Default to a run this build can still operate. Retired DeepSeek snapshots stay
    // reachable from the sidebar/selector but must not take over the main workbench.
    const operable = availableRuns.filter(
      (item: any) => !(item.read_only || item.provenance?.mode === "deepseek"),
    );
    return operable.length > 0 ? operable[operable.length - 1].id : undefined;
  }, [routeRunId, availableRuns]);

  const {
    data: run,
    isPending: runPending,
    isError: runQueryFailed,
    error: runQueryError,
  } = useQuery({
    queryKey: ["run", activeRunId],
    queryFn: () => api.run(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: 2000,
  });

  const { data: projectList } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.projects(true),
    staleTime: 30_000,
  });

  const summaryTitle = useMemo(() => {
    const items = Array.isArray(projectList) ? projectList : [];
    const match = items.find((project: any) => project.id === run?.project_id);
    return match?.name || "未命名项目";
  }, [projectList, run?.project_id]);

  const { data: artifacts, isPending: artifactsPending, isError: artifactsFailed } = useQuery({
    queryKey: ["arts", activeRunId],
    queryFn: () => api.artifacts(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: 2500,
  });

  const { data: tasks } = useQuery({
    queryKey: ["tasks", activeRunId],
    queryFn: () => api.tasks(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: 2000,
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15000,
    retry: false,
  });

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["runs"] });
    if (activeRunId) {
      qc.invalidateQueries({ queryKey: ["run", activeRunId] });
      qc.invalidateQueries({ queryKey: ["arts", activeRunId] });
      qc.invalidateQueries({ queryKey: ["tasks", activeRunId] });
    }
  };

  const {
    events,
    connection: eventConnection,
    connectionError: eventConnectionError,
    reconnect: reconnectEvents,
  } = useRunEvents(activeRunId, refreshAll);

  const startRunMut = useMutation({
    mutationFn: async (opts: { autoToExec?: boolean }) => {
      const pName = projectName.trim() || "Workstation Project";
      const idea = ideaInput.trim() || DEFAULT_IDEA;
      const proj = await api.createProject(pName);
      const created = await api.createRun(proj.id, idea);
      let currentRunId: string = created.run.id;

      if (opts.autoToExec) {
        for (let step = 0; step < 8; step++) {
          const r = await api.run(currentRunId);
          const pendingGate = (r.gates || []).find((g: any) => g.status === "pending");
          if (!pendingGate) break;
          await api.resolveGate(pendingGate.id, "approve", { reason: "Workstation 一键推进基线确认" });
          if (pendingGate.kind === "PLAN基线确认") {
            await api.schedule(currentRunId);
            break;
          }
        }
      }
      return currentRunId;
    },
    onSuccess: (newRunId) => {
      message.success(`运行已启动: ${newRunId.slice(0, 8)}`);
      qc.invalidateQueries({ queryKey: ["runs"] });
      nav(`${routeBase}/${newRunId}`);
    },
    onError: (err: any) => {
      message.error(`启动失败: ${err?.message || String(err)}`);
    },
  });

  const pendingGate = useMemo(
    () => (run?.gates || []).find((g: any) => g.status === "pending"),
    [run?.gates],
  );

  const designView = designResult && designResult.run_id === activeRunId ? designResult : null;
  const isDesignRun = run?.origin === "design_spec";
  const importingDesign = isDesignImporting({
    artifactStatus: artifacts?.design_input_status,
    inFlight: designResult,
    activeRunId,
  });
  const waitingForRun = Boolean(activeRunId) && runPending && !run;
  const composerMode: "idea" | "design" = designComposerForced(artifacts, run) && flowMode === "idea"
    ? "design"
    : flowMode;
  const legacyRetired = Boolean(run?.read_only || run?.provenance?.mode === "deepseek");
  const showDesignPreview = Boolean(
    activeRunId && (isDesignRun || designView || artifacts?.design_input_status),
  );
  const designProjectId = run?.project_id || sessionProjectId;
  const controlOpts = { importing: importingDesign, statusQueryFailed: runQueryFailed };
  const runPauseKind = legacyRetired ? null : pauseResumeKind(run);
  const runPauseEnabled = !legacyRetired && pauseResumeEnabled(run, controlOpts);
  const canSchedule = !legacyRetired && scheduleEnabled(run, controlOpts);
  const scheduleMode = health?.schedule_mode;
  // Existing idea/discussion runs already carry their input; only new runs and
  // design-spec runs (which support source editing) need the composer.
  const showComposer = !activeRunId || isDesignRun || legacyRetired;

  const handleDesignCreated = (result: any) => {
    if (result?.project_id) setSessionProjectId(result.project_id);
    setDesignResult(result);
    qc.invalidateQueries({ queryKey: ["runs"] });
    if (result?.run_id) {
      qc.invalidateQueries({ queryKey: ["arts", result.run_id] });
      qc.invalidateQueries({ queryKey: ["run", result.run_id] });
    }
    setSelectedId(null);
    setActiveTab("graph");
    if (result?.run_id && result.run_id !== routeRunId) nav(`${routeBase}/${result.run_id}`);
  };

  const resolveGateMut = useMutation({
    mutationFn: async ({ decision }: { decision: "approve" | "reject" }) => {
      if (!pendingGate) throw new Error("没有待确认关卡");
      const payload: Record<string, any> = {};
      if (gateReason.trim()) payload.reason = gateReason.trim();
      if (pendingGate.kind === "想法补充" && supplementText.trim()) {
        payload.text = supplementText.trim();
      }
      return api.resolveGate(pendingGate.id, decision, payload);
    },
    onSuccess: (_data, vars) => {
      message.success(vars.decision === "approve" ? "已批准并推进" : "已驳回");
      setGateReason("");
      setSupplementText("");
      refreshAll();
    },
    onError: (err: any) => {
      message.error(`关卡处理失败: ${err?.message || String(err)}`);
    },
  });

  const scheduleMut = useMutation({
    mutationFn: () => api.schedule(activeRunId!),
    onSuccess: (res) => {
      const started = res?.started || [];
      message.success(started.length ? `已调度执行任务: ${started.join(", ")}` : "本轮调度完成");
      refreshAll();
    },
    onError: (err: any) => {
      message.error(`调度失败: ${err?.message || String(err)}`);
    },
  });

  const acceptMut = useMutation({
    mutationFn: () => api.accept(activeRunId!),
    onSuccess: () => {
      message.success("已触发生成验收报告与验收确认关卡");
      refreshAll();
    },
    onError: (err: any) => {
      message.error(`验收触发失败: ${err?.message || String(err)}`);
    },
  });

  const controlMut = useMutation({
    mutationFn: ({ code, action, revision }: { code: string; action: string; revision: number }) =>
      api.control(code, action, revision, controlReason),
    onSuccess: (_, vars) => {
      message.success(`任务 ${vars.code} 执行动作 ${vars.action} 成功`);
      refreshAll();
    },
    onError: (err: any) => {
      message.error(`任务控制失败: ${err?.message || String(err)}`);
    },
  });

  const runCtrlMut = useMutation({
    mutationFn: (action: "pause" | "resume" | "terminate") => {
      if (!activeRunId) return Promise.reject(new Error("没有运行"));
      if (action === "pause") return api.pauseRun(activeRunId);
      if (action === "resume") return api.resumeRun(activeRunId);
      return api.terminate(activeRunId);
    },
    onSuccess: (_data, action) => {
      const ok = { pause: "已暂停", resume: "已恢复", terminate: "已终止" };
      message.success(ok[action] || "操作成功");
      refreshAll();
    },
    onError: (err: any, action) => {
      const fail = { pause: "暂停失败", resume: "恢复失败", terminate: "终止失败" };
      message.error(`${fail[action] || "操作失败"}: ${err?.message || String(err)}`);
    },
  });

  const gatesLocked = gateActionsLocked({
    resolving: resolveGateMut.isPending,
    importing: importingDesign,
    statusQueryFailed: runQueryFailed,
  });

  const autoAdvanceActive = autoAdvance && !legacyRetired;
  useEffect(() => {
    if (!activeRunId || !run) return;
    if (
      !autoAdvanceAllowed({
        autoAdvance: autoAdvanceActive,
        hasPendingGate: Boolean(pendingGate),
        gatesLocked,
      })
    ) {
      return;
    }
    const timer = setTimeout(() => {
      resolveGateMut.mutate({ decision: "approve" });
    }, 600);
    return () => clearTimeout(timer);
  }, [autoAdvanceActive, activeRunId, run, pendingGate, gatesLocked]);

  const { phases, allItems, workPackages } = useMemo(
    () => buildWorkstationItems({ run, artifacts, tasks, pendingGate, isDesignRun }),
    [run, artifacts, tasks, pendingGate, isDesignRun],
  );
  const overview = useMemo(() => buildStageOverview(allItems, run), [allItems, run]);
  const mainGraph = useMemo(
    () => buildMainGraph(allItems, workPackages, openedPackage),
    [allItems, workPackages, openedPackage],
  );
  const openedPackageItem = workPackages.find((item) => item.id === openedPackage);

  useEffect(() => {
    setOpenedPackage(null);
  }, [activeRunId]);

  useEffect(() => {
    if (openedPackage && !workPackages.some((item) => item.id === openedPackage)) {
      setOpenedPackage(null);
    }
  }, [workPackages, openedPackage]);

  const progressItems = allItems.filter((i) => i.status !== "skipped");
  const completedCount = progressItems.filter((i) => i.status === "completed").length;
  const totalCount = progressItems.length || 1;
  const overallPercent = run ? Math.round((completedCount / totalCount) * 100) : 0;

  const selectedItem = useMemo(
    () => allItems.find((i) => i.id === selectedId) || mainGraph.items[0] || allItems[0] || null,
    [allItems, mainGraph, selectedId],
  );

  const graphIds = useMemo(() => mainGraph.items.map((item) => item.id), [mainGraph]);
  const graphStructure = structureKey(graphIds, mainGraph.edges);
  // Re-layout only when the structure (or the quantised container shape) changes, not on status polls.
  const layered = useMemo(
    () => layoutLayered(graphIds, mainGraph.edges, {
      aspect: canvasAspect || undefined,
      rankGap: mainGraph.kind === "packages" ? 172 : undefined,
      nodeGap: mainGraph.kind === "packages" ? 72 : undefined,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graphStructure, canvasAspect, mainGraph.kind],
  );

  const flowNodes = useMemo<Node[]>(
    () =>
      mainGraph.items.map((item) => ({
        id: item.id,
        type: "twinTask",
        position: layered.positions[item.id] || { x: 0, y: 0 },
        draggable: false,
        connectable: false,
        ariaLabel: `${item.code} ${item.title}，${STATUS_META[item.status].label}`,
        data: { ...item, selected: selectedItem?.id === item.id },
      })),
    [mainGraph, layered, selectedItem?.id],
  );

  const edgePorts = useMemo(() => {
    const sourceOffsets = new Map<string, number>();
    const targetOffsets = new Map<string, number>();
    const assign = (end: "source" | "target") => {
      const groups = new Map<string, string[]>();
      for (const edge of mainGraph.edges) {
        const node = end === "source" ? edge.source : edge.target;
        groups.set(node, [...(groups.get(node) || []), edge.id]);
      }
      const offsets = new Map<string, number>();
      for (const ids of groups.values()) {
        if (ids.length < 2) continue;
        ids.sort((left, right) => {
          const edgeLeft = mainGraph.edges.find((edge) => edge.id === left)!;
          const edgeRight = mainGraph.edges.find((edge) => edge.id === right)!;
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
  }, [mainGraph, layered]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      mainGraph.edges.map((edge) => ({
        ...readableFlowEdge({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "layered",
          focusNodeId: hoveredNodeId || selectedId,
        }),
        data: {
          route: layered.routes[edge.id],
          ortho: mainGraph.kind === "packages" || mainGraph.kind === "tasks",
          sourceOffset: edgePorts.sources.get(edge.id) || 0,
          targetOffset: edgePorts.targets.get(edge.id) || 0,
        },
      })),
    [mainGraph, layered, hoveredNodeId, selectedId, edgePorts],
  );

  const onNodesChange = (changes: NodeChange[]) => {
    // Keyboard selection (Enter on a focused node) arrives as a select change; nothing else is applied.
    for (const change of changes) {
      if (change.type === "select" && change.selected) setSelectedId(change.id);
    }
  };

  const designImportStatus: string | undefined = artifacts?.design_input_status;
  const emptyNotice = emptyGraphNotice({ run, designImportStatus, importing: importingDesign, isDesignRun });
  const statusLine = runStatusLine({
    run,
    artifacts,
    pendingGate,
    importing: importingDesign,
    queryFailed: runQueryFailed,
    allItems,
    isDesignRun,
  });
  const modeBadge = legacyRetired
    ? "已下线 · 只读"
    : isDesignRun || composerMode === "design"
      ? "设计规格"
      : "完整流程";
  const graphCaption = workPackages.length > 0
    ? openedPackage
      ? `${openedPackageItem?.title || openedPackage} · ${mainGraph.items.length} 个子任务`
      : `工作包 · ${workPackages.length} 个`
    : mainGraph.kind === "tasks"
      ? `任务依赖图 · ${mainGraph.items.length} 个任务`
      : mainGraph.kind === "modules"
        ? `设计模块 · ${mainGraph.items.length} 个（仅属于 DESIGN）`
        : "暂无可展示的图";

  const hasReadyTasks = useMemo(
    () => (tasks || []).some((t: any) => t.state === "ready" || t.state === "stale"),
    [tasks],
  );

  const taskByCode = useMemo(
    () => new Map<string, any>((tasks || []).map((t: any) => [t.code, t])),
    [tasks],
  );

  const selectedRuntime = selectedItem?.kind === "task" ? taskByCode.get(selectedItem.code) : undefined;

  const selectedWaitReason = useMemo(
    () => taskWaitReason(selectedRuntime, selectedItem || { dependsOn: [] }, taskByCode),
    [selectedRuntime, selectedItem, taskByCode],
  );

  const isTaskSelected = selectedItem?.kind === "task" && selectedItem.detail?.revision !== undefined;
  const tabs: Array<{ key: WorkstationTab; label: string; count?: number }> = [
    { key: "graph", label: "流程图" },
    { key: "plan", label: "任务计划", count: artifacts?.plan?.tasks?.length },
    { key: "architecture", label: "架构图", count: artifacts?.design?.modules?.length },
    { key: "details", label: "节点详情" },
    { key: "specs", label: "规格产物" },
    { key: "activity", label: "活动" },
  ];

  const renderControls = (compact: boolean) => (
    <>
      <Input
        size="small"
        aria-label="任务控制理由"
        placeholder="控制理由（跳过 / 强制通过必填）"
        value={controlReason}
        onChange={(e) => setControlReason(e.target.value)}
        style={{ width: compact ? 200 : 280 }}
      />
      {TASK_ACTIONS.map(([action, label]) => (
        <Tooltip key={action} title={action}>
          <Button
            size="small"
            type={compact ? "text" : "default"}
            disabled={legacyRetired || !controlEnabled(action, selectedItem!.detail.state)}
            loading={controlMut.isPending && controlMut.variables?.action === action}
            onClick={() =>
              controlMut.mutate({
                code: selectedItem!.code,
                action,
                revision: selectedItem!.detail.revision,
              })
            }
          >
            {label}
          </Button>
        </Tooltip>
      ))}
    </>
  );

  return (
    <div className="ws">
      <div className={layout.bodyClassName} style={layout.bodyStyle} ref={layout.bodyRef}>
        <aside
          className="ws-left"
          id={LEFT_PANEL_ID}
          aria-label="工作台运行面板"
          ref={layout.leftRef}
          tabIndex={-1}
        >
          {activeRunId && (
            <section className="ws-summary" aria-label="运行摘要" data-testid="run-summary">
              <div className="ws-summary-head">
                <strong className="ws-summary-name" title={summaryTitle}>
                  {summaryTitle}
                </strong>
                <span className="mode-badge" data-testid="mode-badge">{modeBadge}</span>
                <Tooltip title="刷新">
                  <Button size="small" type="text" aria-label="刷新" icon={<ReloadOutlined />} onClick={refreshAll} />
                </Tooltip>
              </div>
              <div className={`ws-status-line tone-${statusLine.tone}`} role="status" data-testid="run-status-line">
                <span
                  className={`dot ${statusLine.tone === "done" ? "completed" : statusLine.tone === "awaiting" ? "awaiting" : statusLine.tone === "error" ? "error" : statusLine.tone === "progress" ? "in_progress" : "pending"}`}
                  aria-hidden="true"
                />
                {statusLine.text}
              </div>
              {run && (
                <div className="ws-run-actions" data-testid="run-actions">
                  <Tooltip title="自动批准当前挂起关卡以快速推进">
                    <span className="pill auto-advance">
                      <Switch size="small" aria-label="自动过关" checked={autoAdvanceActive} disabled={legacyRetired} onChange={setAutoAdvance} />
                      自动过关
                    </span>
                  </Tooltip>
                  {run.stage === "7" && (
                    <Button
                      size="small"
                      type="primary"
                      aria-label="调度执行"
                      icon={<PlayCircleOutlined />}
                      loading={scheduleMut.isPending}
                      disabled={!canSchedule}
                      onClick={() => scheduleMut.mutate()}
                    >
                      调度执行
                    </Button>
                  )}
                  {run.stage === "8" && run.status !== "done" && !pendingGate && (
                    <Button
                      size="small"
                      type="primary"
                      icon={<CheckOutlined />}
                      loading={acceptMut.isPending}
                      disabled={legacyRetired || runQueryFailed || importingDesign}
                      onClick={() => acceptMut.mutate()}
                    >
                      生成验收报告
                    </Button>
                  )}
                  {runPauseKind && (
                    <Button
                      size="small"
                      icon={runPauseKind === "resume" ? <CaretRightOutlined /> : <PauseOutlined />}
                      aria-label={runPauseKind === "resume" ? "恢复" : "暂停"}
                      data-testid="run-pause-resume"
                      disabled={!runPauseEnabled || runCtrlMut.isPending}
                      loading={runCtrlMut.isPending}
                      onClick={() => runCtrlMut.mutate(runPauseKind)}
                    >
                      {runPauseKind === "resume" ? "恢复" : "暂停"}
                    </Button>
                  )}
                </div>
              )}
              {run?.idea && (
                <div className="ws-idea-bubble" data-testid="run-idea">
                  <p>{run.idea}</p>
                </div>
              )}
            </section>
          )}
          {showComposer && (
          <section className="composer glass-panel" aria-labelledby="composer-heading">
            <div className="panel-heading">
              <span className="panel-icon"><ThunderboltOutlined /></span>
              <h2 id="composer-heading">
                {legacyRetired
                  ? "历史运行（只读）"
                  : waitingForRun && composerMode === "idea"
                    ? "运行加载中"
                    : composerMode === "design"
                      ? "设计规格输入"
                      : "想法输入"}
              </h2>
            </div>
            {legacyRetired ? (
              <Alert
                type="warning"
                showIcon
                data-testid="retired-run-notice"
                message="已下线，只读，不支持继续调用"
                description="该历史运行由已下线的 DeepSeek 专用入口创建。历史产物、事件与任务快照仍可查看；新建、重试、恢复或继续生成 PLAN 均不会发往模型。"
              />
            ) : (
              <>
            <Segmented
                block
                size="small"
                aria-label="选择流程入口"
                value={composerMode}
                disabled={waitingForRun}
                onChange={(val) => setFlowMode(val as "idea" | "design")}
                options={[
                  { label: "完整流程", value: "idea" },
                  { label: "从设计规格开始", value: "design" },
                ]}
              />
            {waitingForRun && composerMode === "idea" ? (
              <div className="mono muted">正在加载运行…</div>
            ) : composerMode === "design" ? (
              <DesignSpecInput
                projectName={projectName}
                onProjectName={setProjectName}
                onCreated={handleDesignCreated}
                watchingImport={importingDesign}
                importArtifacts={artifacts}
                projectId={designProjectId}
                onProjectId={setSessionProjectId}
                runId={activeRunId}
                editSourceSignal={editSourceSignal}
              />
            ) : (
              <>
                <div className="composer-fields">
                  <input
                    className="composer-name"
                    aria-label="项目名称"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    placeholder="项目名称"
                  />
                  <textarea
                    aria-label="产品想法"
                    rows={3}
                    value={ideaInput}
                    onChange={(e) => setIdeaInput(e.target.value)}
                    placeholder="用一两句话描述产品想法…"
                  />
                </div>
                <div className="composer-actions">
                  <Tooltip title="创建后逐个关卡推进到任务分解并开始执行">
                    <Button
                      size="small"
                      type="text"
                      icon={<ThunderboltOutlined />}
                      loading={startRunMut.isPending}
                      onClick={() => startRunMut.mutate({ autoToExec: true })}
                    >
                      一键推进到执行
                    </Button>
                  </Tooltip>
                  <Button
                    size="small"
                    type="primary"
                    loading={startRunMut.isPending}
                    onClick={() => startRunMut.mutate({ autoToExec: false })}
                  >
                    启动 <ArrowRightOutlined />
                  </Button>
                </div>
              </>
            )}
              </>
            )}
          </section>
          )}

          {runQueryFailed && (
            <Alert
              type="warning"
              showIcon
              data-testid="run-status-error"
              message="状态查询失败"
              description={
                (runQueryError as Error)?.message
                  ? `未能读取运行状态：${(runQueryError as Error).message}。未开放暂停、批准或调度。`
                  : "未能读取运行状态，未开放暂停、批准或调度。"
              }
            />
          )}

          {showDesignPreview && (
            <DesignSpecPreview
              artifacts={artifacts}
              result={designView}
              hideProvenance
              onEditSource={() => setEditSourceSignal((n) => n + 1)}
            />
          )}

          {pendingGate && !runQueryFailed && !legacyRetired && (
            <section className="gate-card glass-panel" aria-labelledby="gate-heading">
              <div>
                <div className="gate-kicker">等待你确认</div>
                <h2 className="gate-head" id="gate-heading">
                  <span className="dot awaiting" />
                  {pendingGate.kind}
                </h2>
              </div>
              {pendingGate.kind === "想法补充" && (
                <Input.TextArea
                  rows={2}
                  aria-label="补充想法"
                  placeholder="补充缺失的用户或问题说明…"
                  value={supplementText}
                  onChange={(e) => setSupplementText(e.target.value)}
                />
              )}
              <Input
                size="small"
                aria-label="裁决理由"
                placeholder={
                  pendingGate.kind === "验收确认" && !pendingGate.payload?.pass
                    ? "验收未通过，人工批准必须填写理由"
                    : "裁决理由（可选）"
                }
                value={gateReason}
                onChange={(e) => setGateReason(e.target.value)}
              />
              <div className="gate-actions">
                <Button
                  type="primary"
                  size="small"
                  aria-label="批准并推进"
                  loading={resolveGateMut.isPending && resolveGateMut.variables?.decision === "approve"}
                  disabled={
                    gatesLocked ||
                    (pendingGate.kind === "验收确认" && !pendingGate.payload?.pass && !gateReason.trim())
                  }
                  onClick={() => resolveGateMut.mutate({ decision: "approve" })}
                >
                  批准并推进
                </Button>
                <Button
                  size="small"
                  danger
                  type="text"
                  aria-label={pendingGate.kind === "DESIGN基线确认" && isDesignRun ? "驳回（需改原文重提）" : "驳回重写"}
                  loading={resolveGateMut.isPending && resolveGateMut.variables?.decision === "reject"}
                  disabled={gatesLocked}
                  onClick={() => resolveGateMut.mutate({ decision: "reject" })}
                >
                  {pendingGate.kind === "DESIGN基线确认" && isDesignRun ? "驳回（需改原文重提）" : "驳回重写"}
                </Button>
              </div>
            </section>
          )}

          {pendingGate && legacyRetired && (
            <div className="notice" data-testid="retired-gate-notice">
              <span>历史关卡「{pendingGate.kind}」保留为只读；已下线模式不支持继续裁决。</span>
            </div>
          )}

          {hasReadyTasks && !pendingGate && !legacyRetired && (
            <div className="notice" data-testid="schedule-notice">
              <span>{scheduleNoticeText(scheduleMode)}</span>
              <Button
                size="small"
                type="primary"
                loading={scheduleMut.isPending}
                disabled={!canSchedule}
                onClick={() => scheduleMut.mutate()}
              >
                立即调度
              </Button>
            </div>
          )}

          <section className="progress-section" aria-labelledby="progress-heading">
            <div className="progress-summary glass-panel">
            <div className="section-title">
              <h2 id="progress-heading">进度</h2>
              <span className="hint mono">
                {completedCount}/{progressItems.length} · {overallPercent}%
              </span>
            </div>
            <div className="meter brand" role="progressbar" aria-label="整体进度" aria-valuenow={overallPercent} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${overallPercent}%` }} />
            </div>
            </div>

            <details className="node-list">
            <summary>
              节点列表 <span className="hint mono">{allItems.length} 项 · 点选后在右侧查看详情</span>
            </summary>
            <div className="phase-list">
            {phases.map((phase) => {
              const countable = phase.items.filter((i) => i.status !== "skipped");
              const doneCnt = countable.filter((i) => i.status === "completed").length;
              return (
                <section className="phase glass-panel" key={phase.key} aria-labelledby={`${phase.key}-heading`}>
                  <div className="phase-head">
                    <span className="phase-no">{phase.no}</span>
                    <h3 className="phase-title" id={`${phase.key}-heading`}>{phase.title}</h3>
                    <span className="phase-pct">
                      {doneCnt}/{countable.length || phase.items.length}
                    </span>
                  </div>
                  <div className="phase-items">
                  {phase.items.length === 0 && <div className="phase-empty">尚无条目</div>}
                  {phase.items.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      className={`row ${selectedItem?.id === item.id ? "active" : ""}`}
                      aria-pressed={selectedItem?.id === item.id}
                      data-status={item.status}
                      onClick={() => {
                        setSelectedId(item.id);
                        if (item.kind === "task" && item.parent) setOpenedPackage(item.parent);
                      }}
                    >
                      <span className={`dot ${item.status}`} aria-hidden="true" />
                      <span className="row-main">
                        <span className="row-title">
                          <span className="code">{item.code}</span>
                          <span className="text" title={item.title}>
                            {item.title}
                          </span>
                        </span>
                        {item.subtitle && (
                          <span className="row-sub" title={item.subtitle}>
                            {item.subtitle}
                          </span>
                        )}
                      </span>
                    </button>
                  ))}
                  </div>
                </section>
              );
            })}
            </div>
            </details>
          </section>
        </aside>

        <WorkstationSplitter layout={layout} />

        <section className="canvas">
          <div className="canvas-toolbar">
            <WorkstationLayoutControls
              layout={layout}
              attention={pendingGate && !runQueryFailed ? `待确认：${pendingGate.kind}` : undefined}
            />
            <div className="chips">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  className={`chip ${activeTab === t.key ? "active" : ""}`}
                      aria-pressed={activeTab === t.key}
                  onClick={() => setActiveTab(t.key)}
                >
                  {t.label}
                  {t.count !== undefined && <span className="count">{t.count}</span>}
                </button>
              ))}
            </div>
            {activeTab === "graph" && activeRunId && (
              <div className="legend">
                {(Object.keys(STATUS_META) as ItemStatus[]).map((s) => (
                  <span key={s}>
                    <span className={`dot ${s}`} style={{ animation: "none" }} />
                    {STATUS_META[s].label}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="canvas-body">
            {!activeRunId ? (
              availableRuns === undefined ? null : <div className="hero">
                <h1>
                  把一句想法，
                  <br />
                  推进成可交付的工程。
                </h1>
                <p>
                  在左侧写下产品想法并启动。多个角色会依次讨论、评审、产出规格与设计，再分解为任务交给编排器执行，每个关键节点都等你确认。
                </p>
                <div className="pipeline">
                  {PIPELINE.map((s, i) => (
                    <span key={s} style={{ display: "inline-flex", gap: 6 }}>
                      <span className="pill">{s}</span>
                      {i < PIPELINE.length - 1 && (
                        <span className="arrow">
                          <ArrowRightOutlined style={{ fontSize: 10 }} />
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {activeTab === "graph" && (
                  <div className="graph-pane">
                    <ol className="stage-strip" aria-label="阶段概览" data-testid="stage-overview">
                      {overview.map((stage) => (
                        <li
                          key={stage.key}
                          className={`stage-step ${stage.current ? "current" : ""}`}
                          data-status={stage.status}
                          aria-current={stage.current ? "step" : undefined}
                          title={`${stage.label}：${STATUS_META[stage.status].label}${stage.rawState ? `（${stage.rawState}）` : ""}`}
                        >
                          <span className={`dot ${stage.status}`} aria-hidden="true" />
                          <span className="stage-label">{stage.label}</span>
                          <span className="stage-state">{STATUS_META[stage.status].label}</span>
                        </li>
                      ))}
                      <li className="stage-caption" data-testid="graph-caption">
                        {openedPackage && (
                          <button
                            type="button"
                            className="graph-back"
                            onClick={() => {
                              setOpenedPackage(null);
                              setSelectedId(null);
                            }}
                          >
                            ← 全部工作包
                          </button>
                        )}
                        <span>{graphCaption}</span>
                      </li>
                    </ol>
                    <div className="graph-flow" ref={graphBox.attach}>
                      {mainGraph.kind === "empty" && (
                        <div className={`graph-empty tone-${emptyNotice.tone}`} role="status" data-testid="graph-empty">
                          <strong>{emptyNotice.title}</strong>
                          <span>{emptyNotice.detail}</span>
                        </div>
                      )}
                      <ReactFlow
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
                        onNodeClick={(_, node) => {
                          const item = mainGraph.items.find((entry) => entry.id === node.id);
                          if (item?.kind === "package") {
                            setOpenedPackage(node.id);
                            setSelectedId(null);
                          } else {
                            setSelectedId(node.id);
                          }
                        }}
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
                          structure={`${activeRunId}|${graphStructure}|${canvasAspect}`}
                          userMoved={viewport.userMoved}
                          bounds={{ width: layered.width, height: layered.height }}
                          getSize={graphBox.getSize}
                          readableZoom={0.82}
                        />
                        <FlowResetButton
                          userMoved={viewport.userMoved}
                          bounds={{ width: layered.width, height: layered.height }}
                          getSize={graphBox.getSize}
                        />
                      </ReactFlow>
                    </div>

                    {selectedItem && (
                      <div className="dock">
                        <div className="dock-info">
                          <span className={`dot ${selectedItem.status}`} />
                          <span className="mono muted">{selectedItem.code}</span>
                          <span className="title">{selectedItem.title}</span>
                          <span className="mono" style={{ color: "var(--ink-4)" }}>
                            {selectedItem.rawState}
                          </span>
                        </div>
                        <div className="dock-actions">
                          {isTaskSelected && renderControls(true)}
                          <Button size="small" onClick={() => setActiveTab(isTaskSelected ? "details" : "specs")}>
                            {isTaskSelected ? "详情" : "查看产物"}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {activeTab === "plan" && (
                  <div className="canvas-scroll">
                    <div className="stack" style={{ maxWidth: 860 }}>
                      <TaskPlanPreview
                        plan={artifacts?.plan}
                        tasks={tasks || []}
                        provenance={run?.provenance}
                        onSelect={(code) => {
                          setSelectedId(code);
                          setActiveTab("details");
                        }}
                      />
                    </div>
                  </div>
                )}

                {activeTab === "architecture" && (
                  <ArchitecturePreview
                    key={activeRunId}
                    design={artifacts?.design}
                    plan={artifacts?.plan}
                    runtimeTasks={tasks}
                    loading={artifactsPending}
                    failed={artifactsFailed}
                    onSelectTask={(code) => {
                      setSelectedId(code);
                      setActiveTab("details");
                    }}
                  />
                )}

                {activeTab === "details" && (
                  <div className="canvas-scroll">
                    {selectedItem ? (
                      <div className="stack" style={{ maxWidth: 860 }}>
                        <div>
                          <div className="detail-head">
                            <span className={`dot ${selectedItem.status}`} />
                            <span className="mono muted">{selectedItem.code}</span>
                            <h2>{selectedItem.title}</h2>
                          </div>
                          <div className="kv">
                            <div className="k">状态</div>
                            <div>
                              {STATUS_META[selectedItem.status].label}
                              <span className="mono muted" style={{ marginLeft: 8 }}>
                                {selectedItem.rawState}
                              </span>
                            </div>
                            <div className="k">节点类型</div>
                            <div className="mono">{selectedItem.kind}</div>
                            <div className="k">所属阶段</div>
                            <div>{phases.find((p) => p.key === selectedItem.phaseKey)?.title}</div>
                            <div className="k">上游依赖</div>
                            <div className="mono">{selectedItem.dependsOn.join(", ") || "无"}</div>
                            {selectedRuntime && (
                              <>
                                <div className="k">等待原因</div>
                                <div data-testid="wait-reason">{selectedWaitReason || "不适用（已开始或已完成）"}</div>
                                {selectedRuntime.last_error && (
                                  <>
                                    <div className="k">最近错误</div>
                                    <div style={{ color: "var(--danger, #b42318)" }}>{selectedRuntime.last_error}</div>
                                  </>
                                )}
                                {selectedRuntime.prev_output && (
                                  <>
                                    <div className="k">上一版产物</div>
                                    <div className="mono muted" style={{ whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto" }}>
                                      {selectedRuntime.prev_output}
                                    </div>
                                  </>
                                )}
                              </>
                            )}
                            {selectedItem.detail?.card && (
                              <>
                                <div className="k">执行角色</div>
                                <div>{selectedItem.detail.card.role}</div>
                                <div className="k">估算点数</div>
                                <div className="mono">{selectedItem.detail.card.points} pt</div>
                                <div className="k">允许写集</div>
                                <div className="mono">{(selectedItem.detail.card.write_set || []).join(", ")}</div>
                                <div className="k">验收命令</div>
                                <div className="mono">
                                  {(selectedItem.detail.card.acceptance || [])
                                    .map((a: any) => (a.cmd || []).join(" "))
                                    .join(" ; ")}
                                </div>
                              </>
                            )}
                          </div>
                        </div>

                        {isTaskSelected && (
                          <div>
                            <div className="section-title">任务控制</div>
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{renderControls(false)}</div>
                            {selectedItem.detail.takeover_workspace && (
                              <div className="pill" style={{ marginTop: 10 }}>
                                接管工作树 <span className="mono">{selectedItem.detail.takeover_workspace}</span>
                              </div>
                            )}
                          </div>
                        )}

                        <div>
                          <div className="section-title">产物与证据</div>
                          <pre className="code-well" style={{ maxHeight: 360 }}>
                            {JSON.stringify(selectedItem.detail || {}, null, 2)}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <Empty description="在左侧或流程图中选择一个节点" />
                    )}
                  </div>
                )}

                {activeTab === "specs" && (
                  <div className="canvas-scroll">
                    <div className="stack" style={{ maxWidth: 860 }}>
                      {[
                        { title: "需求规格", hint: "SPEC 基线", data: artifacts?.spec, empty: "尚未生成 SPEC，请先推进前序关卡" },
                        { title: "设计规格", hint: "DESIGN 模块与接口", data: artifacts?.design, empty: "尚未进入阶段 5 设计规格" },
                        { title: "开发任务分解", hint: "PLAN 任务图", data: artifacts?.plan, empty: "尚未进入阶段 6 任务分解" },
                      ].map((s) => (
                        <div key={s.title}>
                          <div className="section-title">
                            <span>{s.title}</span>
                            <span className="hint">{s.hint}</span>
                          </div>
                          {s.data ? (
                            <pre className="code-well" style={{ maxHeight: 260 }}>
                              {JSON.stringify(s.data, null, 2)}
                            </pre>
                          ) : (
                            <div className="well muted" style={{ padding: "14px 16px" }}>
                              {s.empty}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === "activity" && (
                  <div className="canvas-scroll">
                    <div style={{ maxWidth: 860 }} className="stack">
                      {eventConnection === "error" && (
                        <Alert
                          type="error"
                          showIcon
                          data-testid="events-connection-error"
                          message={eventConnectionError || "事件连接已断开"}
                          description={
                            <div>
                              <div>实时推送已中断，下方仅为断开前已收到的事件；恢复不代表任务成功。</div>
                              <Button size="small" icon={<ReloadOutlined />} onClick={reconnectEvents}>
                                重新连接
                              </Button>
                            </div>
                          }
                        />
                      )}
                      {eventConnection === "connecting" && activeRunId && (
                        <Alert type="info" showIcon message="正在连接事件流…" />
                      )}
                      {events.length === 0 && eventConnection !== "error" && <Empty description="暂无事件" />}
                      {[...events].reverse().map((ev: any) => (
                        <div className="event" key={ev.seq}>
                          <span className="seq">#{ev.seq}</span>
                          <div style={{ minWidth: 0 }}>
                            <div>
                              <span className="kind">{ev.kind}</span>
                              {ev.subject && <span className="mono muted" style={{ marginLeft: 8 }}>{ev.subject}</span>}
                            </div>
                            <div className="payload" title={JSON.stringify(ev.payload || {})}>
                              {JSON.stringify(ev.payload || {})}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
