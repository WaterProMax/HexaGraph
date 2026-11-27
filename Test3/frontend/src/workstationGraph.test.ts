import { describe, expect, it } from "vitest";
import {
  buildMainGraph,
  buildStageOverview,
  buildWorkstationItems,
  emptyGraphNotice,
  runStatusLine,
  type PhaseTaskItem,
} from "./workstationGraph";

const designRun = (over: Record<string, unknown> = {}) => ({
  id: "r1",
  origin: "design_spec",
  status: "waiting",
  stage: "5",
  paused: false,
  gates: [],
  ...over,
});

const modules = [
  { code: "M1", name: "座位查询", sources: ["F1"] },
  { code: "M2", name: "开放时间", sources: ["F2"] },
  { code: "M3", name: "预约", sources: ["F3"], depends_on: ["M1", "M9"] },
];

function build(input: { run?: any; artifacts?: any; tasks?: any; gate?: any; isDesignRun?: boolean }) {
  const run = "run" in input ? input.run : designRun();
  const { phases, allItems, workPackages } = buildWorkstationItems({
    run,
    artifacts: input.artifacts ?? {},
    tasks: input.tasks ?? [],
    pendingGate: input.gate ?? null,
    isDesignRun: input.isDesignRun ?? true,
  });
  return {
    run,
    phases,
    allItems,
    workPackages,
    overview: buildStageOverview(allItems, run),
    graph: buildMainGraph(allItems, workPackages),
  };
}

const item = (items: PhaseTaskItem[], id: string) => items.find((i) => i.id === id)!;

describe("main graph: modules", () => {
  const artifacts = {
    design_input_status: "awaiting_confirmation",
    design_input: { title: "t" },
    spec: { features: [] },
    design: { modules, interfaces: [] },
  };

  it("shows design modules only, with no PLAN node and no stage fan-in", () => {
    const { graph, allItems } = build({ artifacts, gate: { kind: "DESIGN基线确认" } });
    expect(graph.kind).toBe("modules");
    expect(graph.items.map((i) => i.id)).toEqual(["MOD-M1", "MOD-M2", "MOD-M3"]);
    expect(graph.items.some((i) => i.id === "S-PLAN" || i.id === "S-DESIGN")).toBe(false);
    expect(item(allItems, "S-PLAN").dependsOn).toEqual(["S-DESIGN"]);
  });

  it("draws module edges only from the module's own depends_on, limited to existing modules", () => {
    const { graph } = build({ artifacts });
    expect(graph.edges).toEqual([{ id: "e-MOD-M1-MOD-M3", source: "MOD-M1", target: "MOD-M3" }]);
  });

  it("invents no M1→M2 chain when the artifact declares no dependencies", () => {
    const flat = { ...artifacts, design: { modules: modules.map(({ depends_on: _drop, ...m }) => m), interfaces: [] } };
    expect(build({ artifacts: flat }).graph.edges).toEqual([]);
  });

  it("marks modules as waiting on the DESIGN gate, not failed and not completed", () => {
    const { graph } = build({ artifacts, gate: { kind: "DESIGN基线确认" } });
    expect(new Set(graph.items.map((i) => i.status))).toEqual(new Set(["awaiting"]));
  });
});

describe("main graph: tasks", () => {
  const cards = [
    { code: "T-01", title: "骨架", depends_on: [] },
    { code: "T-02", title: "模型", depends_on: ["T-01"] },
    { code: "T-03", title: "接口", depends_on: ["T-01", "T-404"] },
    { code: "T-04", title: "集成", depends_on: ["T-02", "T-03"] },
  ];
  const artifacts = { design_input_status: "plan_confirmed", design: { modules }, plan: { tasks: cards } };
  const tasks = cards.map((card, index) => ({ code: card.code, state: index === 0 ? "done" : "pending", revision: 1, card }));

  it("replaces the module graph by the task DAG once tasks exist", () => {
    const { graph } = build({ run: designRun({ stage: "7" }), artifacts, tasks });
    expect(graph.kind).toBe("tasks");
    expect(graph.items.map((i) => i.id)).toEqual(["T-01", "T-02", "T-03", "T-04"]);
    expect(graph.items.some((i) => i.id.startsWith("MOD-"))).toBe(false);
  });

  it("takes edges only from card.depends_on and ignores unknown targets", () => {
    const { graph } = build({ run: designRun({ stage: "7" }), artifacts, tasks });
    expect(graph.edges.map((e) => `${e.source}>${e.target}`).sort()).toEqual(["T-01>T-02", "T-01>T-03", "T-02>T-04", "T-03>T-04"]);
  });

  it("gives root tasks no fake upstream (not 'waiting on PLAN')", () => {
    const { allItems } = build({ run: designRun({ stage: "7" }), artifacts, tasks });
    expect(item(allItems, "T-01").dependsOn).toEqual([]);
  });

  it("falls back to plan cards (pending) before runtime tasks exist", () => {
    const { graph } = build({ run: designRun({ stage: "6" }), artifacts, tasks: [] });
    expect(graph.kind).toBe("tasks");
    expect(new Set(graph.items.map((i) => i.status))).toEqual(new Set(["pending"]));
  });

  it("keeps acceptance out of the graph and out of the dependency fan-in", () => {
    const { graph, allItems } = build({ run: designRun({ stage: "8" }), artifacts, tasks });
    expect(graph.items.some((i) => i.id === "S-ACCEPT")).toBe(false);
    expect(item(allItems, "S-ACCEPT").kind).toBe("stage");
  });
});

