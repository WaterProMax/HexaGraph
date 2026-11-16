const BASE = "/api";

export class ApiError extends Error {
  status: number;
  category?: string;
  summary?: string;
  run_id?: string;

  constructor(
    message: string,
    init: { status: number; category?: string; summary?: string; run_id?: string },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = init.status;
    this.category = init.category;
    this.summary = init.summary;
    this.run_id = init.run_id;
  }
}

function parseApiError(status: number, text: string): ApiError {
  let category: string | undefined;
  let summary: string | undefined;
  let runId: string | undefined;
  let message = text || String(status);
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const detail = body?.detail ?? body;
    if (detail && typeof detail === "object") {
      const rec = detail as Record<string, unknown>;
      category = typeof rec.category === "string" ? rec.category : undefined;
      summary = typeof rec.summary === "string" ? rec.summary : undefined;
      runId = typeof rec.run_id === "string" ? rec.run_id : undefined;
      if (summary) message = summary;
      else if (typeof rec.message === "string" && rec.message) message = rec.message;
    } else if (typeof detail === "string" && detail) {
      message = detail;
    }
  } catch {
    // keep raw text; never invent secrets from the payload
  }
  return new ApiError(message, { status, category, summary, run_id: runId });
}

async function req(path: string, init?: RequestInit) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    throw parseApiError(res.status, await res.text());
  }
  return res.json();
}

export const api = {
  health: () => req("/health"),
  projects: () => req("/projects"),
  createProject: (name: string) => req("/projects", { method: "POST", body: JSON.stringify({ name }) }),
  createRun: (projectId: string, idea: string) =>
    req(`/projects/${projectId}/runs`, { method: "POST", body: JSON.stringify({ idea }) }),
  createDesignRun: (
    projectId: string,
    text: string,
    source: { kind: "text" | "file"; name?: string; note?: string },
    title = "",
    init?: RequestInit,
  ) =>
    req(`/projects/${projectId}/design-runs`, {
      method: "POST",
      body: JSON.stringify({ text, source, title }),
      signal: init?.signal,
    }),
  runs: () => req("/runs"),
  run: (id: string, init?: RequestInit) => req(`/runs/${id}`, init),
  stages: (id: string) => req(`/runs/${id}/stages`),
  discussion: (id: string) => req(`/runs/${id}/discussion`),
  artifacts: (id: string, init?: RequestInit) => req(`/runs/${id}/artifacts`, init),
  todos: (id: string) => req(`/runs/${id}/todos`),
  tasks: (id: string) => req(`/runs/${id}/tasks`),
  task: (taskId: string) => req(`/tasks/${taskId}`),
  budget: (id: string) => req(`/runs/${id}/budget`),
  trace: (id: string) => req(`/runs/${id}/trace`),
  events: (id: string, after = 0) => req(`/runs/${id}/events/history?after=${after}`),
  resolveGate: (gateId: string, decision: string, payload: object, expected_revision?: number) =>
    req(`/gates/${gateId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ decision, payload, ...(expected_revision !== undefined ? { expected_revision } : {}) }),
    }),
  control: (taskId: string, action: string, expected_revision: number, reason: string, payload: object = {}) =>
    req(`/tasks/${taskId}/${action}`, { method: "POST", body: JSON.stringify({ expected_revision, reason, payload }) }),
  schedule: (id: string) => req(`/runs/${id}/schedule`, { method: "POST" }),
  accept: (id: string) => req(`/runs/${id}/accept`, { method: "POST" }),
  pauseRun: (id: string) => req(`/runs/${id}/pause`, { method: "POST" }),
  resumeRun: (id: string) => req(`/runs/${id}/resume`, { method: "POST" }),
  terminate: (id: string) => req(`/runs/${id}/terminate`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  models: () => req("/config/models"),
  testModels: () => req("/config/models/test", { method: "POST" }),
};

export const CONTROL_ENABLED: Record<string, string[]> = {
  retry: ["needs_human", "failed"],
  skip: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
  "force-pass": ["needs_human", "failed"],
  pause: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
  resume: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
  takeover: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
  "submit-takeover": ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
};

export function controlEnabled(action: string, state: string): boolean {
  return (CONTROL_ENABLED[action] || []).includes(state);
}
