import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  DiscussionMessage,
  DiscussionMessageKind,
  DiscussionSession,
  DiscussionSessionStatus,
} from "../../../api/types";
import { useDiscussionSession } from "./useDiscussionSession";

const apiMock = vi.hoisted(() => ({
  discussionSessions: vi.fn(),
  discussionSession: vi.fn(),
  discussionMessages: vi.fn(),
  discussionReviews: vi.fn(),
  discussionEventsUrl: vi.fn(
    (sessionId: string, botId: string) =>
      `/api/discussion-sessions/${sessionId}/events?bot_id=${encodeURIComponent(botId)}`,
  ),
}));

vi.mock("../../../api/client", () => ({ api: apiMock }));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 2;
  });

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  open() {
    this.onopen?.(new Event("open"));
  }

  fail() {
    this.onerror?.(new Event("error"));
  }

  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

function makeSession(
  sessionId: string,
  overrides: Partial<DiscussionSession> = {},
): DiscussionSession {
  return {
    session_id: sessionId,
    project_id: "p-1",
    leader_bot_id: "leader-1",
    participant_bot_ids: ["leader-1", "bot-2"],
    status: "cross_review",
    current_round: 1,
    budget: { max_rounds: 3, max_tokens: null, max_wallclock_seconds: null, score_gap_threshold: 2 },
    requirement_snapshot_hash: "hash",
    decision_package: null,
    requirement_text: "做一个座位预约工具",
    previous_session_id: null,
    resolution_comment: null,
    paused: false,
    created_at: "2026-11-20T08:00:00+00:00",
    ...overrides,
  };
}

function makeMessage(
  sessionId: string,
  seq: number,
  kind: DiscussionMessageKind = "system",
  payload: Record<string, any> = { event: "round_started", text: "开始" },
): DiscussionMessage {
  return {
    session_id: sessionId,
    seq,
    kind,
    bot_id: kind === "system" ? null : "bot-2",
    round: 1,
    payload,
    created_at: `2026-11-20T08:00:0${seq}+00:00`,
  };
}

const s1 = makeSession("s1", {
  status: "rejected",
  resolution_comment: "请补充离线能力",
  created_at: "2026-11-20T08:00:00+00:00",
});
const s2 = makeSession("s2", {
  status: "cross_review",
  previous_session_id: "s1",
  created_at: "2026-11-20T10:00:00+00:00",
});

const s1Messages = [makeMessage("s1", 1), makeMessage("s1", 2, "proposal", { proposal_id: "prop-1" })];
const s2Messages = [makeMessage("s2", 1), makeMessage("s2", 2, "proposal", { proposal_id: "prop-2" })];
const ballot = {
  reviewer_bot_id: "bot-2",
  proposal_id: "prop-2",
  scores: { value: 4, feasibility: 4, testability: 4, clarity: 4 },
  score_justification: { value: "", feasibility: "", testability: "", clarity: "" },
  hard_gate_results: { coverage: true, conflicts_closed_or_recorded: true, evidence_complete: true },
  dissent_items: [],
};

function stubEventSource(ctor: unknown = FakeEventSource) {
  vi.stubGlobal("EventSource", ctor as any);
}

async function flushPromises(times = 30) {
  await act(async () => {
    for (let i = 0; i < times; i += 1) await Promise.resolve();
  });
}

