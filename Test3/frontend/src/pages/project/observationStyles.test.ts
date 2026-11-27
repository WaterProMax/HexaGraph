import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExecutionAttempt, ExecutionStep, ExecutionTrace } from "../../api/types";
import {
  CONTEXT_INJECTED_NO_SKILL_TEXT,
  CONTEXT_INJECTED_WITH_SKILL_TEXT,
  CONTEXT_NOT_INJECTED_TEXT,
  OBSERVATION_STYLES,
  contextInjectionNote,
  downloadTextFile,
  hasObservationSteps,
  observationExport,
  tableToCsv,
  traceToJson,
  traceToMarkdown,
  traceToTable,
  traceToTimeline,
} from "./observationStyles";

/**
 * The fixture simulates an ALREADY redacted API response: one literal
 * ***REDACTED*** marker and one sk-shaped (but redacted) key. Converters must
 * pass both through untouched — never restore a secret, never invent one.
 */
const LLM_STEP: ExecutionStep = {
  step: 1,
  kind: "llm",
  name: "coder-gateway",
  status: "ok",
  started_at: "2026-11-24T09:00:00+00:00",
  ended_at: "2026-11-24T09:00:01+00:00",
  duration_ms: 850,
  model: "qwen-coder",
  slot: "coder",
  tokens_in: 1200,
  tokens_out: 340,
  finish_reason: "tool_calls",
  input_summary: "api_key=***REDACTED***; last_user=实现登录",
  output_summary: "tool_calls: write_file",
  error: null,
  truncated: false,
};

const TOOL_STEP: ExecutionStep = {
  step: 2,
  kind: "tool",
  name: "write_file",
  status: "ok",
  started_at: "2026-11-24T09:00:01+00:00",
  ended_at: "2026-11-24T09:00:01+00:00",
  duration_ms: 120,
  model: "",
  slot: "",
  tokens_in: 0,
  tokens_out: 0,
  finish_reason: "",
  input_summary: "path=src/login.py; chars=42",
  output_summary: "ok=true; key=sk-***REDACTED***",
  error: null,
  truncated: false,
};

const ATTEMPT: ExecutionAttempt = {
  attempt_id: "attempt-0001-aaaa",
  status: "finished_ok",
  started_at: "2026-11-24T09:00:00+00:00",
  ended_at: "2026-11-24T09:00:02+00:00",
  role: "coder",
  context_hash: "a".repeat(64),
  memory_context_hash: "b".repeat(64),
  manual_revision: 2,
  skill_bundle_hash: "c".repeat(64),
  commit: "d".repeat(40),
  context_injected: true,
  execution_path: "legacy_tool_agent",
  // Deliberately out of order: converters must sort by `step` ascending.
  steps: [TOOL_STEP, LLM_STEP],
};

