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

function mockFetch(result: unknown = {}) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(result),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("discussion API methods", () => {
  it("creates a session with the leader body and actor header", async () => {
    const fetchMock = mockFetch({ session_id: "s-1" });

    await api.createDiscussionSession(
      "p-1",
      {
        leader_bot_id: "leader-1",
        participant_bot_ids: ["leader-1", "bot-2"],
        requirement_snapshot: "做一个座位预约工具",
        budget: { max_rounds: 2, score_gap_threshold: 1.5 },
        previous_session_id: "s-0",
      },
      "leader-1",
    );

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/projects/p-1/discussion-sessions");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    expect(JSON.parse(init.body)).toEqual({
      leader_bot_id: "leader-1",
      participant_bot_ids: ["leader-1", "bot-2"],
      requirement_snapshot: "做一个座位预约工具",
      budget: { max_rounds: 2, score_gap_threshold: 1.5 },
      previous_session_id: "s-0",
    });
  });

  it("runs a session with an empty JSON body and the actor header", async () => {
    const fetchMock = mockFetch({ running: true, session: { session_id: "s-1" } });

    await api.runDiscussion("s-1", "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/discussion-sessions/s-1/run");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    expect(JSON.parse(init.body)).toEqual({});
  });

  it("reads messages after a seq with the actor header", async () => {
    const fetchMock = mockFetch({ items: [] });

    await api.discussionMessages("s-1", 7, "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/discussion-sessions/s-1/messages?after=7");
    expect(init.method).toBeUndefined();
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
  });

  it("pauses, resumes with optional skipped bots, and terminates with confirm", async () => {
    const fetchMock = mockFetch({ session_id: "s-1" });

    await api.pauseDiscussion("s-1", "leader-1");
    await api.resumeDiscussion("s-1", {}, "leader-1");
    await api.resumeDiscussion("s-1", { skip_bot_ids: ["bot-2"] }, "leader-1");
    await api.terminateDiscussion("s-1", "leader-1");

    const calls = fetchMock.mock.calls;
    expect(calls[0][0]).toBe("/api/discussion-sessions/s-1/pause");
    expect(calls[0][1].method).toBe("POST");
    expect(JSON.parse(calls[0][1].body)).toEqual({});

    expect(calls[1][0]).toBe("/api/discussion-sessions/s-1/resume");
    expect(JSON.parse(calls[1][1].body)).toEqual({});

    expect(calls[2][0]).toBe("/api/discussion-sessions/s-1/resume");
    expect(JSON.parse(calls[2][1].body)).toEqual({ skip_bot_ids: ["bot-2"] });

    expect(calls[3][0]).toBe("/api/discussion-sessions/s-1/terminate");
    expect(JSON.parse(calls[3][1].body)).toEqual({ confirm: true });

    for (const [, init] of calls) {
      expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    }
  });

  it("builds the events URL with an encoded bot id", () => {
    expect(api.discussionEventsUrl("s-1", "leader 1/+")).toBe(
      "/api/discussion-sessions/s-1/events?bot_id=leader%201%2F%2B",
    );
  });
});

describe("task role memory API methods", () => {
  it("reads the role memory with encoded scope and the actor header", async () => {
    const fetchMock = mockFetch({});

    await api.taskRoleMemory("run/1", "T 1", "tester", "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/runs/run%2F1/tasks/T%201/role-memory/tester");
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
  });

  it("saves with expected_revision, manual_text and the actor header", async () => {
    const fetchMock = mockFetch({});

    await api.saveTaskRoleMemory(
      "r1",
      "T1",
      "coder",
      { expected_revision: 3, manual_text: "优先覆盖空输入" },
      "leader-1",
    );

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/runs/r1/tasks/T1/role-memory/coder");
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    expect(JSON.parse(init.body)).toEqual({
      expected_revision: 3,
      manual_text: "优先覆盖空输入",
    });
  });

  it("deletes with the expected revision in the query string", async () => {
    const fetchMock = mockFetch({});

    await api.deleteTaskRoleMemory("r1", "T1", "coder", 4, "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/runs/r1/tasks/T1/role-memory/coder?expected_revision=4");
    expect(init.method).toBe("DELETE");
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
  });

  it("exposes run_busy as the parsed 409 category", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () => JSON.stringify({ error_category: "run_busy", detail: "run_busy" }),
      }),
    );

    await expect(
      api.saveTaskRoleMemory("r1", "T1", "coder", { expected_revision: 1, manual_text: "x" }, "leader-1"),
    ).rejects.toMatchObject({ status: 409, category: "run_busy" });
  });
});

