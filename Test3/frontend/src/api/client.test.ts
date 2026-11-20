import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api error parsing", () => {
  it("explains an empty 5xx body as an unreachable backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => "" }));
    await expect(api.health()).rejects.toMatchObject({
      status: 500,
      message: expect.stringContaining("make dev-backend"),
    });
  });

  it("keeps a plain status code for an empty 4xx body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => "" }));
    await expect(api.health()).rejects.toMatchObject({ status: 404, message: "404" });
  });

  it("keeps 409 category, summary, and run_id from JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () =>
          JSON.stringify({
            detail: {
              category: "import_in_progress",
              summary: "该项目已有正在整理的设计规格",
              run_id: "run-existing",
            },
          }),
      }),
    );

    await expect(api.createDesignRun("proj", "目标：座位", { kind: "text" })).rejects.toMatchObject({
      status: 409,
      category: "import_in_progress",
      summary: "该项目已有正在整理的设计规格",
      run_id: "run-existing",
    });
  });
});

describe("P2–P5 error body compatibility", () => {
  it("reads error_category and string detail from the standard domain error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () => JSON.stringify({ error_category: "baseline_stale", detail: "approved hashes changed" }),
      }),
    );
    await expect(api.executionGrants("run-1")).rejects.toMatchObject({
      status: 409,
      category: "baseline_stale",
      message: "approved hashes changed",
    });
  });

  it("keeps the legacy detail-object shape working", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () => JSON.stringify({ detail: { category: "import_in_progress", summary: "整理中", run_id: "r1" } }),
      }),
    );
    await expect(api.executionGrants("run-1")).rejects.toMatchObject({
      category: "import_in_progress",
      summary: "整理中",
      run_id: "r1",
    });
  });
});
