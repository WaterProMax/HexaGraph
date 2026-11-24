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

/** Empty 5xx bodies usually mean the dev proxy could not reach the backend. */
function emptyServerErrorMessage(status: number): string {
  return `后端没有响应（HTTP ${status}）。请确认后端已启动：cd Test3 && make dev-backend（127.0.0.1:8765）`;
}

function parseApiError(status: number, text: string): ApiError {
  let category: string | undefined;
  let summary: string | undefined;
  let runId: string | undefined;
  let message = text.trim() || (status >= 500 ? emptyServerErrorMessage(status) : String(status));
  try {
    const body = JSON.parse(text) as { detail?: unknown; error_category?: unknown };
    // P2–P5 domain errors: {"error_category": "...", "detail": "..."}.
    if (typeof body?.error_category === "string" && body.error_category) {
      category = body.error_category;
    }
    const detail = body?.detail ?? body;
    if (detail && typeof detail === "object") {
      const rec = detail as Record<string, unknown>;
      // Legacy shape: {"detail": {category, summary, run_id}}.
      category = typeof rec.category === "string" ? rec.category : category;
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
    ...init,
    // Spread init first so an actor-only header map cannot drop Content-Type.
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    throw parseApiError(res.status, await res.text());
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

/** Attach the explicit actor header required by discussion/acceptance routes. */
function botHeader(botId: string): Record<string, string> {
  return { "X-Bot-Id": botId };
}

export const api = {
  health: () => req("/health"),
  projects: (includeArchived = false) =>
    req(`/projects${includeArchived ? "?include_archived=true" : ""}`),
  createProject: (name: string) => req("/projects", { method: "POST", body: JSON.stringify({ name }) }),
  archiveProject: (projectId: string) =>
    req(`/projects/${encodeURIComponent(projectId)}/archive`, { method: "POST", body: JSON.stringify({}) }),
  restoreProject: (projectId: string) =>
    req(`/projects/${encodeURIComponent(projectId)}/restore`, { method: "POST", body: JSON.stringify({}) }),
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
  monitor: (id: string): Promise<import("./types").MonitorSnapshot> => req(`/runs/${id}/monitor`),
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

  // --- P2–P5 domains ---------------------------------------------------------
  bots: (status?: "active" | "archived") =>
    req(`/bots${status ? `?status=${status}` : ""}`),
  bot: (botId: string) => req(`/bots/${encodeURIComponent(botId)}`),
  createBot: (body: import("./types").BotCreate) =>
    req("/bots", { method: "POST", body: JSON.stringify(body) }),
  patchBot: (botId: string, body: import("./types").BotPatch) =>
    req(`/bots/${encodeURIComponent(botId)}`, { method: "PATCH", body: JSON.stringify(body) }),
  chatBot: (botId: string, messages: import("./types").ChatMessage[]): Promise<import("./types").ChatReply> =>
    req(`/bots/${encodeURIComponent(botId)}/chat`, { method: "POST", body: JSON.stringify({ messages }) }),
  botFiles: (botId: string): Promise<import("./types").BotFileLibrary> =>
    req(`/bots/${encodeURIComponent(botId)}/files`),
  uploadBotFile: (
    botId: string,
    body: { filename: string; content: string },
  ): Promise<import("./types").BotFileLibrary & { file: import("./types").BotFile }> =>
    req(`/bots/${encodeURIComponent(botId)}/files`, { method: "POST", body: JSON.stringify(body) }),
  deleteBotFile: (botId: string, fileId: string): Promise<null> =>
    req(`/bots/${encodeURIComponent(botId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }),
  archiveBot: (botId: string) =>
    req(`/bots/${encodeURIComponent(botId)}/archive`, { method: "POST", body: JSON.stringify({}) }),
  skills: () => req("/skills"),
  importSkill: (url: string) => req("/skills/import", { method: "POST", body: JSON.stringify({ url }) }),
  memberships: (projectId: string) => req(`/projects/${projectId}/memberships`),
  addMembership: (projectId: string, body: import("./types").MembershipCreate) =>
    req(`/projects/${projectId}/memberships`, { method: "POST", body: JSON.stringify(body) }),
  removeMembership: (projectId: string, botId: string) =>
    req(`/projects/${projectId}/memberships/${encodeURIComponent(botId)}`, { method: "DELETE" }),
  executionGrants: (runId: string) => req(`/runs/${runId}/execution-grants`),
  executionProfile: (runId: string) => req(`/runs/${runId}/execution-profile`),
  scheduleRun: (runId: string, taskCodes?: string[]) =>
    req(`/runs/${runId}/schedule`, {
      method: "POST",
      body: JSON.stringify(taskCodes ? { task_codes: taskCodes } : {}),
    }),

  // Discussion (C.5.6) requires X-Bot-Id as the actor.
  discussionSessions: (projectId: string, botId: string): Promise<{ items: import("./types").DiscussionSession[] }> =>
    req(`/projects/${projectId}/discussion-sessions`, { headers: botHeader(botId) }),
  discussionSession: (sessionId: string, botId: string): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}`, { headers: botHeader(botId) }),
  discussionProposals: (sessionId: string, botId: string): Promise<{ items: import("./types").DiscussionProposal[] }> =>
    req(`/discussion-sessions/${sessionId}/proposals?include_history=true`, { headers: botHeader(botId) }),
  discussionReviews: (sessionId: string, botId: string): Promise<{ items: import("./types").ReviewBallot[] }> =>
    req(`/discussion-sessions/${sessionId}/reviews`, { headers: botHeader(botId) }),
  resolveDiscussion: (
    sessionId: string,
    body: { decision: "approved" | "rejected"; comment?: string; run_id?: string },
    botId: string,
  ): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}/resolve`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify(body),
    }),
  createDiscussionSession: (
    projectId: string,
    body: import("./types").DiscussionSessionCreate,
    botId: string,
  ): Promise<import("./types").DiscussionSession> =>
    req(`/projects/${projectId}/discussion-sessions`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify(body),
    }),
  runDiscussion: (
    sessionId: string,
    botId: string,
  ): Promise<{ running: boolean; session: import("./types").DiscussionSession }> =>
    req(`/discussion-sessions/${sessionId}/run`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify({}),
    }),
  discussionMessages: (
    sessionId: string,
    after: number,
    botId: string,
  ): Promise<{ items: import("./types").DiscussionMessage[] }> =>
    req(`/discussion-sessions/${sessionId}/messages?after=${Math.max(0, Math.floor(after))}`, {
      headers: botHeader(botId),
    }),
  pauseDiscussion: (sessionId: string, botId: string): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}/pause`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify({}),
    }),
  resumeDiscussion: (
    sessionId: string,
    body: { skip_bot_ids?: string[] },
    botId: string,
  ): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}/resume`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify(body.skip_bot_ids?.length ? { skip_bot_ids: body.skip_bot_ids } : {}),
    }),
  terminateDiscussion: (sessionId: string, botId: string): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}/terminate`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify({ confirm: true }),
    }),
  supplementDiscussion: (sessionId: string, text: string, botId: string): Promise<import("./types").DiscussionSession> =>
    req(`/discussion-sessions/${sessionId}/supplement`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...botHeader(botId) },
      body: JSON.stringify({ text }),
    }),
  planDiscussion: (sessionId: string, botId: string): Promise<{ run_id: string }> =>
    req(`/discussion-sessions/${sessionId}/plan`, {
      method: "POST",
      headers: botHeader(botId),
    }),
  discussionEventsUrl: (sessionId: string, botId: string): string =>
    `/api/discussion-sessions/${sessionId}/events?bot_id=${encodeURIComponent(botId)}`,

  // Memory (C.5.5): every route requires an explicit X-Bot-Id actor.
  memories: (
    query: { owner_bot_id?: string; project_id?: string; visibility?: "private" | "project" | "run" },
    botId: string,
  ) => {
    const params = new URLSearchParams();
    if (query.owner_bot_id) params.set("owner_bot_id", query.owner_bot_id);
    if (query.project_id) params.set("project_id", query.project_id);
    if (query.visibility) params.set("visibility", query.visibility);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return req(`/memory/records${suffix}`, { headers: botHeader(botId) });
  },
  createMemory: (body: import("./types").MemoryCreate, botId: string) =>
    req("/memory/records", { method: "POST", headers: botHeader(botId), body: JSON.stringify(body) }),
  publishMemory: (memId: string, expectedVersion: number, botId: string) =>
    req(`/memory/records/${encodeURIComponent(memId)}/publish`, {
      method: "POST",
      headers: botHeader(botId),
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),

  // Module acceptance / defects (C.5.7) require X-Bot-Id.
  moduleAcceptances: (runId: string, botId: string) =>
    req(`/runs/${runId}/module-acceptances`, { headers: botHeader(botId) }),
  defects: (runId: string, botId: string) =>
    req(`/runs/${runId}/defects`, { headers: botHeader(botId) }),
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