describe("failures and gates are never shown as success", () => {
  it.each(["needs_input", "needs_split", "failed"])("keeps %s as an error on SPEC and DESIGN", (status) => {
    const { allItems, overview, graph } = build({
      run: designRun({ status: "stopped" }),
      artifacts: { design_input_status: status, design_input: {}, design: { modules } },
    });
    expect(item(allItems, "S-SPEC").status).toBe("error");
    expect(item(allItems, "S-DESIGN").status).toBe("error");
    expect(item(allItems, "S-PLAN").status).toBe("pending");
    expect(graph.items.every((i) => i.status === "error")).toBe(true);
    expect(overview.find((s) => s.key === "S-DESIGN")?.status).toBe("error");
    expect(overview.find((s) => s.key === "S-PLAN")?.status).toBe("pending");
    expect(overview.some((s) => s.status === "completed" && ["S-DESIGN", "S-PLAN", "S-EXEC", "S-ACCEPT"].includes(s.key))).toBe(false);
  });

  it("distinguishes a waiting gate (awaiting) from a failure (error)", () => {
    const awaiting = build({
      artifacts: { design_input_status: "awaiting_confirmation", design_input: {}, spec: {}, design: { modules } },
      gate: { kind: "DESIGN基线确认" },
    });
    expect(item(awaiting.allItems, "S-DESIGN").status).toBe("awaiting");
    expect(awaiting.allItems.some((i) => i.status === "error")).toBe(false);
  });

  it("shows failed and blocked tasks as errors and the execution stage as failed", () => {
    const cards = [{ code: "T-01", title: "a", depends_on: [] }, { code: "T-02", title: "b", depends_on: ["T-01"] }];
    const { overview } = build({
      run: designRun({ stage: "7", status: "running" }),
      artifacts: { plan: { tasks: cards }, design_input_status: "plan_confirmed" },
      tasks: [
        { code: "T-01", state: "failed", revision: 1, card: cards[0] },
        { code: "T-02", state: "blocked", revision: 1, card: cards[1] },
      ],
    });
    expect(overview.find((s) => s.key === "S-EXEC")?.status).toBe("error");
  });
});

describe("stage overview", () => {
  it("is pending everywhere before a run exists and has no current stage", () => {
    const { overview } = build({ run: undefined, artifacts: undefined, isDesignRun: false });
    expect(overview.map((s) => s.label)).toEqual(["想法", "讨论", "SPEC", "DESIGN", "PLAN", "执行", "验收"]);
    expect(overview.every((s) => s.status === "pending" && !s.current)).toBe(true);
  });

  it("marks the first unfinished stage as current and skips the discussion for design runs", () => {
    const { overview } = build({
      artifacts: { design_input_status: "awaiting_confirmation", design_input: {}, spec: { features: [] }, design: { modules } },
      gate: { kind: "DESIGN基线确认" },
    });
    expect(overview.find((s) => s.key === "S-IDEA")?.status).toBe("skipped");
    expect(overview.find((s) => s.key === "S-DISC")?.status).toBe("skipped");
    expect(overview.find((s) => s.key === "S-SPEC")?.status).toBe("completed");
    expect(overview.filter((s) => s.current)).toHaveLength(1);
    expect(overview.find((s) => s.current)).toMatchObject({ key: "S-DESIGN", status: "awaiting" });
  });

  it("completes execution only when every non-skipped task is done", () => {
    const cards = [{ code: "T-01", title: "a", depends_on: [] }, { code: "T-02", title: "b", depends_on: [] }];
    const make = (states: string[]) =>
      build({
        run: designRun({ stage: "7", status: "running" }),
        artifacts: { plan: { tasks: cards }, design_input_status: "plan_confirmed" },
        tasks: cards.map((card, i) => ({ code: card.code, state: states[i], revision: 1, card })),
      }).overview.find((s) => s.key === "S-EXEC")!;
    expect(make(["done", "running"]).status).toBe("in_progress");
    expect(make(["done", "skipped"]).status).toBe("completed");
    expect(make(["done", "done"]).rawState).toBe("2/2");
  });
});

