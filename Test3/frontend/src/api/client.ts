const BASE = "/api";

async function req(path: string, init?: RequestInit) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (res.status === 409) {
    const err = new Error("409");
    (err as Error & { status: number }).status = 409;
    throw err;
  }
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export const api = {
  projects: () => req("/projects"),
  createProject: (name: string) => req("/projects", { method: "POST", body: JSON.stringify({ name }) }),
  createRun: (projectId: string, idea: string) =>
    req(`/projects/${projectId}/runs`, { method: "POST", body: JSON.stringify({ idea }) }),
  createDesignRun: (
    projectId: string,
    text: string,
    source: { kind: "text" | "file"; name?: string; note?: string },
    title = "",
  ) =>
    req(`/projects/${projectId}/design-runs`, {
      method: "POST",
      body: JSON.stringify({ text, source, title }),
    }),
  runs: () => req("/runs"),
  run: (id: string) => req(`/runs/${id}`),
  stages: (id: string) => req(`/runs/${id}/stages`),
  discussion: (id: string) => req(`/runs/${id}/discussion`),
  artifacts: (id: string) => req(`/runs/${id}/artifacts`),
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
