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
  run: (id: string) => req(`/runs/${id}`),
  discussion: (id: string) => req(`/runs/${id}/discussion`),
  artifacts: (id: string) => req(`/runs/${id}/artifacts`),
  todos: (id: string) => req(`/runs/${id}/todos`),
  tasks: (id: string) => req(`/runs/${id}/tasks`),
  budget: (id: string) => req(`/runs/${id}/budget`),
  events: (id: string, after = 0) => req(`/runs/${id}/events/history?after=${after}`),
  resolveGate: (gateId: string, decision: string, payload: object) =>
    req(`/gates/${gateId}/resolve`, { method: "POST", body: JSON.stringify({ decision, payload }) }),
  control: (taskId: string, action: string, expected_revision: number, reason: string) =>
    req(`/tasks/${taskId}/${action}`, { method: "POST", body: JSON.stringify({ expected_revision, reason }) }),
  models: () => req("/config/models"),
  testModels: () => req("/config/models/test", { method: "POST" }),
};

export const CONTROL_ENABLED: Record<string, string[]> = {
  retry: ["needs_human", "failed"],
  skip: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
  "force-pass": ["needs_human", "failed"],
  pause: ["pending", "ready", "running", "verifying", "failed", "needs_human", "blocked"],
};

export function controlEnabled(action: string, state: string): boolean {
  return (CONTROL_ENABLED[action] || []).includes(state);
}