describe("empty graph and status line", () => {
  it("explains an empty graph and reports a stopped import as an error", () => {
    expect(emptyGraphNotice({ run: designRun(), importing: false, isDesignRun: true, designImportStatus: "needs_input" }).tone).toBe("error");
    expect(emptyGraphNotice({ run: designRun(), importing: true, isDesignRun: true }).tone).toBe("info");
    const idle = emptyGraphNotice({ run: { stage: "2" }, importing: false, isDesignRun: false });
    expect(idle.tone).toBe("info");
    expect(idle.detail).toContain("阶段 2");
  });

  const status = (over: Record<string, unknown>) => {
    const base = build({ artifacts: {} });
    return runStatusLine({
      run: designRun(),
      artifacts: {},
      pendingGate: null,
      importing: false,
      queryFailed: false,
      allItems: base.allItems,
      isDesignRun: true,
      ...over,
    } as Parameters<typeof runStatusLine>[0]);
  };

  it("never reads as success while input is missing, failed or a gate is waiting", () => {
    expect(status({ artifacts: { design_input_status: "needs_input" } })).toMatchObject({ tone: "error" });
    expect(status({ artifacts: { design_input_status: "failed" } })).toMatchObject({ tone: "error" });
    expect(status({ pendingGate: { kind: "DESIGN基线确认" } })).toMatchObject({ tone: "awaiting" });
    expect(status({ queryFailed: true })).toMatchObject({ tone: "error" });
    expect(status({ importing: true })).toMatchObject({ tone: "progress" });
    expect(status({ run: designRun({ status: "done" }) })).toMatchObject({ tone: "done" });
    expect(status({ run: undefined })).toMatchObject({ tone: "idle" });
  });

  it("lets a failed model stage outrank a pending gate", () => {
    const line = status({ artifacts: { model_stage: { status: "timeout" } }, pendingGate: { kind: "PLAN基线确认" } });
    expect(line.tone).toBe("error");
  });

  it("shows work packages first and opens their leaf subgraph on demand", () => {
    const hierarchical = [
      { code: "T-01", title: "骨架", parent: "W1", depends_on: [] },
      { code: "T-02", title: "模型", parent: "W1", depends_on: ["T-01"] },
      { code: "T-03", title: "接口", parent: "W2", depends_on: ["T-01"] },
      { code: "T-04", title: "集成", parent: "W2", depends_on: ["T-02", "T-03"] },
    ];
    const packages = [
      { code: "W1", title: "基座", module: "M1", summary: "", sources: ["F1"] },
      { code: "W2", title: "业务", module: "M2", summary: "", sources: ["F2"] },
    ];
    const hierarchicalArtifacts = {
      design_input_status: "plan_confirmed",
      design: { modules },
      plan: { tasks: hierarchical, work_packages: packages },
    };
    const { allItems, workPackages } = buildWorkstationItems({
      run: designRun({ stage: "7" }),
      artifacts: hierarchicalArtifacts,
      tasks: [],
      pendingGate: null,
      isDesignRun: false,
    });
    const overview = buildMainGraph(allItems, workPackages);
    expect(overview.kind).toBe("packages");
    expect(overview.items.map((i) => i.id)).toEqual(["W1", "W2"]);
    expect(overview.items[0].subtitle).toContain("2 个任务");
    expect(overview.edges).toEqual([{ id: "e-W1-W2", source: "W1", target: "W2" }]);

    const opened = buildMainGraph(allItems, workPackages, "W1");
    expect(opened.kind).toBe("tasks");
    expect(opened.items.map((i) => i.id)).toEqual(["T-01", "T-02"]);
    expect(opened.edges).toEqual([{ id: "e-T-01-T-02", source: "T-01", target: "T-02" }]);
  });

});
