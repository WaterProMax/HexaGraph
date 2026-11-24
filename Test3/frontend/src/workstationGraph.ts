/**
 * Workstation view model: stage overview, node list and the single "current main graph".
 * Pure functions only, so statuses and edges can be tested without React Flow.
 *
 * Edge rules (no invented dependencies):
 *  - task graph: only `card.depends_on`
 *  - module graph: only the design module's own `depends_on`, limited to modules that exist
 *  - stages never fan in to modules or tasks; PLAN has no node in the main graph
 */

/** "awaiting" is a human gate that is simply waiting; "error" is a failure that needs handling. */
export type ItemStatus = "completed" | "in_progress" | "awaiting" | "pending" | "error" | "skipped";

export interface PhaseTaskItem {
  id: string;
  code: string;
  title: string;
  subtitle?: string;
  status: ItemStatus;
  rawState?: string;
  phaseKey: string;
  dependsOn: string[];
  kind: "stage" | "spec" | "design" | "package" | "task";
  parent?: string;
  detail?: any;
}

export interface PhaseDef {
  key: string;
  no: string;
  title: string;
  items: PhaseTaskItem[];
}

export const DESIGN_IMPORT_STOPPED = ["needs_input", "needs_split", "failed"];

export function mapTaskState(state: string): ItemStatus {
  if (state === "done") return "completed";
  if (state === "skipped" || state === "cancelled") return "skipped";
  if (["running", "verifying", "ready"].includes(state)) return "in_progress";
  if (["failed", "needs_human", "blocked", "stale"].includes(state)) return "error";
  return "pending";
}

export interface WorkstationInput {
  run: any;
  artifacts: any;
  tasks: any;
  pendingGate: any;
  isDesignRun: boolean;
}

function stageNumber(run: any): number {
  const stageStr = String(run?.stage ?? "0");
  return stageStr === "done" ? 9 : stageStr === "stopped" ? -1 : Number(stageStr);
}

function rollupStatus(items: PhaseTaskItem[]): ItemStatus {
  if (items.length === 0) return "pending";
  if (items.every((item) => item.status === "completed" || item.status === "skipped")) return "completed";
  if (items.some((item) => item.status === "error")) return "error";
  if (items.some((item) => item.status !== "pending")) return "in_progress";
  return "pending";
}

