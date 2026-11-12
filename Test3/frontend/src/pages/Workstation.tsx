import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Input,
  List,
  Progress,
  Select,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  ApartmentOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  ControlOutlined,
  ExclamationCircleFilled,
  FileTextOutlined,
  HistoryOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RocketOutlined,
  StepForwardOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { api, controlEnabled } from "../api/client";
import { useRunEvents } from "../hooks/useRunEvents";

const DEFAULT_IDEA = "做一个帮同学在期末周找到有空位自习室的小程序。";

type ItemStatus = "completed" | "in_progress" | "pending" | "error";

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

const STATUS_META: Record<
  ItemStatus,
  { color: string; bg: string; border: string; tagColor: string; label: string }
> = {
  completed: {
    color: "#237804",
    bg: "#f6ffed",
    border: "#52c41a",
    tagColor: "success",
    label: "Completed",
  },
  in_progress: {
    color: "#d46b08",
    bg: "#fff7e6",
    border: "#fa8c16",
    tagColor: "warning",
    label: "In Progress",
  },
  pending: {
    color: "#595959",
    bg: "#fafafa",
    border: "#d9d9d9",
    tagColor: "default",
    label: "Pending",
  },
  error: {
    color: "#cf1322",
    bg: "#fff1f0",
    border: "#ff4d4f",
    tagColor: "error",
    label: "Needs Action / Error",
  },
};

function mapTaskState(state: string): ItemStatus {
  if (state === "done") return "completed";
  if (["running", "verifying", "ready"].includes(state)) return "in_progress";
  if (["failed", "needs_human", "blocked", "stale"].includes(state)) return "error";
  return "pending";
}

function StatusIcon({ status }: { status: ItemStatus }) {
  if (status === "completed") return <CheckCircleFilled style={{ color: "#52c41a", fontSize: 15 }} />;
  if (status === "in_progress") return <SyncOutlined spin style={{ color: "#fa8c16", fontSize: 15 }} />;
  if (status === "error") return <ExclamationCircleFilled style={{ color: "#ff4d4f", fontSize: 15 }} />;
  return <ClockCircleOutlined style={{ color: "#bfbfbf", fontSize: 15 }} />;
}

function PhaseGroupNode({ data }: { data: any }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        border: "1.5px dashed #91caff",
        borderRadius: 10,
        background: "rgba(240, 245, 255, 0.38)",
        padding: "8px 12px",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          background: "#e6f4ff",
          border: "1px solid #91caff",
          borderRadius: 6,
          padding: "2px 10px",
          fontSize: 12,
          fontWeight: 600,
          color: "#0958d9",
        }}
      >
        <span>{data.label}</span>
        <span style={{ fontWeight: 400, color: "#1677ff" }}>{data.progressText}</span>
      </div>
    </div>
  );
}

