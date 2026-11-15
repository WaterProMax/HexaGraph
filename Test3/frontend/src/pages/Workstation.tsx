import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Segmented, Select, Switch, Tooltip, message } from "antd";
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
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { api, controlEnabled } from "../api/client";
import DesignSpecInput from "../components/DesignSpecInput";
import DesignSpecPreview from "../components/DesignSpecPreview";
import TaskPlanPreview from "../components/TaskPlanPreview";
import { useRunEvents } from "../hooks/useRunEvents";

const DEFAULT_IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";

type ItemStatus = "completed" | "in_progress" | "pending" | "error" | "skipped";

interface PhaseTaskItem {
  id: string;
  code: string;
  title: string;
  subtitle?: string;
  status: ItemStatus;
  rawState?: string;
  phaseKey: string;
  dependsOn: string[];
  kind: "stage" | "spec" | "design" | "task";
  detail?: any;
}

const STATUS_META: Record<ItemStatus, { label: string; edge: string }> = {
  completed: { label: "已完成", edge: "#a1a1aa" },
  in_progress: { label: "进行中", edge: "#0066fa" },
  pending: { label: "待开始", edge: "#d4d4d8" },
  error: { label: "需处理", edge: "#f76808" },
  skipped: { label: "不适用", edge: "#94a3b8" },
};

