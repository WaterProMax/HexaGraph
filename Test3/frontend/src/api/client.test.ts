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