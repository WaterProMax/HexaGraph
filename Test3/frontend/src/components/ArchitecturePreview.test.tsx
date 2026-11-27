import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ArchitecturePreview from "./ArchitecturePreview";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    children,
    nodes = [],
    edges = [],
    nodeTypes = {},
    onNodeClick,
    onNodeMouseEnter,
    onNodeMouseLeave,
  }: {
    children?: ReactNode;
    nodes?: Array<{ id: string; type?: string; data?: any; selected?: boolean }>;
    edges?: Array<{ id: string; source: string; target: string; type?: string; label?: unknown; style?: { strokeDasharray?: string } }>;
    nodeTypes?: Record<string, (props: any) => ReactNode>;
    onNodeClick?: (event: unknown, node: any) => void;
    onNodeMouseEnter?: (event: unknown, node: any) => void;
    onNodeMouseLeave?: (event: unknown, node: any) => void;
  }) => (
    <div data-testid="flow">
      {nodes.map((node) => {
        const Component = node.type ? nodeTypes[node.type] : undefined;
        return (
          <div
            key={node.id}
            data-testid="flow-node"
            data-node-id={node.id}
            onClick={() => onNodeClick?.(null, node)}
            onMouseEnter={() => onNodeMouseEnter?.(null, node)}
            onMouseLeave={() => onNodeMouseLeave?.(null, node)}
          >
            {Component ? <Component data={node.data} selected={node.selected} /> : null}
          </div>
        );
      })}
      {edges.map((edge) => (
        <div
          key={edge.id}
          data-testid="flow-edge"
          data-source={edge.source}
          data-target={edge.target}
          data-dashed={String(Boolean(edge.style?.strokeDasharray))}
        >
          {String(edge.label ?? "")}
        </div>
      ))}
      {children}
    </div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Left: "left", Right: "right" },
  useReactFlow: () => ({ fitView: vi.fn(), setViewport: vi.fn() }),
}));

const design = {
  modules: [
    { code: "M1", name: "座位查询界面", responsibility: "展示楼层余位", depends_on: ["M2"] },
    { code: "M2", name: "查询与上报 API", responsibility: "校验请求", depends_on: ["M3"] },
    { code: "M3", name: "座位数据服务", responsibility: "记录座位数" },
  ],
  interfaces: [
    { code: "C1", provider: "M2", consumers: ["M1"] },
    { code: "C2", provider: "M3", consumers: ["M2"] },
  ],
};

const plan = {
  tasks: [
    { code: "T1", title: "实现座位查询和上报", module: "M3", points: 2, role: "coder" },
    { code: "T2", title: "验证查询与上报限频", module: "M3", depends_on: ["T1"], points: 2, role: "tester" },
    { code: "T3", title: "接通查询和上报接口", module: "M2", depends_on: ["T1"], points: 2, role: "coder" },
    { code: "T4", title: "展示楼层余位和上报表单", module: "M1", depends_on: ["T3"], points: 2, role: "coder" },
  ],
};

function nodeByCode(code: string): HTMLElement {
  const node = screen.getAllByTestId("flow-node").find((el) => el.dataset.nodeId === code);
  if (!node) throw new Error(`flow node ${code} not found`);
  return node;
}

afterEach(cleanup);