describe("task assignment API", () => {
  it("assigns with a PUT, encoded scope, actor header and CAS body", async () => {
    const fetchMock = mockFetch({ code: "T1", assignment: { assignee_bot_id: "bot-a" } });

    await api.assignTask("run/1", "T 1", { assignee_bot_id: "bot-a", expected_revision: 3 }, "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/runs/run%2F1/tasks/T%201/assignment");
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    expect(JSON.parse(init.body)).toEqual({ assignee_bot_id: "bot-a", expected_revision: 3 });
  });

  it("clears the assignment with a null assignee", async () => {
    const fetchMock = mockFetch({ code: "T1", assignment: null });

    await api.assignTask("r1", "T1", { assignee_bot_id: null, expected_revision: 4 }, "leader-1");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/runs/r1/tasks/T1/assignment");
    expect(JSON.parse(init.body)).toEqual({ assignee_bot_id: null, expected_revision: 4 });
  });

  it("exposes revision_conflict and assignee_not_member as parsed categories", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () => JSON.stringify({ error_category: "revision_conflict", detail: "revision mismatch" }),
      }),
    );
    await expect(
      api.assignTask("r1", "T1", { assignee_bot_id: "bot-a", expected_revision: 1 }, "leader-1"),
    ).rejects.toMatchObject({ status: 409, category: "revision_conflict" });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => JSON.stringify({ error_category: "assignee_not_member", detail: "not a member" }),
      }),
    );
    await expect(
      api.assignTask("r1", "T1", { assignee_bot_id: "bot-x", expected_revision: 1 }, "leader-1"),
    ).rejects.toMatchObject({ status: 400, category: "assignee_not_member" });
  });
});

describe("discussion control API methods", () => {
  it("sends the control revision on pause, resume, intervention, end-round and start-round", async () => {
    const fetchMock = mockFetch({ session_id: "s-1" });

    await api.pauseDiscussion("s-1", "leader-1", 4);
    await api.resumeDiscussion("s-1", { expected_revision: 4, skip_bot_ids: ["bot-2"] }, "leader-1");
    await api.addDiscussionIntervention(
      "s-1",
      { expected_revision: 9, text: "先收敛接口边界" },
      "leader-1",
    );
    await api.endDiscussionRound(
      "s-1",
      { expected_revision: 5, reason: "方向已足够清楚", confirm: true },
      "leader-1",
    );
    await api.startDiscussionRound("s-1", { expected_revision: 8 }, "leader-1");

    const calls = fetchMock.mock.calls;
    expect(calls[0][0]).toBe("/api/discussion-sessions/s-1/pause");
    expect(JSON.parse(calls[0][1].body)).toEqual({ expected_revision: 4 });

    expect(calls[1][0]).toBe("/api/discussion-sessions/s-1/resume");
    expect(JSON.parse(calls[1][1].body)).toEqual({
      expected_revision: 4,
      skip_bot_ids: ["bot-2"],
    });

    expect(calls[2][0]).toBe("/api/discussion-sessions/s-1/interventions");
    expect(JSON.parse(calls[2][1].body)).toEqual({
      expected_revision: 9,
      text: "先收敛接口边界",
    });

    expect(calls[3][0]).toBe("/api/discussion-sessions/s-1/end-round");
    expect(JSON.parse(calls[3][1].body)).toEqual({
      expected_revision: 5,
      reason: "方向已足够清楚",
      confirm: true,
    });

    expect(calls[4][0]).toBe("/api/discussion-sessions/s-1/rounds/start");
    expect(JSON.parse(calls[4][1].body)).toEqual({ expected_revision: 8 });

    for (const [, init] of calls) {
      expect(init.method).toBe("POST");
      expect(init.headers).toMatchObject({ "X-Bot-Id": "leader-1" });
    }
  });

  it("returns the wrapped { running, session } run payload", async () => {
    const fetchMock = mockFetch({ running: true, session: { session_id: "s-1" } });

    const result = await api.runDiscussion("s-1", "leader-1");

    expect(result).toEqual({ running: true, session: { session_id: "s-1" } });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/discussion-sessions/s-1/run");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({});
  });
});
describe("execution trace API", () => {
  it("requests the task-scoped trace path and keeps snake_case fields", async () => {
    const body = {
      run_id: "run-1",
      task_code: "T-01",
      role: "coder",
      execution_path: "legacy_tool_agent",
      context_injected: true,
      current_attempt_id: "a-1",
      attempts: [
        {
          attempt_id: "a-1",
          status: "finished_ok",
          started_at: "2026-11-26T00:00:00+00:00",
          ended_at: "2026-11-26T00:00:01+00:00",
          role: "coder",
          context_hash: "ctx",
          memory_context_hash: "mem",
          manual_revision: 3,
          skill_bundle_hash: "",
          commit: "abc",
          context_injected: true,
          execution_path: "legacy_tool_agent",
          steps: [
            {
              step: 1,
              kind: "tool",
              name: "read_file",
              status: "ok",
              started_at: "2026-11-26T00:00:00+00:00",
              ended_at: "2026-11-26T00:00:00+00:00",
              duration_ms: 5,
              model: "",
              slot: "",
              tokens_in: 0,
              tokens_out: 0,
              finish_reason: "",
              input_summary: "path=src/app.py",
              output_summary: "chars=12",
              error: null,
              truncated: true,
            },
          ],
        },
      ],
    };
    const fetchMock = mockFetch(body);

    const trace = await api.executionTrace("run-1", "T-01");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs/run-1/tasks/T-01/execution-trace");
    expect(trace.execution_path).toBe("legacy_tool_agent");
    expect(trace.context_injected).toBe(true);
    expect(trace.attempts[0].steps[0]).toMatchObject({
      kind: "tool",
      name: "read_file",
      duration_ms: 5,
      truncated: true,
      error: null,
    });
  });

  it("encodes run and task identifiers", async () => {
    const fetchMock = mockFetch({ attempts: [] });

    await api.executionTrace("run/1", "T 01");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs/run%2F1/tasks/T%2001/execution-trace");
  });
});