export function buildWorkstationItems({ run, artifacts, tasks, pendingGate, isDesignRun }: WorkstationInput): {
  phases: PhaseDef[];
  allItems: PhaseTaskItem[];
  workPackages: PhaseTaskItem[];
} {
  const stageNum = stageNumber(run);
  const hasSpec = Boolean(artifacts?.spec);
  const hasDesign = Boolean(artifacts?.design);
  const hasPlan = Boolean(artifacts?.plan);
  const skipDiscussion = Boolean(isDesignRun || artifacts?.design_input);
  const designImportStatus = artifacts?.design_input_status;
  const designImportStopped = Boolean(isDesignRun && DESIGN_IMPORT_STOPPED.includes(designImportStatus));
  const gateKind: string | undefined = pendingGate?.kind;

  const p1Items: PhaseTaskItem[] = [
    {
      id: "S-IDEA",
      code: "STAGE-0",
      title: "想法解析与初步做法",
      subtitle: skipDiscussion ? "设计规格入口跳过讨论" : artifacts?.idea_card?.approach || "idea_checker / pm_draft",
      status: !run
        ? "pending"
        : skipDiscussion
          ? "skipped"
          : stageNum >= 1
            ? "completed"
            : pendingGate
              ? "awaiting"
              : "in_progress",
      rawState: skipDiscussion ? "不适用" : stageNum >= 1 ? "confirmed" : gateKind || "stage-0",
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
                ? "awaiting"
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
        : designImportStopped
          ? "error"
          : stageNum >= 5 && hasSpec
            ? "completed"
            : hasSpec
              ? gateKind === "SPEC基线确认"
                ? "awaiting"
                : "in_progress"
              : "pending",
      rawState: designImportStopped
        ? designImportStatus
        : artifacts?.baseline_SPEC
          ? `v${artifacts.baseline_SPEC}`
          : hasSpec
            ? "await_gate"
            : "pending",
      phaseKey: "phase1",
      dependsOn: skipDiscussion ? [] : ["S-DISC"],
      kind: "spec",
      detail: artifacts?.spec,
    },
  ];

  const designModules: any[] = artifacts?.design?.modules || [];
  const designAwaiting = gateKind === "DESIGN基线确认";
  const p2Items: PhaseTaskItem[] = [
    {
      id: "S-DESIGN",
      code: "DESIGN",
      title: "架构与设计规格",
      subtitle: designImportStopped
        ? "导入未完成，未形成待确认设计"
        : hasDesign
          ? `模块 ${designModules.length} 个 · 接口 ${(artifacts?.design?.interfaces || []).length} 个`
          : "architect + 双评审背靠背打分",
      status: !run
        ? "pending"
        : designImportStopped
          ? "error"
          : stageNum >= 6
            ? "completed"
            : stageNum === 5 || hasDesign
              ? designAwaiting
                ? "awaiting"
                : "in_progress"
              : "pending",
      rawState: designImportStopped
        ? designImportStatus
        : artifacts?.baseline_DESIGN
          ? `v${artifacts.baseline_DESIGN}`
          : hasDesign
            ? "await_gate"
            : "pending",
      phaseKey: "phase2",
      dependsOn: ["S-SPEC"],
      kind: "design",
      detail: artifacts?.design,
    },
    ...designModules.map((m: any): PhaseTaskItem => ({
      id: `MOD-${m.code}`,
      code: m.code,
      title: m.name,
      subtitle: m.responsibility || `追溯 ${(m.sources || []).join(", ") || "-"}`,
      status: designImportStopped ? "error" : stageNum >= 6 ? "completed" : designAwaiting ? "awaiting" : "in_progress",
      rawState: designImportStopped ? designImportStatus : stageNum >= 6 ? "frozen" : "draft",
      phaseKey: "phase2",
      // Membership only: modules belong to DESIGN. Module-to-module edges come from `detail.depends_on`.
      dependsOn: ["S-DESIGN"],
      kind: "design",
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
        : "尚未生成 PLAN",
      status: !run
        ? "pending"
        : stageNum >= 7
          ? "completed"
          : stageNum === 6 || hasPlan
            ? gateKind === "PLAN基线确认"
              ? "awaiting"
              : "in_progress"
            : "pending",
      rawState: artifacts?.baseline_PLAN ? `v${artifacts.baseline_PLAN}` : hasPlan ? "await_gate" : "pending",
      phaseKey: "phase3",
      dependsOn: ["S-DESIGN"],
      kind: "stage",
      detail: artifacts?.plan,
    },
  ];

  const taskSourceList =
    runtimeTaskList.length > 0
      ? runtimeTaskList
      : planTasks.map((card: any) => ({ code: card.code, state: "pending", revision: 1, card }));

  const p4Items: PhaseTaskItem[] = taskSourceList.map((t: any) => {
    const card = t.card || {};
    return {
      id: t.code,
      code: t.code,
      parent: card.parent || "",
      title: card.title || t.code,
      subtitle: `${card.role || "coder"} · ${card.kind || "impl"} · ${card.module || "M1"} · ${card.points || 1}pt`,
      status: mapTaskState(t.state),
      rawState: t.state,
      phaseKey: "phase4",
      // Real task DAG only. A root task has no upstream; it is not "waiting on PLAN".
      dependsOn: Array.isArray(card.depends_on) ? card.depends_on : [],
      kind: "task" as const,
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
        : gateKind === "验收确认"
          ? "待人工确认验收关卡"
          : "就绪，可触发验收",
      status: run?.status === "done" ? "completed" : gateKind === "验收确认" ? "awaiting" : "in_progress",
      rawState: run?.status === "done" ? "done" : "stage-8",
      phaseKey: "phase4",
      dependsOn: taskSourceList.map((t: any) => t.code),
      kind: "stage",
      detail: artifacts?.acceptance,
    });
  }

  const planPackages = Array.isArray(artifacts?.plan?.work_packages) ? artifacts.plan.work_packages : [];
  const leafTasks = p4Items.filter((item) => item.kind === "task");
  const workPackages: PhaseTaskItem[] = planPackages.map((pkg: any) => {
    const children = leafTasks.filter((item) => item.parent === pkg.code);
    const done = children.filter((item) => item.status === "completed" || item.status === "skipped").length;
    return {
      id: pkg.code,
      code: pkg.code,
      title: pkg.title || pkg.code,
      subtitle: `${children.length} 个任务 · ${pkg.module || "M1"}`,
      status: rollupStatus(children),
      rawState: `${done}/${children.length}`,
      phaseKey: "phase4",
      dependsOn: [],
      kind: "package" as const,
      detail: { package: pkg, children: children.map((item) => item.id) },
    };
  });

  const phases: PhaseDef[] = [
    { key: "phase1", no: "Phase 1", title: "想法与需求规格", items: p1Items },
    { key: "phase2", no: "Phase 2", title: "设计规格与模块契约", items: p2Items },
    { key: "phase3", no: "Phase 3", title: "开发任务分解", items: p3Items },
    { key: "phase4", no: "Phase 4", title: "编排执行与验收", items: p4Items },
  ];
  return { phases, allItems: phases.flatMap((p) => p.items), workPackages };
}

// ---------------------------------------------------------------------------------------------
// Stage overview strip

export interface OverviewStage {
  key: string;
  label: string;
  status: ItemStatus;
  rawState?: string;
  /** First stage that is neither completed nor skipped: where the run currently is. */
  current: boolean;
}

export function buildStageOverview(allItems: PhaseTaskItem[], run: any): OverviewStage[] {
  const byId = new Map(allItems.map((item) => [item.id, item]));
  const pick = (id: string, label: string): Omit<OverviewStage, "current"> => {
    const item = byId.get(id);
    return { key: id, label, status: item?.status ?? "pending", rawState: item?.rawState };
  };

  const tasks = allItems.filter((item) => item.kind === "task");
  const counted = tasks.filter((item) => item.status !== "skipped");
  const done = counted.filter((item) => item.status === "completed").length;
  let execStatus: ItemStatus = "pending";
  if (run && tasks.length > 0) {
    if (tasks.some((item) => item.status === "error")) execStatus = "error";
    else if (counted.length === 0 || done === counted.length) execStatus = "completed";
    else if (tasks.some((item) => item.status === "in_progress" || item.status === "completed")) execStatus = "in_progress";
  }

  const stages: Omit<OverviewStage, "current">[] = [
    pick("S-IDEA", "想法"),
    pick("S-DISC", "讨论"),
    pick("S-SPEC", "SPEC"),
    pick("S-DESIGN", "DESIGN"),
    pick("S-PLAN", "PLAN"),
    {
      key: "S-EXEC",
      label: "执行",
      status: execStatus,
      rawState: tasks.length ? `${done}/${counted.length}` : "pending",
    },
    pick("S-ACCEPT", "验收"),
  ];
  const currentIndex = run ? stages.findIndex((s) => s.status !== "completed" && s.status !== "skipped") : -1;
  return stages.map((s, index) => ({ ...s, current: index === currentIndex }));
}

// ---------------------------------------------------------------------------------------------
// Current main graph

export interface GraphEdgeSpec {
  id: string;
  source: string;
  target: string;
}

function transitiveReduction(edges: GraphEdgeSpec[]): GraphEdgeSpec[] {
  const reachable = (from: string, to: string, skip: string): boolean => {
    const seen = new Set<string>();
    const stack = edges
      .filter((edge) => edge.id !== skip && edge.source === from)
      .map((edge) => edge.target);
    while (stack.length) {
      const node = stack.pop()!;
      if (node === to) return true;
      if (seen.has(node)) continue;
      seen.add(node);
      for (const edge of edges) {
        if (edge.id !== skip && edge.source === node) stack.push(edge.target);
      }
    }
    return false;
  };
  return edges.filter((edge) => !reachable(edge.source, edge.target, edge.id));
}

export interface MainGraph {
  kind: "packages" | "tasks" | "modules" | "empty";
  items: PhaseTaskItem[];
  edges: GraphEdgeSpec[];
}

export function buildMainGraph(
  allItems: PhaseTaskItem[],
  workPackages: PhaseTaskItem[] = [],
  openedPackage?: string | null,
): MainGraph {
  const tasks = allItems.filter((item) => item.kind === "task");
  if (workPackages.length > 0) {
    if (openedPackage) {
      const children = tasks.filter((item) => item.parent === openedPackage);
      const known = new Set(children.map((item) => item.id));
      const edges = children.flatMap((item) =>
        item.dependsOn
          .filter((dep) => known.has(dep) && dep !== item.id)
          .map((dep) => ({ id: `e-${dep}-${item.id}`, source: dep, target: item.id })),
      );
      return { kind: "tasks", items: children, edges };
    }
    const parentOf = new Map(tasks.map((item) => [item.id, item.parent || ""]));
    const packageEdges = new Map<string, GraphEdgeSpec>();
    for (const item of tasks) {
      const target = item.parent || "";
      if (!target) continue;
      for (const dep of item.dependsOn) {
        const source = parentOf.get(dep) || "";
        if (!source || source === target) continue;
        const id = `e-${source}-${target}`;
        packageEdges.set(id, { id, source, target });
      }
    }
    const known = new Set(workPackages.map((item) => item.id));
    const direct = [...packageEdges.values()].filter(
      (edge) => known.has(edge.source) && known.has(edge.target),
    );
    return { kind: "packages", items: workPackages, edges: transitiveReduction(direct) };
  }
  if (tasks.length > 0) {
    const known = new Set(tasks.map((item) => item.id));
    const edges = tasks.flatMap((item) =>
      item.dependsOn.filter((dep) => known.has(dep) && dep !== item.id).map((dep) => ({ id: `e-${dep}-${item.id}`, source: dep, target: item.id })),
    );
    return { kind: "tasks", items: tasks, edges };
  }
  const modules = allItems.filter((item) => item.id.startsWith("MOD-"));
  if (modules.length > 0) {
    const known = new Set(modules.map((item) => item.id));
    const edges = modules.flatMap((item) => {
      const declared: unknown = item.detail?.depends_on;
      const deps = Array.isArray(declared) ? declared.map((code) => `MOD-${code}`) : [];
      return deps.filter((dep) => known.has(dep) && dep !== item.id).map((dep) => ({ id: `e-${dep}-${item.id}`, source: dep, target: item.id }));
    });
    return { kind: "modules", items: modules, edges };
  }
  return { kind: "empty", items: [], edges: [] };
}

export interface EmptyGraphNotice {
  tone: "info" | "error";
  title: string;
  detail: string;
}

export function emptyGraphNotice(opts: {
  run: any;
  designImportStatus?: string;
  importing: boolean;
  isDesignRun: boolean;
}): EmptyGraphNotice {
  const { run, designImportStatus, importing, isDesignRun } = opts;
  if (importing) {
    return { tone: "info", title: "正在整理设计规格", detail: "整理完成并通过检查后，这里先显示设计模块。" };
  }
  if (isDesignRun && designImportStatus && DESIGN_IMPORT_STOPPED.includes(designImportStatus)) {
    return {
      tone: "error",
      title: `设计规格未完成：${designImportStatus}`,
      detail: "尚无可展示的设计模块，也未进入任务分解。请在左侧查看缺项或错误，修改原文后重新提交。",
    };
  }
  const stage = run?.stage !== undefined ? `当前阶段 ${run.stage}` : "";
  return {
    tone: "info",
    title: "还没有可展示的图",
    detail: `${stage}${stage ? "。" : ""}生成设计模块后显示模块图，PLAN 确认并建立任务后显示任务依赖图。`,
  };
}

// ---------------------------------------------------------------------------------------------
// One-line status for the info column

export interface StatusLine {
  text: string;
  tone: "idle" | "progress" | "awaiting" | "error" | "done";
}

export function runStatusLine(opts: {
  run: any;
  artifacts: any;
  pendingGate: any;
  importing: boolean;
  queryFailed: boolean;
  allItems: PhaseTaskItem[];
  isDesignRun: boolean;
}): StatusLine {
  const { run, artifacts, pendingGate, importing, queryFailed, allItems, isDesignRun } = opts;
  if (queryFailed) return { text: "状态查询失败，暂不开放暂停、批准或调度", tone: "error" };
  if (!run) return { text: "尚未开始：写下想法或设计规格后启动", tone: "idle" };
  if (importing) return { text: "正在整理设计规格，尚未进入确认", tone: "progress" };
  const importStatus = artifacts?.design_input_status;
  if (isDesignRun && importStatus === "needs_input") return { text: "设计规格缺项，需补充原文后重新提交", tone: "error" };
  if (isDesignRun && importStatus === "needs_split") return { text: "输入需要拆分，需修改原文后重新提交", tone: "error" };
  if (isDesignRun && importStatus === "failed") return { text: "设计规格整理失败，需处理后重新提交", tone: "error" };
  if (run.status === "done") return { text: "运行已完成", tone: "done" };
  if (run.status === "terminated") return { text: "运行已终止", tone: "idle" };
  if (run.status === "stopped") return { text: "运行已停止", tone: "idle" };
  const modelStage = artifacts?.model_stage?.status;
  if (["failed", "timeout", "interrupted", "cancelled"].includes(modelStage || "")) {
    return { text: "模型阶段未成功，未生成可执行计划", tone: "error" };
  }
  if (run.paused) return { text: "运行已暂停", tone: "awaiting" };
  if (pendingGate) return { text: `等待你确认：${pendingGate.kind}`, tone: "awaiting" };
  const failed = allItems.filter((item) => item.kind === "task" && item.status === "error").length;
  if (failed > 0) return { text: `${failed} 个任务需要处理`, tone: "error" };
  if (allItems.some((item) => item.kind === "task" && item.rawState === "ready")) {
    return { text: "有任务已就绪，等待调度", tone: "awaiting" };
  }
  return { text: `阶段 ${run.stage} 进行中`, tone: "progress" };
}
