import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../api/client";
import { STATIC_PROJECT_ID, STATIC_RUN_ID } from "../../static/staticProject";
import ProjectWorkstationPage from "./ProjectWorkstationPage";

/**
 * 静态演示项目集成测试：页面必须完全靠快照渲染（拆分 tabs、只读），
 * 任何对静态 run/project 的请求都不允许落到 fetch。
 */
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    children,
    nodes = [],
    edges = [],
    onNodeClick,
    nodeTypes = {},
  }: {
    children?: ReactNode;
    nodes?: Array<{ id: string; type?: string; data?: any }>;
    edges?: Array<{ id: string; source: string; target: string }>;
    onNodeClick?: (event: unknown, node: any) => void;
    nodeTypes?: Record<string, (props: { data: any }) => ReactNode>;
  }) => (
    <div data-testid="flow">
      {nodes.map((node) => (
        <button
          type="button"
          key={node.id}
          data-testid="flow-node"
          data-node-id={node.id}
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

const fetchCalls: string[] = [];

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  window.localStorage.clear();
  fetchCalls.length = 0;
  class FakeEventSource {
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor(public url: string) {}
  }
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      fetchCalls.push(url);
      // Only the live list endpoints may be fetched; they return empty lists
      // and the client augments them with the static entries.
      if (url === "/api/projects" || url === "/api/projects?include_archived=true") {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/runs") {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`static project must not fetch: ${url}`);
    }),
  );
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("static demo project page", () => {
  it("renders the split task tabs from the snapshot without touching static endpoints", async () => {
    render(
      <MemoryRouter>
        <ProjectWorkstationPage projectId={STATIC_PROJECT_ID} />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("panel-details")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("小红书项目搭建（静态）");
    // No discussion/tasks switch and no retired classroom grid on the static project.
    expect(screen.queryByRole("button", { name: "项目讨论" })).toBeNull();
    expect(screen.queryByRole("button", { name: "开发任务" })).toBeNull();
    expect(screen.queryByTestId("demo-workbench")).toBeNull();
    expect(screen.queryByTestId("disc-stage-bar")).toBeNull();
    // Snapshot task codes are prefixed and selectable.
    expect(await screen.findByRole("option", { name: /SW1-01/ })).toBeTruthy();
    expect(screen.getByTestId("context-leader").textContent).toContain("Water");
    // No request for static entities ever reached fetch.
    expect(fetchCalls.some((url) => url.includes("st-"))).toBe(false);
  });

  it("shows the frozen monitor with a static connection badge", async () => {
    render(
      <MemoryRouter>
        <ProjectWorkstationPage projectId={STATIC_PROJECT_ID} />
      </MemoryRouter>,
    );
    await screen.findByTestId("panel-details");
    fireEvent.click(screen.getByTestId("tab-monitor"));
    expect(await screen.findByTestId("run-monitor")).toBeTruthy();
    expect(await screen.findByText("静态快照")).toBeTruthy();
    expect(fetchCalls.some((url) => url.includes("st-"))).toBe(false);
  });

  it("rejects writes to the static run with a read-only error", async () => {
    await expect(
      api.assignTask(STATIC_RUN_ID, "SW1-01", { assignee_bot_id: null, expected_revision: 0 }, "st-bot"),
    ).rejects.toMatchObject({ status: 409, category: "static_read_only" });
    await expect(api.scheduleRun(STATIC_RUN_ID)).rejects.toBeInstanceOf(ApiError);
    await expect(api.control("SW1-01", "pause", 1, "test")).rejects.toMatchObject({
      category: "static_read_only",
    });
    expect(fetchCalls).toHaveLength(0);
  });
});