function TwinTaskNode({ data }: { data: any }) {
  const status: ItemStatus = data.status || "pending";
  const meta = STATUS_META[status];
  return (
    <div
      style={{
        width: 210,
        borderRadius: 8,
        background: "#fff",
        border: `2px solid ${ data.selected ? "#1677ff" : meta.border }`,
        boxShadow: data.selected
          ? "0 0 0 3px rgba(22, 119, 255, 0.22)"
          : "0 2px 6px rgba(0, 0, 0, 0.06)",
        padding: "8px 10px",
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "#8c8c8c" }} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <Space size={6}>
          <StatusIcon status={status} />
          <Typography.Text strong style={{ fontSize: 12, color: "#1f1f1f" }}>
            {data.code}
          </Typography.Text>
        </Space>
        <Tag
          color={meta.tagColor}
          style={{ margin: 0, fontSize: 10, lineHeight: "16px", padding: "0 5px" }}
        >
          {data.rawState || meta.label}
        </Tag>
      </div>
      <div
        style={{
          fontWeight: 500,
          color: "#262626",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
        title={data.title}
      >
        {data.title}
      </div>
      {data.subtitle && (
        <div
          style={{
            fontSize: 11,
            color: "#8c8c8c",
            marginTop: 2,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {data.subtitle}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: "#8c8c8c" }} />
    </div>
  );
}

const nodeTypes = {
  phaseGroup: PhaseGroupNode,
  twinTask: TwinTaskNode,
};

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

  const events = useRunEvents(activeRunId);

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

  // Auto-advance helper if user toggles auto-pilot
  useEffect(() => {
    if (!autoAdvance || !activeRunId || !run) return;
    if (pendingGate && !resolveGateMut.isPending) {
      const timer = setTimeout(() => {
        resolveGateMut.mutate({ decision: "approve" });
      }, 600);
      return () => clearTimeout(timer);
    }
  }, [autoAdvance, activeRunId, run, pendingGate]);

  // Build Phases & Items for Left Panel & Right Twin Graph
  const { phases, allItems } = useMemo(() => {
    const stageStr = String(run?.stage ?? "0");
    const stageNum = stageStr === "done" ? 9 : stageStr === "stopped" ? -1 : Number(stageStr);
    const hasSpec = Boolean(artifacts?.spec);
    const hasDesign = Boolean(artifacts?.design);
    const hasPlan = Boolean(artifacts?.plan);

    const p1Items: PhaseTaskItem[] = [
      {
        id: "S-IDEA",
        code: "STAGE-0",
        title: "需求想法解析与初步做法 (Idea Check)",
        subtitle: artifacts?.idea_card?.approach || "idea_checker / pm_draft",
        status: !run ? "pending" : stageNum >= 1 ? "completed" : pendingGate ? "error" : "in_progress",
        rawState: stageNum >= 1 ? "confirmed" : pendingGate?.kind || "stage-0",
        phaseKey: "phase1",
        dependsOn: [],
        kind: "stage",
        detail: artifacts?.idea_card,
      },
      {
        id: "S-DISC",
        code: "STAGE-1..3",
        title: "多体讨论与方案评审 (Multi-Agent Review)",
        subtitle: `争议 ${(artifacts?.issues || []).length} 项 / 发言 ${(artifacts?.utterances || []).length} 条`,
        status: !run
          ? "pending"
          : stageNum >= 4
          ? "completed"
          : stageNum >= 1
          ? pendingGate
            ? "error"
            : "in_progress"
          : "pending",
        rawState: stageNum >= 4 ? "reviewed" : stageNum >= 1 ? "discussing" : "pending",
        phaseKey: "phase1",
        dependsOn: ["S-IDEA"],
        kind: "stage",
        detail: { issues: artifacts?.issues, reviews: artifacts?.reviews },
      },
      {
        id: "S-SPEC",
        code: "SPEC",
        title: "需求规格确认 (SPEC Baseline Sync)",
        subtitle: hasSpec
          ? `功能 ${(artifacts?.spec?.features || []).length} 项 (Baseline v${artifacts?.baseline_SPEC || "draft"})`
          : "spec_writer & check_spec",
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
        dependsOn: ["S-DISC"],
        kind: "spec",
        detail: artifacts?.spec,
      },
    ];

    const designModules: any[] = artifacts?.design?.modules || [];
    const p2Items: PhaseTaskItem[] = [
      {
        id: "S-DESIGN",
        code: "DESIGN",
        title: "架构与设计规格生成 (Design Spec)",
        subtitle: hasDesign
          ? `模块 ${designModules.length} 个 / 接口 ${(artifacts?.design?.interfaces || []).length} 个`
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
        title: `${m.name} (${m.responsibility})`,
        subtitle: `追溯: ${(m.sources || []).join(", ") || "-"}`,
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
        title: "开发任务分解与 DAG 校验 (TaskGraph Decompose)",
        subtitle: hasPlan
          ? `共 ${planTasks.length} 个开发任务 / 容量 ${artifacts?.plan?.capacity || 40} 点`
          : "decomposer + check_task_graph",
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
        subtitle: `[${card.role || "coder"}/${card.kind || "impl"}] 模块 ${card.module || "M1"} · ${card.points || 1}pt`,
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
        title: "集成回归与交付包验收 (Acceptance & Build)",
        subtitle: artifacts?.build_tag
          ? `已发布标签 ${artifacts.build_tag}`
          : pendingGate?.kind === "验收确认"
          ? "待人工确认验收关卡"
          : "就绪可触发验收",
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
      { key: "phase1", title: "Phase 1: 想法与需求规格 (SPECSync)", items: p1Items },
      { key: "phase2", title: "Phase 2: 设计规格与模块契约 (Design Spec)", items: p2Items },
      { key: "phase3", title: "Phase 3: 开发任务分解 (TaskGraph)", items: p3Items },
      {
        key: "phase4",
        title: "Phase 4: 编排器调度与执行控制 (Orchestrator Execution)",
        items: p4Items,
      },
    ];

    const flat = phaseDefs.flatMap((p) => p.items);
    return { phases: phaseDefs, allItems: flat };
  }, [run, artifacts, tasks, pendingGate]);

  const completedCount = allItems.filter((i) => i.status === "completed").length;
  const totalCount = allItems.length || 1;
  const overallPercent = run ? Math.round((completedCount / totalCount) * 100) : 0;

  const selectedItem = useMemo(
    () => allItems.find((i) => i.id === selectedId) || allItems.find((i) => i.kind === "task") || allItems[0] || null,
    [allItems, selectedId],
  );

  // Build React Flow Nodes and Edges with Phase Grouping Boxes
  const { flowNodes, flowEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    let currentX = 24;

    phases.forEach((phase) => {
      const items = phase.items;
      const cols = items.length > 3 ? 2 : 1;
      const rows = Math.max(1, Math.ceil(items.length / cols));
      const groupWidth = cols * 240 + 40;
      const groupHeight = Math.max(240, rows * 96 + 64);
      const doneInPhase = items.filter((i) => i.status === "completed").length;
      const pct = items.length ? Math.round((doneInPhase / items.length) * 100) : 0;

      nodes.push({
        id: `group-${phase.key}`,
        type: "phaseGroup",
        position: { x: currentX, y: 20 },
        style: { width: groupWidth, height: groupHeight, zIndex: 0 },
        selectable: false,
        draggable: false,
        data: {
          label: phase.title.split(":")[0],
          progressText: `${pct}% (${doneInPhase}/${items.length})`,
        },
      });

      items.forEach((item, idx) => {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        nodes.push({
          id: item.id,
          type: "twinTask",
          position: {
            x: currentX + 20 + col * 235,
            y: 68 + row * 94,
          },
          style: { zIndex: 2 },
          data: {
            ...item,
            selected: selectedItem?.id === item.id,
          },
        });

        item.dependsOn.forEach((depId) => {
          const isCompleted = item.status === "completed";
          const isRunning = item.status === "in_progress";
          edges.push({
            id: `e-${depId}-${item.id}`,
            source: depId,
            target: item.id,
            animated: isRunning,
            style: {
              stroke: isCompleted ? "#52c41a" : isRunning ? "#fa8c16" : "#8c8c8c",
              strokeWidth: 1.8,
              strokeDasharray: item.status === "pending" ? "5 4" : undefined,
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isCompleted ? "#52c41a" : isRunning ? "#fa8c16" : "#8c8c8c",
            },
          });
        });
      });

      currentX += groupWidth + 36;
    });

    return { flowNodes: nodes, flowEdges: edges };
  }, [phases, selectedItem?.id]);

  const hasReadyTasks = useMemo(
    () => (tasks || []).some((t: any) => t.state === "ready" || t.state === "stale"),
    [tasks],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 48px)", background: "#f0f2f5" }}>
      {/* Top Workstation Header Bar */}
      <div
        style={{
          height: 52,
          background: "#fff",
          borderBottom: "1px solid #e8e8e8",
          padding: "0 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <Space size={12}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            HexaGraph Workstation
          </Typography.Title>
          <Tag color="blue">INFRA Core Platform</Tag>
          <Tag color="geekblue">test3-sdd-graph-engine (active)</Tag>
          {Array.isArray(runsList) && runsList.length > 0 && (
            <Select
              size="small"
              style={{ width: 240 }}
              value={activeRunId}
              placeholder="选择历史运行 Run"
              onChange={(val) => nav(`/workstation/${val}`)}
              options={runsList.map((r: any) => ({
                value: r.id,
                label: `Run ${r.id.slice(0, 8)} · Stage ${r.stage} (${r.status})`,
              }))}
            />
          )}
        </Space>

        <Space size={10}>
          {run && (
            <>
              <Tag color={run.status === "done" ? "success" : run.paused ? "warning" : "processing"}>
                Stage: {run.stage} | Status: {run.status} {run.paused ? "(Paused)" : ""}
              </Tag>
              <Tag>
                Tokens: {budget?.used ?? 0} / {budget?.limit ?? 0}
              </Tag>
              <Tooltip title="自动批准当前挂起关卡以快速推进">
                <Button
                  size="small"
                  type={autoAdvance ? "primary" : "default"}
                  icon={<StepForwardOutlined />}
                  onClick={() => setAutoAdvance((v) => !v)}
                >
                  {autoAdvance ? "自动过关: 开" : "自动过关: 关"}
                </Button>
              </Tooltip>
              {run.stage === "7" && (
                <Button
                  size="small"
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={scheduleMut.isPending}
                  onClick={() => scheduleMut.mutate()}
                >
                  调度执行编排器 (Schedule)
                </Button>
              )}
              {run.stage === "8" && run.status !== "done" && !pendingGate && (
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckCircleFilled />}
                  loading={acceptMut.isPending}
                  onClick={() => acceptMut.mutate()}
                >
                  生成验收报告
                </Button>
              )}
              <Button
                size="small"
                icon={run.paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
                onClick={() => runCtrlMut.mutate(run.paused ? "resume" : "pause")}
              >
                {run.paused ? "恢复运行" : "暂停运行"}
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={refreshAll}>
                刷新
              </Button>
            </>
          )}
        </Space>
      </div>

      {/* Main Split Workspace: Left (Input + Task Progress) | Right (Twin Graph & Execution Interaction) */}
      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "420px 1fr",
          gap: 12,
          padding: 12,
          overflow: "hidden",
        }}
      >
        {/* LEFT PANEL */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            overflowY: "auto",
            paddingRight: 2,
          }}
        >
          {/* 1. Real Input Box to Launch or Drive Run */}
          <Card
            size="small"
            title={
              <Space>
                <RocketOutlined style={{ color: "#1677ff" }} />
                <span>需求/想法输入 (启动或驱动真实 Run)</span>
              </Space>
            }
            styles={{ body: { padding: 12 } }}
          >
            <Space direction="vertical" style={{ width: "100%" }} size={8}>
              <Input
                addonBefore="项目名"
                size="small"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="输入项目名称"
              />
              <Input.TextArea
                rows={2}
                value={ideaInput}
                onChange={(e) => setIdeaInput(e.target.value)}
                placeholder="输入一两句话的产品想法或需求规格..."
              />
              <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                <Button
                  type="primary"
                  size="small"
                  icon={<RocketOutlined />}
                  loading={startRunMut.isPending}
                  onClick={() => startRunMut.mutate({ autoToExec: false })}
                >
                  新建并启动阶段 0
                </Button>
                <Button
                  size="small"
                  type="dashed"
                  icon={<PlayCircleOutlined />}
                  loading={startRunMut.isPending}
                  onClick={() => startRunMut.mutate({ autoToExec: true })}
                >
                  一键推进到任务分解与编排执行
                </Button>
              </Space>
            </Space>
          </Card>

          {/* 2. Active Gate / Human-in-the-loop Action Card */}
          {pendingGate && (
            <Card
              size="small"
              style={{ borderColor: "#fa8c16", background: "#fffbe6" }}
              title={
                <Space>
                  <Badge status="warning" />
                  <Typography.Text strong style={{ color: "#d46b08" }}>
                    待办关卡：{pendingGate.kind}
                  </Typography.Text>
                </Space>
              }
              styles={{ body: { padding: 12 } }}
            >
              <Space direction="vertical" style={{ width: "100%" }} size={8}>
                {pendingGate.kind === "想法补充" && (
                  <Input.TextArea
                    rows={2}
                    placeholder="补充缺失的用户或问题说明..."
                    value={supplementText}
                    onChange={(e) => setSupplementText(e.target.value)}
                  />
                )}
                <Input
                  size="small"
                  placeholder={
                    pendingGate.kind === "验收确认" && !pendingGate.payload?.pass
                      ? "验收未通过，人工批准必须填写理由"
                      : "裁决理由 / 备注（可选）"
                  }
                  value={gateReason}
                  onChange={(e) => setGateReason(e.target.value)}
                />
                <Space>
                  <Button
                    type="primary"
                    size="small"
                    loading={resolveGateMut.isPending}
                    disabled={
                      pendingGate.kind === "验收确认" &&
                      !pendingGate.payload?.pass &&
                      !gateReason.trim()
                    }
                    onClick={() => resolveGateMut.mutate({ decision: "approve" })}
                  >
                    批准并推进下一阶段
                  </Button>
                  <Button
                    danger
                    size="small"
                    loading={resolveGateMut.isPending}
                    onClick={() => resolveGateMut.mutate({ decision: "reject" })}
                  >
                    驳回重写
                  </Button>
                </Space>
              </Space>
            </Card>
          )}

          {hasReadyTasks && !pendingGate && (
            <Alert
              type="info"
              showIcon
              message="存在就绪任务 (Ready)"
              description="编排器后台每 5 秒自动调度，也可点击下方按钮立即触发一轮调度执行。"
              action={
                <Button
                  size="small"
                  type="primary"
                  loading={scheduleMut.isPending}
                  onClick={() => scheduleMut.mutate()}
                >
                  立即调度
                </Button>
              }
            />
          )}

          {/* 3. Task Progress Panel (Teacher Example Style) */}
          <Card
            size="small"
            title={
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>Task Progress</span>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {completedCount} / {allItems.length} tasks
                </Typography.Text>
              </div>
            }
            styles={{ body: { padding: "10px 12px" } }}
            style={{ flex: 1 }}
          >
            <div style={{ marginBottom: 12 }}>
              <Progress percent={overallPercent} status={run?.status === "done" ? "success" : "active"} />
            </div>

            <Collapse
              defaultActiveKey={["phase1", "phase2", "phase3", "phase4"]}
              ghost
              size="small"
              items={phases.map((phase) => {
                const doneCnt = phase.items.filter((i) => i.status === "completed").length;
                const pct = phase.items.length ? Math.round((doneCnt / phase.items.length) * 100) : 0;
                return {
                  key: phase.key,
                  label: (
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                      <Typography.Text strong style={{ fontSize: 13 }}>
                        {phase.title}
                      </Typography.Text>
                      <Tag color={pct === 100 ? "success" : pct > 0 ? "processing" : "default"}>
                        {pct}%
                      </Tag>
                    </div>
                  ),
                  children: (
                    <List
                      size="small"
                      split={false}
                      dataSource={phase.items}
                      renderItem={(item) => {
                        const isSelected = selectedItem?.id === item.id;
                        return (
                          <List.Item
                            onClick={() => setSelectedId(item.id)}
                            style={{
                              padding: "6px 8px",
                              marginBottom: 4,
                              borderRadius: 6,
                              cursor: "pointer",
                              background: isSelected ? "#e6f4ff" : "#fafafa",
                              border: isSelected ? "1px solid #91caff" : "1px solid #f0f0f0",
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "flex-start", gap: 8, width: "100%" }}>
                              <div style={{ marginTop: 2 }}>
                                <StatusIcon status={item.status} />
                              </div>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", gap: 4 }}>
                                  <Typography.Text
                                    strong
                                    style={{ fontSize: 12 }}
                                    ellipsis={{ tooltip: `${item.code}: ${item.title}` }}
                                  >
                                    {item.code} · {item.title}
                                  </Typography.Text>
                                  <Tag
                                    color={STATUS_META[item.status].tagColor}
                                    style={{ margin: 0, fontSize: 10, lineHeight: "16px", padding: "0 4px" }}
                                  >
                                    {item.rawState}
                                  </Tag>
                                </div>
                                {item.subtitle && (
                                  <Typography.Text
                                    type="secondary"
                                    style={{ fontSize: 11, display: "block" }}
                                    ellipsis={{ tooltip: item.subtitle }}
                                  >
                                    {item.subtitle}
                                  </Typography.Text>
                                )}
                              </div>
                            </div>
                          </List.Item>
                        );
                      }}
                    />
                  ),
                };
              })}
            />
          </Card>
        </div>

        {/* RIGHT PANEL: Twin Graph + Task Details + Spec/Design Monitor + Activity */}
        <Card
          size="small"
          styles={{
            body: {
              padding: 0,
              height: "100%",
              display: "flex",
              flexDirection: "column",
            },
          }}
          style={{ height: "100%", overflow: "hidden" }}
        >
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            style={{ padding: "0 16px", flexShrink: 0 }}
            items={[
              {
                key: "graph",
                label: (
                  <Space size={6}>
                    <ApartmentOutlined />
                    <span>Twin Graph (流程与任务图)</span>
                  </Space>
                ),
              },
              {
                key: "details",
                label: (
                  <Space size={6}>
                    <ControlOutlined />
                    <span>Task Details & 执行控制</span>
                  </Space>
                ),
              },
              {
                key: "specs",
                label: (
                  <Space size={6}>
                    <FileTextOutlined />
                    <span>Flow Monitor (设计规格 / 任务分解)</span>
                  </Space>
                ),
              },
              {
                key: "activity",
                label: (
                  <Space size={6}>
                    <HistoryOutlined />
                    <span>Activity ({events.length})</span>
                  </Space>
                ),
              },
            ]}
          />

          <div style={{ flex: 1, position: "relative", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {activeTab === "graph" && (
              <>
                <div style={{ flex: 1, position: "relative" }}>
                  <ReactFlow
                    nodes={flowNodes}
                    edges={flowEdges}
                    nodeTypes={nodeTypes}
                    fitView
                    fitViewOptions={{ padding: 0.15 }}
                    onNodeClick={(_, node) => {
                      if (!node.id.startsWith("group-")) {
                        setSelectedId(node.id);
                      }
                    }}
                  >
                    <Background gap={16} size={1} color="#e5e7eb" />
                    <Controls position="bottom-left" />
                  </ReactFlow>

                  {/* Legend in bottom-right corner matching teacher's Workstation */}
                  <div
                    style={{
                      position: "absolute",
                      right: 16,
                      bottom: 16,
                      background: "rgba(255, 255, 255, 0.94)",
                      border: "1px solid #d9d9d9",
                      borderRadius: 8,
                      padding: "8px 12px",
                      boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
                      fontSize: 12,
                      display: "flex",
                      gap: 14,
                      alignItems: "center",
                      zIndex: 5,
                    }}
                  >
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span
                        style={{
                          width: 12,
                          height: 12,
                          border: "1.5px dashed #1677ff",
                          background: "#e6f4ff",
                          borderRadius: 3,
                          display: "inline-block",
                        }}
                      />
                      Phase
                    </span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ width: 10, height: 10, background: "#52c41a", borderRadius: "50%" }} />
                      Completed
                    </span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ width: 10, height: 10, background: "#fa8c16", borderRadius: "50%" }} />
                      In Progress
                    </span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ width: 10, height: 10, background: "#d9d9d9", borderRadius: "50%" }} />
                      Pending
                    </span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ width: 10, height: 10, background: "#ff4d4f", borderRadius: "50%" }} />
                      Gate / Error
                    </span>
                  </div>
                </div>

                {/* Bottom Interactive Execution Inspector Dock */}
                {selectedItem && (
                  <div
                    style={{
                      borderTop: "1px solid #e8e8e8",
                      background: "#fafafa",
                      padding: "10px 16px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      flexWrap: "wrap",
                    }}
                  >
                    <Space size={10}>
                      <StatusIcon status={selectedItem.status} />
                      <Typography.Text strong>
                        {selectedItem.code}: {selectedItem.title}
                      </Typography.Text>
                      <Tag color={STATUS_META[selectedItem.status].tagColor}>{selectedItem.rawState}</Tag>
                      {selectedItem.subtitle && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {selectedItem.subtitle}
                        </Typography.Text>
                      )}
                    </Space>

                    {selectedItem.kind === "task" && selectedItem.detail?.revision !== undefined ? (
                      <Space size={6} wrap>
                        <Input
                          size="small"
                          placeholder="控制操作理由 (skip/force-pass 必填)"
                          value={controlReason}
                          onChange={(e) => setControlReason(e.target.value)}
                          style={{ width: 210 }}
                        />
                        {(
                          [
                            "pause",
                            "resume",
                            "retry",
                            "skip",
                            "force-pass",
                            "takeover",
                            "submit-takeover",
                          ] as const
                        ).map((action) => (
                          <Button
                            key={action}
                            size="small"
                            disabled={!controlEnabled(action, selectedItem.detail.state)}
                            loading={controlMut.isPending}
                            onClick={() =>
                              controlMut.mutate({
                                code: selectedItem.code,
                                action,
                                revision: selectedItem.detail.revision,
                              })
                            }
                          >
                            {action}
                          </Button>
                        ))}
                        <Button size="small" type="link" onClick={() => setActiveTab("details")}>
                          详情
                        </Button>
                      </Space>
                    ) : (
                      <Button size="small" onClick={() => setActiveTab("specs")}>
                        查看阶段规格与分解产物
                      </Button>
                    )}
                  </div>
                )}
              </>
            )}

            {activeTab === "details" && (
              <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
                {selectedItem ? (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Descriptions bordered size="small" column={2} title={`${selectedItem.code} · ${selectedItem.title}`}>
                      <Descriptions.Item label="节点类型">{selectedItem.kind}</Descriptions.Item>
                      <Descriptions.Item label="当前状态">
                        <Tag color={STATUS_META[selectedItem.status].tagColor}>{selectedItem.rawState}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="所属阶段">{selectedItem.phaseKey}</Descriptions.Item>
                      <Descriptions.Item label="上游依赖">
                        {selectedItem.dependsOn.join(", ") || "无"}
                      </Descriptions.Item>
                      {selectedItem.detail?.card && (
                        <>
                          <Descriptions.Item label="执行角色">{selectedItem.detail.card.role}</Descriptions.Item>
                          <Descriptions.Item label="估算点数">{selectedItem.detail.card.points} pt</Descriptions.Item>
                          <Descriptions.Item label="允许写集 (write_set)" span={2}>
                            {(selectedItem.detail.card.write_set || []).join(", ")}
                          </Descriptions.Item>
                          <Descriptions.Item label="验收命令 (acceptance)" span={2}>
                            {(selectedItem.detail.card.acceptance || [])
                              .map((a: any) => (a.cmd || []).join(" "))
                              .join(" ; ")}
                          </Descriptions.Item>
                        </>
                      )}
                    </Descriptions>

                    {selectedItem.kind === "task" && selectedItem.detail?.revision !== undefined && (
                      <Card size="small" title="编排器任务级交互控制 (Task Execution Control)">
                        <Space wrap>
                          <Input
                            placeholder="输入控制理由（skip / force-pass 必填）"
                            value={controlReason}
                            onChange={(e) => setControlReason(e.target.value)}
                            style={{ width: 280 }}
                          />
                          {["pause", "resume", "retry", "skip", "force-pass", "takeover", "submit-takeover"].map(
                            (action) => (
                              <Button
                                key={action}
                                disabled={!controlEnabled(action, selectedItem.detail.state)}
                                onClick={() =>
                                  controlMut.mutate({
                                    code: selectedItem.code,
                                    action,
                                    revision: selectedItem.detail.revision,
                                  })
                                }
                              >
                                {action}
                              </Button>
                            ),
                          )}
                        </Space>
                        {selectedItem.detail.takeover_workspace && (
                          <div style={{ marginTop: 8 }}>
                            <Tag color="purple">接管工作树: {selectedItem.detail.takeover_workspace}</Tag>
                          </div>
                        )}
                      </Card>
                    )}

                    <Card size="small" title="节点产物 / 证据详情 (Artifact & Evidence)">
                      <pre style={{ maxHeight: 320, overflow: "auto", fontSize: 12, margin: 0 }}>
                        {JSON.stringify(selectedItem.detail || {}, null, 2)}
                      </pre>
                    </Card>
                  </Space>
                ) : (
                  <Empty description="请在左侧或图中选择一个节点" />
                )}
              </div>
            )}

            {activeTab === "specs" && (
              <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
                <Space direction="vertical" style={{ width: "100%" }} size={12}>
                  <Card size="small" title="1. 需求规格 (SPEC Baseline)">
                    <pre style={{ maxHeight: 180, overflow: "auto", fontSize: 12, margin: 0 }}>
                      {JSON.stringify(artifacts?.spec || { note: "尚未生成 SPEC，请先推进前序关卡" }, null, 2)}
                    </pre>
                  </Card>
                  <Card size="small" title="2. 设计规格 (DESIGN Modules & Interfaces)">
                    <pre style={{ maxHeight: 200, overflow: "auto", fontSize: 12, margin: 0 }}>
                      {JSON.stringify(artifacts?.design || { note: "尚未进入阶段 5 设计规格" }, null, 2)}
                    </pre>
                  </Card>
                  <Card size="small" title="3. 开发任务分解 (PLAN TaskGraph)">
                    <pre style={{ maxHeight: 220, overflow: "auto", fontSize: 12, margin: 0 }}>
                      {JSON.stringify(artifacts?.plan || { note: "尚未进入阶段 6 任务分解" }, null, 2)}
                    </pre>
                  </Card>
                </Space>
              </div>
            )}

            {activeTab === "activity" && (
              <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
                <List
                  size="small"
                  bordered
                  dataSource={[...events].reverse()}
                  renderItem={(ev: any) => (
                    <List.Item>
                      <Space>
                        <Tag color="blue">#{ev.seq}</Tag>
                        <Typography.Text code>{ev.kind}</Typography.Text>
                        {ev.subject && <Tag>{ev.subject}</Tag>}
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {JSON.stringify(ev.payload || {})}
                        </Typography.Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