function traceOf(overrides: Partial<ExecutionTrace> = {}): ExecutionTrace {
  return {
    run_id: "r1",
    task_code: "T1",
    role: "coder",
    execution_path: "legacy_tool_agent",
    context_injected: true,
    current_attempt_id: ATTEMPT.attempt_id,
    attempts: [ATTEMPT],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("observationStyles conversions", () => {
  it("exposes exactly the four styles with timeline first (default)", () => {
    expect(OBSERVATION_STYLES).toEqual(["timeline", "table", "json", "markdown"]);
  });

  it.each(OBSERVATION_STYLES)("style %s keeps key step names and never restores redacted secrets", (style) => {
    const trace = traceOf();
    const { content } = observationExport(trace, style);
    expect(content).toContain("coder-gateway");
    expect(content).toContain("write_file");
    // The redaction marker survives verbatim; no plaintext key is introduced.
    expect(content).toContain("***REDACTED***");
    expect(content).not.toMatch(/sk-[A-Za-z0-9_-]{8,}/);
    // Never claims data the trace API does not provide.
    expect(content).not.toContain("manual_text");
    expect(content).not.toContain("context_block");
    expect(content).not.toContain("LangSmith");
    expect(content).not.toContain("20 技能");
  });

  it("timeline reuses the panel data: ascending steps, labels, durations and honest context note", () => {
    const view = traceToTimeline(traceOf());
    expect(view.steps.map((step) => step.step)).toEqual([1, 2]);
    expect(view.steps[0].kindLabel).toBe("模型调用");
    expect(view.steps[0].statusLabel).toBe("成功");
    expect(view.steps[0].durationText).toBe("850ms");
    expect(view.steps[0].name).toBe("coder-gateway");
    expect(view.steps[0].inputSummary).toContain("***REDACTED***");
    expect(view.contextInjected).toBe(true);
    expect(view.contextNote).toBe(CONTEXT_INJECTED_WITH_SKILL_TEXT);
    expect(view.showingOlderAttempt).toBe(false);
  });

  it("timeline falls back to the newest attempt with steps and flags it honestly", () => {
    const live: ExecutionAttempt = { ...ATTEMPT, attempt_id: "attempt-0002-live", status: "started", steps: [] };
    const view = traceToTimeline(traceOf({ current_attempt_id: live.attempt_id, attempts: [ATTEMPT, live] }));
    expect(view.steps.length).toBe(2);
    expect(view.attemptId).toBe(ATTEMPT.attempt_id);
    expect(view.showingOlderAttempt).toBe(true);
  });

  it("context note stays honest for every injection state", () => {
    expect(contextInjectionNote(false, "")).toBe(CONTEXT_NOT_INJECTED_TEXT);
    expect(contextInjectionNote(true, "")).toBe(CONTEXT_INJECTED_NO_SKILL_TEXT);
    expect(contextInjectionNote(true, "c".repeat(64))).toBe(CONTEXT_INJECTED_WITH_SKILL_TEXT);
    const md = traceToMarkdown(traceOf({ context_injected: false, attempts: [{ ...ATTEMPT, context_injected: false, skill_bundle_hash: "" }] }));
    expect(md).toContain(CONTEXT_NOT_INJECTED_TEXT);
    expect(md).not.toContain("已注入");
  });

  it("table has the required columns and one row per step across attempts", () => {
    const table = traceToTable(traceOf());
    for (const column of ["step", "kind", "name", "status", "duration_ms", "model", "slot", "input_summary", "output_summary", "error"]) {
      expect(table.columns).toContain(column);
    }
    expect(table.rows.length).toBe(2);
    const stepIndex = table.columns.indexOf("step");
    expect(table.rows.map((row) => row[stepIndex])).toEqual([1, 2]);
    const nameIndex = table.columns.indexOf("name");
    expect(table.rows[0][nameIndex]).toBe("coder-gateway");
  });

  it("CSV cells starting with = + - @ get the formula-injection prefix (same rule as agentsToCsv)", () => {
    const hostile: ExecutionStep = {
      ...TOOL_STEP,
      step: 1,
      name: "+sum",
      input_summary: "-2+3",
      output_summary: "@SUM(A1)",
      error: '=HYPERLINK("http://evil")',
    };
    const csv = tableToCsv(traceToTable(traceOf({ attempts: [{ ...ATTEMPT, steps: [hostile] }] })));
    expect(csv).toContain("'+sum");
    expect(csv).toContain("'-2+3");
    expect(csv).toContain("'@SUM(A1)");
    expect(csv).toContain('"\'=HYPERLINK(""http://evil"")"');
    expect(csv.split("\r\n")[0]).toContain("duration_ms");
  });

  it("json export is the trace object verbatim (already redacted)", () => {
    const trace = traceOf();
    expect(JSON.parse(traceToJson(trace))).toEqual(trace);
    const { mime } = observationExport(trace, "json");
    expect(mime).toContain("application/json");
  });

  it("markdown lists task code, role, execution_path, context_injected and per-attempt steps", () => {
    const md = traceToMarkdown(traceOf());
    expect(md).toContain("T1");
    expect(md).toContain("coder");
    expect(md).toContain("execution_path");
    expect(md).toContain("legacy_tool_agent");
    expect(md).toContain("context_injected");
    expect(md).toContain(ATTEMPT.attempt_id);
    expect(md).toContain("coder-gateway");
    expect(md).toContain("write_file");
    expect(md).toContain("未计价");
  });

  it("export filenames contain runId, taskCode and the style name with the right extension", () => {
    const trace = traceOf();
    expect(observationExport(trace, "timeline").filename).toBe("trace-r1-T1-timeline.md");
    expect(observationExport(trace, "table").filename).toBe("trace-r1-T1-table.csv");
    expect(observationExport(trace, "json").filename).toBe("trace-r1-T1-json.json");
    expect(observationExport(trace, "markdown").filename).toBe("trace-r1-T1-markdown.md");
    expect(observationExport(trace, "table").mime).toContain("text/csv");
    expect(observationExport(trace, "markdown").mime).toContain("text/markdown");
  });

  it("sanitises unsafe filename characters without dropping the identifiers", () => {
    const { filename } = observationExport(traceOf({ run_id: "r/1", task_code: "T 1" }), "table");
    expect(filename).toBe("trace-r-1-T-1-table.csv");
  });

  it("empty traces convert to empty views and report no steps", () => {
    const empty = traceOf({ attempts: [], current_attempt_id: "", context_injected: false });
    expect(hasObservationSteps(empty)).toBe(false);
    expect(traceToTimeline(empty).steps).toEqual([]);
    expect(traceToTable(empty).rows).toEqual([]);
    expect(traceToMarkdown(empty)).toContain("还没有执行步骤");
    expect(hasObservationSteps(traceOf())).toBe(true);
    expect(hasObservationSteps(null)).toBe(false);
  });
});

describe("downloadTextFile", () => {
  it("downloads arbitrary MIME content via an object URL and revokes it", async () => {
    const blobs: Blob[] = [];
    const clicks: Array<{ download: string; href: string }> = [];
    const contents: string[] = [];
    // jsdom's Blob has no .text(); capture the constructor payload instead.
    class CapturingBlob extends Blob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        super(parts, options);
        contents.push(parts.map(String).join(""));
      }
    }
    vi.stubGlobal("Blob", CapturingBlob);
    const createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return `blob:mock-${blobs.length}`;
    });
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({ download: this.download, href: this.href });
    });

    downloadTextFile("trace-r1-T1-json.json", '{"a":1}', "application/json;charset=utf-8");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(blobs[0].type).toBe("application/json;charset=utf-8");
    expect(contents[0]).toBe('{"a":1}');
    expect(clicks).toEqual([{ download: "trace-r1-T1-json.json", href: "blob:mock-1" }]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-1");
    expect(document.querySelector("a[download]")).toBeNull();
  });
});
