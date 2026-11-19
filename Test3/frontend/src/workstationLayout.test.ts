import { describe, expect, it } from "vitest";
import {
  CANVAS_MIN,
  DEFAULT_LAYOUT,
  LAYOUT_STORAGE_KEY,
  LEFT_DEFAULT,
  LEFT_MAX,
  LEFT_MIN,
  SPLITTER_WIDTH,
  loadLayout,
  maxLeftFor,
  resolveLayout,
  saveLayout,
} from "./workstationLayout";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    data,
  };
}

describe("workstation layout persistence", () => {
  it("uses its own key and never writes the retired static classroom key", () => {
    expect(LAYOUT_STORAGE_KEY).toBe("hexagraph.workstation.layout.v1");
    expect(LAYOUT_STORAGE_KEY).not.toBe("hexagraph.static-classroom-demo.v1");
    const storage = memoryStorage({ "hexagraph.static-classroom-demo.v1": "{\"keep\":true}" });
    saveLayout(storage, { width: 400, collapsed: true, drawerOpen: false });
    expect(storage.data.get("hexagraph.static-classroom-demo.v1")).toBe("{\"keep\":true}");
    expect(JSON.parse(storage.data.get(LAYOUT_STORAGE_KEY)!)).toEqual({ width: 400, collapsed: true, drawerOpen: false });
  });

  it("restores a saved layout and falls back to defaults for missing or corrupt data", () => {
    const storage = memoryStorage();
    expect(loadLayout(storage)).toEqual(DEFAULT_LAYOUT);
    saveLayout(storage, { width: 444, collapsed: false, drawerOpen: true });
    expect(loadLayout(storage)).toEqual({ width: 444, collapsed: false, drawerOpen: true });
    expect(loadLayout(memoryStorage({ [LAYOUT_STORAGE_KEY]: "{not json" }))).toEqual(DEFAULT_LAYOUT);
    expect(loadLayout(memoryStorage({ [LAYOUT_STORAGE_KEY]: "null" }))).toEqual(DEFAULT_LAYOUT);
    expect(loadLayout(null)).toEqual(DEFAULT_LAYOUT);
  });

  it("clamps a stored width into 280–560", () => {
    expect(loadLayout(memoryStorage({ [LAYOUT_STORAGE_KEY]: JSON.stringify({ width: 9999 }) })).width).toBe(LEFT_MAX);
    expect(loadLayout(memoryStorage({ [LAYOUT_STORAGE_KEY]: JSON.stringify({ width: 10 }) })).width).toBe(LEFT_MIN);
    expect(loadLayout(memoryStorage({ [LAYOUT_STORAGE_KEY]: JSON.stringify({ width: "wide" }) })).width).toBe(LEFT_DEFAULT);
  });

  it("does not throw when storage rejects writes", () => {
    expect(() =>
      saveLayout({ setItem: () => { throw new Error("quota"); } }, DEFAULT_LAYOUT),
    ).not.toThrow();
  });
});

describe("resolveLayout", () => {
  it("defaults to a 320px docked info column", () => {
    expect(LEFT_DEFAULT).toBe(320);
    expect(resolveLayout(1400, DEFAULT_LAYOUT)).toEqual({ mode: "docked", width: 320, leftVisible: true });
  });

  it("keeps the canvas at 480px or more by shrinking the info column first", () => {
    const available = 800;
    const resolved = resolveLayout(available, { width: 560, collapsed: false, drawerOpen: false });
    expect(resolved.mode).toBe("docked");
    expect(available - resolved.width - SPLITTER_WIDTH).toBeGreaterThanOrEqual(CANVAS_MIN);
    expect(resolved.width).toBeGreaterThanOrEqual(LEFT_MIN);
    expect(maxLeftFor(available)).toBe(available - CANVAS_MIN - SPLITTER_WIDTH);
  });

  it("switches to a drawer when 280 + 480 + splitter no longer fit", () => {
    const tooNarrow = LEFT_MIN + CANVAS_MIN + SPLITTER_WIDTH - 1;
    expect(resolveLayout(tooNarrow, DEFAULT_LAYOUT).mode).toBe("drawer");
    expect(resolveLayout(tooNarrow, DEFAULT_LAYOUT).leftVisible).toBe(false);
    expect(resolveLayout(tooNarrow, { ...DEFAULT_LAYOUT, drawerOpen: true }).leftVisible).toBe(true);
    expect(resolveLayout(LEFT_MIN + CANVAS_MIN + SPLITTER_WIDTH, DEFAULT_LAYOUT).mode).toBe("docked");
  });

  it("honours a user-collapsed column and treats an unmeasured container as roomy", () => {
    expect(resolveLayout(1400, { ...DEFAULT_LAYOUT, collapsed: true })).toMatchObject({ mode: "collapsed", leftVisible: false });
    expect(resolveLayout(0, DEFAULT_LAYOUT).mode).toBe("docked");
  });
});