describe("useDiscussionSession", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    apiMock.discussionSessions.mockReset().mockResolvedValue({ items: [s2, s1] });
    apiMock.discussionSession.mockReset().mockImplementation(async (sessionId: string) =>
      sessionId === "s1" ? s1 : s2,
    );
    apiMock.discussionMessages.mockReset().mockImplementation(async (sessionId: string, after: number) => {
      const all = sessionId === "s1" ? s1Messages : sessionId === "s2" ? s2Messages : [];
      return { items: all.filter((message) => message.seq > after) };
    });
    apiMock.discussionReviews.mockReset().mockResolvedValue({ items: [ballot] });
    apiMock.discussionEventsUrl.mockClear();
    stubEventSource();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("loads sessions oldest-first and replays the chain with dividers", async () => {
    const { result } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("");
    expect(result.current.sessions.map((item) => item.session_id)).toEqual(["s1", "s2"]);
    expect(result.current.session?.session_id).toBe("s2");
    expect(result.current.messages.map((message) => message.seq)).toEqual([1, 2]);
    expect(result.current.reviews).toHaveLength(1);

    const dividers = result.current.timeline.filter((item) => item.type === "divider");
    expect(dividers.map((item) => item.key)).toEqual(["divider-s1", "divider-s2"]);
    expect(dividers.map((item) => item.text)).toEqual([
      "第 1 次讨论",
      "第 2 次讨论 · 你的意见：请补充离线能力",
    ]);
    const replayed = result.current.timeline
      .filter((item) => item.type === "message")
      .map((item) => item.message.session_id);
    expect(replayed).toEqual(["s1", "s1", "s1", "s2", "s2"]);

    expect(apiMock.discussionMessages).toHaveBeenCalledWith("s1", 0, "leader-1");
    expect(apiMock.discussionMessages).toHaveBeenCalledWith("s2", 0, "leader-1");
  });

  it("subscribes to the actor's events URL and appends messages once per seq", async () => {
    const { result } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(FakeEventSource.instances).toHaveLength(1);
    const stream = FakeEventSource.instances[0];
    expect(stream.url).toContain("/api/discussion-sessions/s2/events?bot_id=leader-1");
    expect(apiMock.discussionEventsUrl).toHaveBeenCalledWith("s2", "leader-1");

    act(() => stream.open());
    expect(result.current.connection).toBe("live");

    act(() => stream.message(makeMessage("s2", 2, "proposal", { proposal_id: "prop-2" })));
    expect(result.current.messages.map((message) => message.seq)).toEqual([1, 2]);

    act(() => stream.message(makeMessage("s2", 3, "review", { proposal_id: "prop-2", total: 16 })));
    expect(result.current.messages.map((message) => message.seq)).toEqual([1, 2, 3]);
    const last = result.current.timeline[result.current.timeline.length - 1];
    expect(last).toMatchObject({ type: "message", message: { seq: 3, kind: "review" } });
    expect(result.current.timeline.filter((item) => item.type === "divider")).toHaveLength(2);
  });

  it("refreshes the session and reviews when proposals are unsealed", async () => {
    const { result } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const stream = FakeEventSource.instances[0];
    act(() => stream.open());

    const refreshed = { ...s2, status: "cross_review" as DiscussionSessionStatus };
    apiMock.discussionSession.mockResolvedValue(refreshed);
    const secondBallot = { ...ballot, proposal_id: "prop-9" };
    apiMock.discussionReviews.mockResolvedValue({ items: [ballot, secondBallot] });

    act(() =>
      stream.message(makeMessage("s2", 3, "system", { event: "proposals_unsealed", text: "方案已解封" })),
    );

    await waitFor(() => expect(apiMock.discussionSession).toHaveBeenCalledWith("s2", "leader-1"));
    await waitFor(() => expect(result.current.reviews).toHaveLength(2));
  });

  it("reconnects after a drop, backfilling from the last seen seq", async () => {
    const { result } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const first = FakeEventSource.instances[0];
    act(() => first.open());

    apiMock.discussionMessages.mockImplementation(async (sessionId: string, after: number) => {
      if (sessionId === "s2" && after >= 2) return { items: [makeMessage("s2", 3, "leader", { action: "submit" })] };
      const all = sessionId === "s1" ? s1Messages : s2Messages;
      return { items: all.filter((message) => message.seq > after) };
    });

    vi.useFakeTimers();
    act(() => first.fail());
    expect(result.current.connection).toBe("error");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(apiMock.discussionMessages).toHaveBeenLastCalledWith("s2", 2, "leader-1");
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(result.current.messages.map((message) => message.seq)).toEqual([1, 2, 3]);
  });

  it("falls back to polling every 2 seconds when EventSource is unavailable", async () => {
    vi.stubGlobal("EventSource", undefined);
    vi.useFakeTimers();

    const { result } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await flushPromises();

    expect(result.current.loading).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.connection).toBe("error");
    expect(apiMock.discussionMessages).toHaveBeenLastCalledWith("s2", 2, "leader-1");

    const callsBeforeTick = apiMock.discussionMessages.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(apiMock.discussionMessages.mock.calls.length).toBeGreaterThan(callsBeforeTick);
    expect(apiMock.discussionMessages).toHaveBeenLastCalledWith("s2", 2, "leader-1");
  });

  it("closes the stream, cancels the reconnect timer and ignores messages after unmount", async () => {
    const { unmount } = renderHook(() => useDiscussionSession("p-1", "leader-1"));
    await waitFor(() => expect(apiMock.discussionReviews).toHaveBeenCalled());
    const stream = FakeEventSource.instances[0];
    act(() => stream.open());

    vi.useFakeTimers();
    act(() => stream.fail());
    expect(stream.close).toHaveBeenCalled();

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