describe("ArchitecturePreview", () => {
  it("embeds each module's tasks inside its node, with intra-module dependencies", () => {
    render(<ArchitecturePreview design={design} plan={plan} onSelectTask={vi.fn()} />);

    expect(screen.getAllByTestId("flow-node")).toHaveLength(3);
    const m2 = nodeByCode("M2");
    expect(within(m2).getByText("T3")).toBeTruthy();
    expect(within(m2).getByText("接通查询和上报接口")).toBeTruthy();
    const m3 = nodeByCode("M3");
    expect(within(m3).getByText("T2")).toBeTruthy();
    expect(within(m3).getByText("←T1")).toBeTruthy();
  });

  it("merges same-direction task deps into the module edge and labels only the selected module's edges", () => {
    render(<ArchitecturePreview design={design} plan={plan} onSelectTask={vi.fn()} />);

    const edges = screen.getAllByTestId("flow-edge");
    const edgeText = (source: string, target: string) =>
      edges.find((edge) => edge.dataset.source === source && edge.dataset.target === target)?.textContent ?? "";
    // 同向任务依赖并入模块边：只剩 2 条实线，无虚线。
    expect(edges).toHaveLength(2);
    expect(edges.every((edge) => edge.dataset.dashed === "false")).toBe(true);
    expect(screen.getByText("3 个模块 · 2 条依赖 · 2 条任务依赖")).toBeTruthy();
    // 默认无选中：只画干净直线，不标字。
    expect(edges.every((edge) => edge.textContent === "")).toBe(true);

    fireEvent.click(within(nodeByCode("M1")).getByText("座位查询界面"));
    expect(edgeText("M1", "M2")).toBe("C1 · T4←T3"); // 契约 + 任务号合并标签
    expect(edgeText("M2", "M3")).toBe(""); // M2→M3 不相连

    fireEvent.click(within(nodeByCode("M3")).getByText("座位数据服务"));
    expect(edgeText("M2", "M3")).toBe("C2 · T3←T1");
    expect(edgeText("M1", "M2")).toBe("");
  });

  it("selects a task when its row inside a module card is clicked", () => {
    const onSelectTask = vi.fn();
    render(<ArchitecturePreview design={design} plan={plan} onSelectTask={onSelectTask} />);
    fireEvent.click(within(nodeByCode("M2")).getByRole("button", { name: /接通查询和上报接口/ }));
    expect(onSelectTask).toHaveBeenCalledWith("T3");
  });

  it("starts as a pure diagram and opens the floating detail on module click", () => {
    render(<ArchitecturePreview design={design} plan={plan} onSelectTask={vi.fn()} />);

    // 默认只展示整张图：没有详情卡，只有图例。
    expect(screen.queryByRole("complementary", { name: "模块详情" })).toBeNull();
    expect(screen.getByTestId("architecture-legend")).toBeTruthy();

    fireEvent.click(within(nodeByCode("M1")).getByText("座位查询界面"));
    const detail = screen.getByRole("complementary", { name: "模块详情" });
    // M1's only task depends on M2's T3.
    expect(within(detail).getByText("T4←T3")).toBeTruthy();
    expect(within(detail).getByText("依赖 查询与上报 API")).toBeTruthy();
    const chip = within(detail).getByRole("button", { name: /展示楼层余位和上报表单/ });
    expect(within(chip).getByText(/2pt · coder · 依赖 T3/)).toBeTruthy();
    // Interface contracts stay on the detail pane.
    expect(within(detail).getByText("C1", { exact: true })).toBeTruthy();

    fireEvent.click(within(detail).getByRole("button", { name: "关闭模块详情" }));
    expect(screen.queryByRole("complementary", { name: "模块详情" })).toBeNull();
  });

  it("marks task rows with runtime states when the run is scheduled", () => {
    render(
      <ArchitecturePreview
        design={design}
        plan={plan}
        runtimeTasks={[
          { code: "T1", state: "done" },
          { code: "T2", state: "running" },
        ]}
        onSelectTask={vi.fn()}
      />,
    );
    expect(nodeByCode("M3").querySelector(".arch-task .dot.completed")).toBeTruthy();
    expect(nodeByCode("M3").querySelector(".arch-task .dot.in_progress")).toBeTruthy();
  });

  it("keeps the empty state when the design has no modules", () => {
    render(<ArchitecturePreview design={{ modules: [] }} onSelectTask={vi.fn()} />);
    expect(screen.getByTestId("architecture-empty")).toBeTruthy();
  });
});
