import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskDependencyGraph } from "./TaskDependencyGraph";

/**
 * React Flow is mocked for jsdom, but the graph's own contract — the accessible
 * dependency text, click selection and empty state — is produced by this
 * component, not by the library. Node cards render through the real nodeTypes
 * so node-level markup (e.g. the A2 assignee badge) is covered too.
 */
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    children,
    nodes = [],
    edges = [],
    nodesDraggable,
    nodesConnectable,
    onNodeClick,
    ariaLabel,
    onNodesChange,
    nodeTypes = {},
  }: {
    children?: ReactNode;
    nodes?: Array<{ id: string; type?: string; data?: any; selected?: boolean }>;
    edges?: Array<{ id: string; source: string; target: string }>;
    nodesDraggable?: boolean;
    nodesConnectable?: boolean;
    onNodeClick?: (event: unknown, node: any) => void;
    onNodesChange?: (changes: any[]) => void;
    ariaLabel?: string;
    nodeTypes?: Record<string, (props: { data: any }) => ReactNode>;
  }) => (
    <div
      data-testid="flow"
      data-draggable={String(nodesDraggable)}
      data-connectable={String(nodesConnectable)}
      aria-label={ariaLabel}
    >
      {nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          data-testid="flow-node"
          data-node-id={node.id}
          data-selected={String(Boolean(node.data?.selected))}
          onClick={() => onNodeClick?.(null, node)}
        >
          {node.type && nodeTypes[node.type]
            ? createElement(nodeTypes[node.type], { data: node.data })
            : node.data?.code}
        </button>
      ))}
      {edges.map((edge) => (
        <div key={edge.id} data-testid="flow-edge" data-source={edge.source} data-target={edge.target} />
      ))}
      <button
        type="button"
        data-testid="flow-select-keyboard"
        onClick={() => onNodesChange?.([{ type: "select", id: "T-02", selected: true }])}
      />
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

const task = {
  id: "T-01",
  code: "T-01",
  title: "实现登录",
  status: "pending" as const,
  rawState: "pending",
};

const dependentTask = {
  id: "T-02",
  code: "T-02",
  title: "接通验收",
  status: "in_progress" as const,
  rawState: "running",
  dependsOn: ["T-01"],
};

afterEach(() => {
  cleanup();
});

describe("TaskDependencyGraph", () => {
  it("renders an accessible sentence for every dependency edge", () => {
    render(<TaskDependencyGraph tasks={[task, dependentTask]} />);
    expect(screen.getByText("T-02 依赖 T-01")).toBeTruthy();
    expect(screen.getByTestId("task-dependency-edges").getAttribute("aria-label")).toBe("任务依赖关系");
    const edge = screen.getByTestId("flow-edge");
    expect(edge.getAttribute("data-source")).toBe("T-01");
    expect(edge.getAttribute("data-target")).toBe("T-02");
    // Pan/zoom stays available, node dragging/connecting stays disabled.
    const flow = screen.getByTestId("flow");
    expect(flow.getAttribute("data-draggable")).toBe("false");
    expect(flow.getAttribute("data-connectable")).toBe("false");
  });

  it("calls onSelect with the clicked node id and highlights the selected node", () => {
    const onSelect = vi.fn();
    const view = render(<TaskDependencyGraph tasks={[task, dependentTask]} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId("flow-node")[1]);
    expect(onSelect).toHaveBeenCalledWith("T-02");

    view.rerender(<TaskDependencyGraph tasks={[task, dependentTask]} selected="T-01" onSelect={onSelect} />);
    const nodes = screen.getAllByTestId("flow-node");
    expect(nodes[0].getAttribute("data-selected")).toBe("true");
    expect(nodes[1].getAttribute("data-selected")).toBe("false");
  });

  it("selects a node from a keyboard select change", () => {
    const onSelect = vi.fn();
    render(<TaskDependencyGraph tasks={[task, dependentTask]} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("flow-select-keyboard"));
    expect(onSelect).toHaveBeenCalledWith("T-02");
  });

  it("shows a Chinese empty state when no task is listed", () => {
    render(<TaskDependencyGraph tasks={[]} />);
    expect(screen.queryByTestId("task-dependency-edges")).toBeNull();
    expect(screen.getByTestId("task-dependency-empty").textContent).toContain("还没有任务依赖图");
  });

  it("states that a dense graph overflows the canvas instead of looking broken", () => {
    const many = Array.from({ length: 151 }, (_, index) => ({
      id: `T-${index}`,
      code: `T-${index}`,
      title: `任务 ${index}`,
      status: "pending" as const,
      rawState: "pending",
    }));
    render(<TaskDependencyGraph tasks={many} selected="T-0" />);
    expect(screen.getByTestId("task-dependency-hint").textContent).toContain("151 个任务");
    expect(screen.getByTestId("task-dependency-hint").textContent).toContain("已定位到当前任务");
  });

  it("does not show the overflow hint for a small graph", () => {
    render(<TaskDependencyGraph tasks={[task, dependentTask]} />);
    expect(screen.queryByTestId("task-dependency-hint")).toBeNull();
  });

  it("ignores dependencies whose endpoint is not part of the graph", () => {
    render(<TaskDependencyGraph tasks={[task, { ...dependentTask, dependsOn: ["T-01", "T-99"] }]} />);
    expect(screen.queryByText("T-02 依赖 T-99")).toBeNull();
    expect(screen.getByText("T-02 依赖 T-01")).toBeTruthy();
  });

  it("shows a read-only assignee badge when the caller provides assignment data (A2)", () => {
    render(
      <TaskDependencyGraph
        tasks={[
          { ...task, assignee: "Member A" },
          { ...dependentTask, assignee: null },
        ]}
      />,
    );
    expect(screen.getByTestId("graph-assignee-T-01").textContent).toContain("Member A");
    expect(screen.getByTestId("graph-assignee-T-02").textContent).toContain("未派发");
  });

  it("renders no assignee badge when assignment data is not supplied (Workstation stays unchanged)", () => {
    render(<TaskDependencyGraph tasks={[task, dependentTask]} />);
    expect(screen.queryByTestId("graph-assignee-T-01")).toBeNull();
    expect(screen.queryByTestId("graph-assignee-T-02")).toBeNull();
  });
});