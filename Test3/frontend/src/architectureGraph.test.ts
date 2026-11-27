import { describe, expect, it } from "vitest";
import { buildArchitectureGraph } from "./architectureGraph";

describe("buildArchitectureGraph", () => {
  it("merges design and interface declarations and assigns tasks only to their modules", () => {
    const graph = buildArchitectureGraph({
      modules: [
        { code: "UI", name: "查询界面", depends_on: ["API", "UNKNOWN", "UI", "API"] },
        { code: "API", name: "座位接口" },
        { code: "STORE", name: "数据库" },
      ],
      interfaces: [
        { code: "C1", provider: "API", consumers: ["UI", "UI"] },
        { code: "C2", provider: "STORE", consumers: ["API"] },
      ],
    }, {
      tasks: [
        { code: "T1", title: "实现查询", module: "API" },
        { code: "T2", title: "未分配", module: "UNKNOWN" },
      ],
    });

    expect(graph.connections.map(({ source, target, interfaces }) => [source, target, interfaces])).toEqual([
      ["UI", "API", ["C1"]],
      ["API", "STORE", ["C2"]],
    ]);
    expect(graph.modules.map(({ tasks }) => tasks.map(({ code }) => code))).toEqual([[], ["T1"], []]);
    expect(graph.modules.map(({ interfaces }) => interfaces.map(({ code }) => code))).toEqual([
      ["C1"], ["C1", "C2"], ["C2"],
    ]);
    expect(graph.taskLinks).toEqual([]);
  });

  it("keeps isolated design modules and leaves an empty design empty", () => {
    expect(buildArchitectureGraph()).toEqual({ modules: [], connections: [], taskLinks: [] });
    const graph = buildArchitectureGraph({ modules: [{ code: "M1", name: "座位服务" }] });
    expect(graph.modules[0]).toMatchObject({ code: "M1", tasks: [], interfaces: [] });
    expect(graph.connections).toEqual([]);
    expect(graph.taskLinks).toEqual([]);
  });

  it("collects cross-module task dependencies, merged per module pair, and keeps task fields", () => {
    const graph = buildArchitectureGraph({
      modules: [
        { code: "M1", name: "界面" },
        { code: "M2", name: "接口" },
        { code: "M3", name: "数据" },
      ],
    }, {
      tasks: [
        { code: "T1", title: "数据实现", module: "M3", points: 2, role: "coder" },
        { code: "T2", title: "数据测试", module: "M3", depends_on: ["T1"] },
        { code: "T3", title: "接通接口", module: "M2", depends_on: ["T1", "T2"] },
        { code: "T4", title: "展示界面", module: "M1", depends_on: ["T3", "T3", "UNKNOWN"] },
      ],
    });

    expect(graph.taskLinks).toEqual([
      { id: `t:${JSON.stringify(["M2", "M3"])}`, source: "M2", target: "M3", pairs: [{ task: "T3", dep: "T1" }, { task: "T3", dep: "T2" }] },
      { id: `t:${JSON.stringify(["M1", "M2"])}`, source: "M1", target: "M2", pairs: [{ task: "T4", dep: "T3" }] },
    ]);
    expect(graph.modules[2].tasks[0]).toMatchObject({ code: "T1", points: 2, role: "coder" });
  });
});