const RUN_STATUS: Record<string, string> = {
  running: "运行中",
  waiting: "等待确认",
  done: "已完成",
  terminated: "已终止",
  stopped: "已停止",
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

function mapTaskState(state: string): ItemStatus {
  if (state === "done") return "completed";
  if (state === "skipped" || state === "cancelled") return "skipped";
  if (["running", "verifying", "ready"].includes(state)) return "in_progress";
  if (["failed", "needs_human", "blocked", "stale"].includes(state)) return "error";
  return "pending";
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const NODE_W = 216;
const NODE_H = 72;
const COL_W = 236;
const ROW_H = 88;
const GROUP_PAD = 14;
const GROUP_HEAD = 48;
const GROUP_GAP = 32;

interface GroupBox {
  x: number;
  y: number;
  w: number;
  h: number;
  cols: number;
}

function phaseLayout(phases: { items: unknown[] }[], orientation: "row" | "column") {
  const sizes = phases.map((p) => {
    const n = p.items.length;
    const cols = orientation === "row" ? (n > 4 ? 2 : 1) : 3;
    const rows = Math.max(1, Math.ceil(n / cols));
    return {
      cols,
      w: GROUP_PAD * 2 + (cols - 1) * COL_W + NODE_W,
      h: GROUP_HEAD + (rows - 1) * ROW_H + NODE_H + GROUP_PAD,
    };
  });
  const maxW = Math.max(...sizes.map((s) => s.w));
  const maxH = Math.max(...sizes.map((s) => s.h));
  let offset = 0;
  const groups: GroupBox[] = sizes.map((s) => {
    const box =
      orientation === "row"
        ? { x: offset, y: 0, w: s.w, h: maxH, cols: s.cols }
        : { x: 0, y: offset, w: maxW, h: s.h, cols: s.cols };
    offset += (orientation === "row" ? s.w : s.h) + GROUP_GAP;
    return box;
  });
  const span = offset - GROUP_GAP;
  return { groups, bounds: orientation === "row" ? { w: span, h: maxH } : { w: maxW, h: span } };
}

function PhaseGroupNode({ data }: { data: any }) {
  return (
    <div className="flow-group">
      <span className="label">
        <span className="no">{data.no}</span>
        <span>{data.title}</span>
        <span className="pct">{data.progressText}</span>
      </span>
    </div>
  );
}

function TwinTaskNode({ data }: { data: any }) {
  const status: ItemStatus = data.status || "pending";
  return (
    <div className={`flow-node ${data.selected ? "selected" : ""}`} data-status={status}>
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span className={`dot ${status}`} />
        <span className="code">{data.code}</span>
        <span className="state">{data.rawState || STATUS_META[status].label}</span>
      </div>
      <div className="title" title={data.title}>
        {data.title}
      </div>
      {data.subtitle && <div className="sub">{data.subtitle}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = {
  phaseGroup: PhaseGroupNode,
  twinTask: TwinTaskNode,
};

function AutoFit({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    // New nodes need a frame to be measured before fitView sees their size.
    const timer = setTimeout(() => fitView({ padding: 0.1, duration: 200 }), 60);
    return () => clearTimeout(timer);
  }, [signature, fitView]);
  return null;
}

export default function Workstation() {
  const { id: routeRunId } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();

  const [projectName, setProjectName] = useState("自习室空位查询小程序");
  const [ideaInput, setIdeaInput] = useState(DEFAULT_IDEA);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [controlReason, setControlReason] = useState("");
  const [gateReason, setGateReason] = useState("");
  const [supplementText, setSupplementText] = useState("");
  const [activeTab, setActiveTab] = useState("graph");
  const [autoAdvance, setAutoAdvance] = useState(false);
  const [flowMode, setFlowMode] = useState<"idea" | "design">("idea");
  const [designResult, setDesignResult] = useState<any>(null);
  const flowRef = useRef<HTMLDivElement>(null);
  const [canvasSize, setCanvasSize] = useState({ w: 0, h: 0 });

  const { data: runsList } = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: 3000,
  });

  const activeRunId = useMemo(() => {
    if (routeRunId) return routeRunId;
    if (Array.isArray(runsList) && runsList.length > 0) {
      return runsList[runsList.length - 1].id;
    }
    return undefined;
  }, [routeRunId, runsList]);

  const { data: run } = useQuery({
    queryKey: ["run", activeRunId],
    queryFn: () => api.run(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: 2000,
  });

  const { data: artifacts } = useQuery({
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

  const { data: budget } = useQuery({
    queryKey: ["budget", activeRunId],
    queryFn: () => api.budget(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: 4000,
  });

  const { events, connection: eventConnection, connectionError: eventConnectionError } = useRunEvents(activeRunId);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["runs"] });
    if (activeRunId) {
      qc.invalidateQueries({ queryKey: ["run", activeRunId] });
      qc.invalidateQueries({ queryKey: ["arts", activeRunId] });
      qc.invalidateQueries({ queryKey: ["tasks", activeRunId] });
      qc.invalidateQueries({ queryKey: ["budget", activeRunId] });
    }
  };

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
      nav(`/workstation/${newRunId}`);
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
  const showDesignPreview = Boolean(activeRunId && (isDesignRun || designView));

  const handleDesignCreated = (result: any) => {
    setDesignResult(result);
    qc.invalidateQueries({ queryKey: ["runs"] });
    setSelectedId(null);
    setActiveTab("graph");
    if (result?.run_id) nav(`/workstation/${result.run_id}`);
  };

  const resolveGateMut = useMutation({
    mutationFn: async ({ decision }: { decision: "approve" | "reject" }) => {
      if (!pendingGate) return;
      const payload: Record<string, any> = {};
      if (gateReason.trim()) payload.reason = gateReason.trim();
      if (pendingGate.kind === "想法补充" && supplementText.trim()) {
        payload.text = supplementText.trim();
      }
      return api.resolveGate(pendingGate.id, decision, payload);
    },
    onSuccess: () => {
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
      if (!activeRunId) return Promise.resolve();
      if (action === "pause") return api.pauseRun(activeRunId);
      if (action === "resume") return api.resumeRun(activeRunId);
      return api.terminate(activeRunId);
    },
    onSuccess: () => refreshAll(),
  });

  useEffect(() => {
    if (!autoAdvance || !activeRunId || !run) return;
    if (pendingGate && !resolveGateMut.isPending) {
      const timer = setTimeout(() => {
        resolveGateMut.mutate({ decision: "approve" });
      }, 600);
      return () => clearTimeout(timer);
    }
  }, [autoAdvance, activeRunId, run, pendingGate]);

  useEffect(() => {
    const el = flowRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setCanvasSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [activeTab, activeRunId]);

  const { phases, allItems } = useMemo(() => {
    const stageStr = String(run?.stage ?? "0");
    const stageNum = stageStr === "done" ? 9 : stageStr === "stopped" ? -1 : Number(stageStr);
    const hasSpec = Boolean(artifacts?.spec);
    const hasDesign = Boolean(artifacts?.design);
    const hasPlan = Boolean(artifacts?.plan);
    const skipDiscussion = Boolean(isDesignRun || artifacts?.design_input);

    const p1Items: PhaseTaskItem[] = [
      {
        id: "S-IDEA",
        code: "STAGE-0",
        title: "想法解析与初步做法",
        subtitle: skipDiscussion
          ? "设计规格入口跳过讨论"
          : artifacts?.idea_card?.approach || "idea_checker / pm_draft",
        status: !run
          ? "pending"
          : skipDiscussion
          ? "skipped"
          : stageNum >= 1
          ? "completed"
          : pendingGate
          ? "error"
          : "in_progress",
        rawState: skipDiscussion ? "不适用" : stageNum >= 1 ? "confirmed" : pendingGate?.kind || "stage-0",
        phaseKey: "phase1",
        dependsOn: [],
        kind: "stage",
        detail: artifacts?.idea_card,
      },
      {
        id: "S-DISC",
        code: "STAGE-1..3",
        title: "多体讨论与方案评审",
        subtitle: skipDiscussion
          ? "不适用（从设计规格开始）"
          : `争议 ${(artifacts?.issues || []).length} 项 · 发言 ${(artifacts?.utterances || []).length} 条`,
        status: !run
          ? "pending"
          : skipDiscussion
          ? "skipped"
          : stageNum >= 4
          ? "completed"
          : stageNum >= 1
          ? pendingGate
            ? "error"
            : "in_progress"
          : "pending",
        rawState: skipDiscussion ? "不适用" : stageNum >= 4 ? "reviewed" : stageNum >= 1 ? "discussing" : "pending",
        phaseKey: "phase1",
        dependsOn: ["S-IDEA"],
        kind: "stage",
        detail: { issues: artifacts?.issues, reviews: artifacts?.reviews },
      },
      {
        id: "S-SPEC",
        code: "SPEC",
        title: "需求规格基线",
        subtitle: hasSpec
          ? `功能 ${(artifacts?.spec?.features || []).length} 项 · 基线 v${artifacts?.baseline_SPEC || "draft"}`
          : skipDiscussion
          ? "由设计规格整理得到"
          : "spec_writer / check_spec",
        status: !run
          ? "pending"
          : stageNum >= 5
          ? "completed"
          : hasSpec
          ? pendingGate?.kind === "SPEC基线确认"
            ? "error"
            : "in_progress"
          : "pending",
        rawState: artifacts?.baseline_SPEC ? `v${artifacts.baseline_SPEC}` : hasSpec ? "await_gate" : "pending",
        phaseKey: "phase1",
        dependsOn: skipDiscussion ? [] : ["S-DISC"],
        kind: "spec",
        detail: artifacts?.spec,
      },
    ];

    const designModules: any[] = artifacts?.design?.modules || [];
    const p2Items: PhaseTaskItem[] = [
      {
        id: "S-DESIGN",
        code: "DESIGN",
        title: "架构与设计规格",
        subtitle: hasDesign
          ? `模块 ${designModules.length} 个 · 接口 ${(artifacts?.design?.interfaces || []).length} 个`
          : "architect + 双评审背靠背打分",
        status: !run
          ? "pending"
          : stageNum >= 6
          ? "completed"
          : stageNum === 5 || hasDesign
          ? pendingGate?.kind === "DESIGN基线确认"
            ? "error"
            : "in_progress"
          : "pending",
        rawState: artifacts?.baseline_DESIGN ? `v${artifacts.baseline_DESIGN}` : hasDesign ? "await_gate" : "pending",
        phaseKey: "phase2",
        dependsOn: ["S-SPEC"],
        kind: "design",
        detail: artifacts?.design,
      },
      ...designModules.map((m: any) => ({
        id: `MOD-${m.code}`,
        code: m.code,
        title: m.name,
        subtitle: m.responsibility || `追溯 ${(m.sources || []).join(", ") || "-"}`,
        status: (stageNum >= 6 ? "completed" : "in_progress") as ItemStatus,
        rawState: stageNum >= 6 ? "frozen" : "draft",
        phaseKey: "phase2",
        dependsOn: ["S-DESIGN"],
        kind: "design" as const,
        detail: m,
      })),
    ];

    const planTasks: any[] = artifacts?.plan?.tasks || [];
    const runtimeTaskList: any[] = Array.isArray(tasks) ? tasks : [];
    const runtimeByCode = new Map(runtimeTaskList.map((t: any) => [t.code, t]));

    const p3Items: PhaseTaskItem[] = [
      {
        id: "S-PLAN",
        code: "PLAN",
        title: "任务分解与 DAG 校验",
        subtitle: hasPlan
          ? `${planTasks.length} 个开发任务 · 容量 ${artifacts?.plan?.capacity || 40} 点`
          : "decomposer / check_task_graph",
        status: !run
          ? "pending"
          : stageNum >= 7
          ? "completed"
          : stageNum === 6 || hasPlan
          ? pendingGate?.kind === "PLAN基线确认"
            ? "error"
            : "in_progress"
          : "pending",
        rawState: artifacts?.baseline_PLAN ? `v${artifacts.baseline_PLAN}` : hasPlan ? "await_gate" : "pending",
        phaseKey: "phase3",
        dependsOn: designModules.length > 0 ? designModules.map((m: any) => `MOD-${m.code}`) : ["S-DESIGN"],
        kind: "stage",
        detail: artifacts?.plan,
      },
    ];

    const taskSourceList =
      runtimeTaskList.length > 0
        ? runtimeTaskList
        : planTasks.map((card: any) => ({
            code: card.code,
            state: "pending",
            revision: 1,
            card,
          }));

    const p4Items: PhaseTaskItem[] = taskSourceList.map((t: any) => {
      const card = t.card || {};
      const deps: string[] = card.depends_on || [];
      return {
        id: t.code,
        code: t.code,
        title: card.title || t.code,
        subtitle: `${card.role || "coder"} · ${card.kind || "impl"} · ${card.module || "M1"} · ${card.points || 1}pt`,
        status: mapTaskState(t.state),
        rawState: t.state,
        phaseKey: "phase4",
        dependsOn: deps.length > 0 ? deps : ["S-PLAN"],
        kind: "task",
        detail: runtimeByCode.get(t.code) || t,
      };
    });

    if (stageNum >= 8 || artifacts?.acceptance) {
      p4Items.push({
        id: "S-ACCEPT",
        code: "ACCEPT",
        title: "集成回归与交付验收",
        subtitle: artifacts?.build_tag
          ? `已发布标签 ${artifacts.build_tag}`
          : pendingGate?.kind === "验收确认"
          ? "待人工确认验收关卡"
          : "就绪，可触发验收",
        status:
          run?.status === "done"
            ? "completed"
            : pendingGate?.kind === "验收确认"
            ? "error"
            : "in_progress",
        rawState: run?.status === "done" ? "done" : "stage-8",
        phaseKey: "phase4",
        dependsOn: taskSourceList.length > 0 ? taskSourceList.map((t: any) => t.code) : ["S-PLAN"],
        kind: "stage",
        detail: artifacts?.acceptance,
      });
    }

    const phaseDefs = [
      { key: "phase1", no: "Phase 1", title: "想法与需求规格", items: p1Items },
      { key: "phase2", no: "Phase 2", title: "设计规格与模块契约", items: p2Items },
      { key: "phase3", no: "Phase 3", title: "开发任务分解", items: p3Items },
      { key: "phase4", no: "Phase 4", title: "编排执行与验收", items: p4Items },
    ];

    const flat = phaseDefs.flatMap((p) => p.items);
    return { phases: phaseDefs, allItems: flat };
  }, [run, artifacts, tasks, pendingGate, isDesignRun]);

  const progressItems = allItems.filter((i) => i.status !== "skipped");
  const completedCount = progressItems.filter((i) => i.status === "completed").length;
  const totalCount = progressItems.length || 1;
  const overallPercent = run ? Math.round((completedCount / totalCount) * 100) : 0;

  const selectedItem = useMemo(
    () => allItems.find((i) => i.id === selectedId) || allItems.find((i) => i.kind === "task") || allItems[0] || null,
    [allItems, selectedId],
  );

  const orientation = useMemo<"row" | "column">(() => {
    if (!canvasSize.w || !canvasSize.h) return "row";
    const row = phaseLayout(phases, "row");
    const column = phaseLayout(phases, "column");
    const fit = (b: { w: number; h: number }) => Math.min(canvasSize.w / b.w, canvasSize.h / b.h);
    return fit(row.bounds) >= fit(column.bounds) ? "row" : "column";
  }, [phases, canvasSize]);

  const { flowNodes, flowEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const { groups } = phaseLayout(phases, orientation);

    phases.forEach((phase, phaseIdx) => {
      const items = phase.items;
      const g = groups[phaseIdx];
      const countable = items.filter((i) => i.status !== "skipped");
      const doneInPhase = countable.filter((i) => i.status === "completed").length;

      nodes.push({
        id: `group-${phase.key}`,
        type: "phaseGroup",
        position: { x: g.x, y: g.y },
        style: { width: g.w, height: g.h, zIndex: 0 },
        selectable: false,
        draggable: false,
        data: {
          no: phase.no,
          title: phase.title,
          progressText: `${doneInPhase}/${countable.length || items.length}`,
        },
      });

      items.forEach((item, idx) => {
        const col = idx % g.cols;
        const row = Math.floor(idx / g.cols);
        nodes.push({
          id: item.id,
          type: "twinTask",
          position: {
            x: g.x + GROUP_PAD + col * COL_W,
            y: g.y + GROUP_HEAD + row * ROW_H,
          },
          style: { zIndex: 2 },
          data: {
            ...item,
            selected: selectedItem?.id === item.id,
          },
        });

        item.dependsOn.forEach((depId) => {
          const color = STATUS_META[item.status].edge;
          edges.push({
            id: `e-${depId}-${item.id}`,
            source: depId,
            target: item.id,
            type: "smoothstep",
            animated: item.status === "in_progress",
            style: {
              stroke: color,
              strokeWidth: 1.5,
              strokeDasharray: item.status === "pending" ? "4 4" : undefined,
            },
            markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
          });
        });
      });
    });

    return { flowNodes: nodes, flowEdges: edges };
  }, [phases, orientation, selectedItem?.id]);

  const hasReadyTasks = useMemo(
    () => (tasks || []).some((t: any) => t.state === "ready" || t.state === "stale"),
    [tasks],
  );

  const taskByCode = useMemo(
    () => new Map<string, any>((tasks || []).map((t: any) => [t.code, t])),
    [tasks],
  );

  const selectedRuntime = selectedItem?.kind === "task" ? taskByCode.get(selectedItem.code) : undefined;

  const selectedWaitReason = useMemo(() => {
    if (!selectedRuntime) return "";
    const state = selectedRuntime.state;
    if (state === "ready" || state === "stale") return "依赖已满足，等待调度";
    if (state === "pending") {
      const unmet = (selectedItem?.dependsOn || []).filter(
        (code: string) => (taskByCode.get(code)?.state ?? "pending") !== "done",
      );
      return unmet.length ? `等待依赖：${unmet.join("、")}` : "依赖已满足，等待调度";
    }
    if (state === "blocked" || state === "failed") {
      return selectedRuntime.last_error || "上游未完成，已阻塞";
    }
    return "";
  }, [selectedRuntime, selectedItem, taskByCode]);

  const isTaskSelected = selectedItem?.kind === "task" && selectedItem.detail?.revision !== undefined;
  const budgetUsed = budget?.used ?? 0;
  const budgetLimit = budget?.limit ?? 0;
  const budgetPct = budgetLimit ? Math.min(100, (budgetUsed / budgetLimit) * 100) : 0;

  const tabs = [
    { key: "graph", label: "流程图" },
    { key: "plan", label: "任务计划", count: artifacts?.plan?.tasks?.length },
    { key: "details", label: "节点详情" },
    { key: "specs", label: "规格产物" },
    { key: "activity", label: "活动", count: events.length },
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
            disabled={!controlEnabled(action, selectedItem!.detail.state)}
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
      <header className="topbar">
        <div className="topbar-left">
          <span className="crumb">
            工作台 <span style={{ color: "var(--ink-4)" }}>/</span>
            <strong>{run ? run.idea?.slice(0, 18) || "运行" : "新运行"}</strong>
          </span>
          {Array.isArray(runsList) && runsList.length > 0 && (
            <Select
              size="small"
              aria-label="选择历史运行"
              classNames={{ popup: { root: "glass-select-popup" } }}
              variant="filled"
              style={{ width: 220 }}
              value={activeRunId}
              placeholder="选择历史运行"
              onChange={(val) => nav(`/workstation/${val}`)}
              options={[...runsList].reverse().map((r: any) => ({
                value: r.id,
                label: `#${r.id.slice(0, 6)} · 阶段 ${r.stage} · ${RUN_STATUS[r.status] || r.status}`,
              }))}
            />
          )}
        </div>

        {run && (
          <div className="topbar-right">
            <span className="pill">
              <span className={`dot ${run.status === "done" ? "completed" : run.paused || pendingGate ? "error" : "in_progress"}`} />
              阶段 {run.stage} · {run.paused ? "已暂停" : RUN_STATUS[run.status] || run.status}
            </span>
            <Tooltip title={`令牌 ${budgetUsed.toLocaleString()} / ${budgetLimit.toLocaleString()}`}>
              <span className="pill" style={{ gap: 8 }}>
                <span className="mono">
                  {fmtNum(budgetUsed)} / {fmtNum(budgetLimit)}
                </span>
                <span className="meter brand" style={{ width: 48 }}>
                  <span style={{ width: `${budgetPct}%` }} />
                </span>
              </span>
            </Tooltip>
            <Tooltip title="自动批准当前挂起关卡以快速推进">
              <span className="pill auto-advance">
                <Switch size="small" aria-label="自动过关" checked={autoAdvance} onChange={setAutoAdvance} />
                自动过关
              </span>
            </Tooltip>
            {run.stage === "7" && (
              <Button
                size="small"
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={scheduleMut.isPending}
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
                onClick={() => acceptMut.mutate()}
              >
                生成验收报告
              </Button>
            )}
            <Button
              size="small"
              icon={run.paused ? <CaretRightOutlined /> : <PauseOutlined />}
              aria-label={run.paused ? "恢复" : "暂停"}
              onClick={() => runCtrlMut.mutate(run.paused ? "resume" : "pause")}
            >
              {run.paused ? "恢复" : "暂停"}
            </Button>
            <Tooltip title="刷新">
              <Button size="small" type="text" aria-label="刷新" icon={<ReloadOutlined />} onClick={refreshAll} />
            </Tooltip>
          </div>
        )}
      </header>

      <div className="ws-body">
        <aside className="ws-left" aria-label="工作台运行面板">
          <section className="composer glass-panel" aria-labelledby="composer-heading">
            <div className="panel-heading">
              <span className="panel-icon"><ThunderboltOutlined /></span>
              <h2 id="composer-heading">{flowMode === "design" ? "设计规格输入" : "想法输入"}</h2>
            </div>
            <Segmented
              block
              size="small"
              aria-label="选择流程入口"
              value={flowMode}
              onChange={(val) => setFlowMode(val as "idea" | "design")}
              options={[
                { label: "完整流程", value: "idea" },
                { label: "从设计规格开始", value: "design" },
              ]}
            />
            {flowMode === "design" ? (
              <DesignSpecInput
                projectName={projectName}
                onProjectName={setProjectName}
                onCreated={handleDesignCreated}
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
          </section>

          {showDesignPreview && (
            <DesignSpecPreview artifacts={artifacts} result={designView} />
          )}

          {pendingGate && (
            <section className="gate-card glass-panel" aria-labelledby="gate-heading">
              <div>
                <div className="gate-kicker">等待你确认</div>
                <h2 className="gate-head" id="gate-heading">
                  <span className="dot error" />
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
                  loading={resolveGateMut.isPending}
                  disabled={pendingGate.kind === "验收确认" && !pendingGate.payload?.pass && !gateReason.trim()}
                  onClick={() => resolveGateMut.mutate({ decision: "approve" })}
                >
                  批准并推进
                </Button>
                <Button
                  size="small"
                  danger
                  type="text"
                  loading={resolveGateMut.isPending}
                  onClick={() => resolveGateMut.mutate({ decision: "reject" })}
                >
                  {pendingGate.kind === "DESIGN基线确认" && isDesignRun ? "驳回（需改原文重提）" : "驳回重写"}
                </Button>
              </div>
            </section>
          )}

          {hasReadyTasks && !pendingGate && (
            <div className="notice">
              <span>有就绪任务，编排器每 5 秒自动调度一次。</span>
              <Button size="small" type="primary" loading={scheduleMut.isPending} onClick={() => scheduleMut.mutate()}>
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
                      onClick={() => setSelectedId(item.id)}
                    >
                      <span className={`dot ${item.status}`} aria-hidden="true" />
                      <span className="row-main">
                        <span className="row-meta">
                          <span className="code">{item.code}</span>
                          <span className="row-state">{item.rawState}</span>
                        </span>
                        <span className="row-title">
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
          </section>
        </aside>

        <section className="canvas">
          <div className="canvas-toolbar">
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
              runsList === undefined ? null : <div className="hero">
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
                    <div className="graph-flow" ref={flowRef}>
                      <ReactFlow
                        nodes={flowNodes}
                        edges={flowEdges}
                        nodeTypes={nodeTypes}
                        fitView
                        fitViewOptions={{ padding: 0.1 }}
                        minZoom={0.3}
                        onNodeClick={(_, node) => {
                          if (!node.id.startsWith("group-")) {
                            setSelectedId(node.id);
                          }
                        }}
                      >
                        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#b5cfe1" />
                        <Controls position="top-right" showInteractive={false} />
                        <AutoFit
                          signature={`${orientation}:${flowNodes.length}:${canvasSize.w}x${canvasSize.h}`}
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
                          description="实时推送已中断，请刷新页面后重试；下方仅为断开前已收到的事件。"
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
