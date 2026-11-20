import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  if (typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }),
    });
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("retired entries", () => {
  it("keeps only the surviving sidebar entries", async () => {
    renderAt("/workstation/static-classroom");
    expect(await screen.findByRole("link", { name: "新建 Bot" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "创建项目" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "模型槽位" })).toBeNull();
    expect(screen.queryByRole("link", { name: "工作台" })).toBeNull();
    expect(screen.queryByRole("link", { name: "静态课堂演示" })).toBeNull();
    expect(screen.queryByRole("link", { name: "DeepSeek" })).toBeNull();
  });

  it("explains the retired static classroom URL instead of rendering a demo", () => {
    renderAt("/workstation/static-classroom");
    const page = screen.getByTestId("retired-feature");
    expect(page.getAttribute("data-feature")).toBe("static-classroom");
    expect(page.textContent).toContain("静态课堂演示已下线");
    expect(page.textContent).toContain("已下线，只读，不支持继续调用");
  });

  it.each(["/deepseek", "/deepseek/any-run-id"])("explains the retired DeepSeek URL %s", (path) => {
    renderAt(path);
    const page = screen.getByTestId("retired-feature");
    expect(page.getAttribute("data-feature")).toBe("deepseek");
    expect(page.textContent).toContain("DeepSeek 专用入口已下线");
    expect(page.textContent).toContain("未发起任何请求");
  });

  it("does not auto-open a retired run on the main workbench", async () => {
    renderAt("/workstation");
    expect(await screen.findByLabelText("产品想法")).toBeTruthy();
    expect(screen.queryByTestId("retired-run-notice")).toBeNull();
  });
});
