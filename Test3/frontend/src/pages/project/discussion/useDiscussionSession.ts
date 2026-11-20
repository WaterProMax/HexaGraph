import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../../api/client";
import type {
  DiscussionMessage,
  DiscussionSession,
  DiscussionTimelineItem,
  ReviewBallot,
} from "../../../api/types";

export type DiscussionConnection = "idle" | "connecting" | "live" | "error";

type Segment = { session: DiscussionSession; messages: DiscussionMessage[] };

/** Current session plus at most 10 previous sessions are replayed. */
const MAX_HISTORY_DEPTH = 10;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10000;
const RECONNECT_FALLBACK_AFTER = 4;
const POLL_INTERVAL_MS = 2000;

function sortBySeq(messages: DiscussionMessage[]): DiscussionMessage[] {
  return [...messages].sort((a, b) => a.seq - b.seq);
}

/**
 * Loads the latest discussion session of a project, replays the session chain
 * (oldest first) and follows the live message stream.
 *
 * Live updates use SSE; when the stream is unavailable or keeps failing the
 * hook falls back to polling `messages?after=<last seq>`. Nothing is persisted
 * in the browser — a reload rebuilds everything from the server.
 */
export function useDiscussionSession(projectId: string, actorBotId: string) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [session, setSession] = useState<DiscussionSession | null>(null);
  const [sessions, setSessions] = useState<DiscussionSession[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [reviews, setReviews] = useState<ReviewBallot[]>([]);
  const [connection, setConnection] = useState<DiscussionConnection>("idle");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!projectId || !actorBotId) {
      setLoading(false);
      setError("");
      setSession(null);
      setSessions([]);
      setSegments([]);
      setReviews([]);
      setConnection("idle");
      return;
    }

    let closed = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let lastSeq = 0;
    let failures = 0;
    let refreshing = false;

    const clearReconnect = () => {
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const stopPolling = () => {
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const closeSource = () => {
      if (source) {
        const current = source;
        source = null;
        current.close();
      }
    };

    setLoading(true);
    setError("");
    setConnection("connecting");

    const applyIncoming = (incoming: DiscussionMessage) => {
      setSegments((prev) => {
        if (prev.length === 0) return prev;
        const next = [...prev];
        const last = next[next.length - 1];
        if (last.messages.some((message) => message.seq === incoming.seq)) return prev;
        next[next.length - 1] = { ...last, messages: sortBySeq([...last.messages, incoming]) };
        return next;
      });
    };

    const refreshMeta = async (sessionId: string) => {
      if (refreshing || closed) return;
      refreshing = true;
      try {
        const [freshResult, reviewResult] = await Promise.allSettled([
          api.discussionSession(sessionId, actorBotId),
          api.discussionReviews(sessionId, actorBotId),
        ]);
        if (closed) return;
        if (freshResult.status === "fulfilled" && freshResult.value?.session_id) {
          const fresh = freshResult.value;
          setSession(fresh);
          setSessions((prev) => prev.map((item) => (item.session_id === fresh.session_id ? fresh : item)));
          setSegments((prev) =>
            prev.map((segment) =>
              segment.session.session_id === fresh.session_id ? { ...segment, session: fresh } : segment,
            ),
          );
        }
        if (reviewResult.status === "fulfilled") {
          const items = reviewResult.value?.items;
          setReviews(Array.isArray(items) ? items : []);
        }
      } finally {
        refreshing = false;
      }
    };

    const maybeRefreshMeta = (message: DiscussionMessage) => {
      const unsealed = message.kind === "system" && message.payload?.event === "proposals_unsealed";
      if (!unsealed && message.kind !== "review" && message.kind !== "leader") return;
      void refreshMeta(message.session_id);
    };

    const backfill = async (sessionId: string) => {
      try {
        const result = await api.discussionMessages(sessionId, lastSeq, actorBotId);
        if (closed) return;
        const items = Array.isArray(result?.items) ? result.items : [];
        for (const item of items) {
          if (!item || item.session_id !== sessionId) continue;
          if (item.seq <= lastSeq) continue;
          lastSeq = item.seq;
          applyIncoming(item);
          maybeRefreshMeta(item);
        }
      } catch {
        // The next reconnect attempt or poll retries from the same cursor.
      }
    };

    const startPolling = (sessionId: string) => {
      if (closed || pollTimer !== null) return;
      clearReconnect();
      closeSource();
      setConnection("error");
      void backfill(sessionId);
      pollTimer = setInterval(() => {
        void backfill(sessionId);
      }, POLL_INTERVAL_MS);
    };

    const openStream = (sessionId: string) => {
      if (closed) return;
      const ES = typeof EventSource === "undefined" ? null : EventSource;
      if (!ES) {
        startPolling(sessionId);
        return;
      }
      let es: EventSource;
      try {
        es = new ES(api.discussionEventsUrl(sessionId, actorBotId));
      } catch {
        startPolling(sessionId);
        return;
      }
      source = es;
      es.onopen = () => {
        if (closed) return;
        failures = 0;
        setConnection("live");
      };
      es.onmessage = (event: MessageEvent) => {
        if (closed) return;
        let incoming: DiscussionMessage;
        try {
          incoming = JSON.parse(event.data) as DiscussionMessage;
        } catch {
          return;
        }
        if (!incoming || incoming.session_id !== sessionId) return;
        if (typeof incoming.seq !== "number" || incoming.seq <= lastSeq) return;
        lastSeq = incoming.seq;
        setConnection("live");
        applyIncoming(incoming);
        maybeRefreshMeta(incoming);
      };
      es.onerror = () => {
        if (closed || pollTimer !== null) return;
        es.close();
        if (source === es) source = null;
        setConnection("error");
        failures += 1;
        if (failures >= RECONNECT_FALLBACK_AFTER) {
          startPolling(sessionId);
          return;
        }
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** (failures - 1), RECONNECT_MAX_MS);
        reconnectTimer = setTimeout(async () => {
          reconnectTimer = null;
          if (closed) return;
          await backfill(sessionId);
          if (closed) return;
          openStream(sessionId);
        }, delay);
      };
    };

    const load = async () => {
      try {
        const listed = await api.discussionSessions(projectId, actorBotId);
        if (closed) return;
        const items = Array.isArray(listed?.items) ? listed.items : [];
        const ordered = [...items].sort((a, b) =>
          a.created_at === b.created_at
            ? a.session_id.localeCompare(b.session_id)
            : String(a.created_at).localeCompare(String(b.created_at)),
        );
        setSessions(ordered);
        if (ordered.length === 0) {
          setSession(null);
          setSegments([]);
          setReviews([]);
          setConnection("idle");
          setLoading(false);
          return;
        }

        const current = ordered[ordered.length - 1];
        setSession(current);

        const known = new Map<string, DiscussionSession>();
        ordered.forEach((item) => known.set(item.session_id, item));
        const chain: Segment[] = [];
        const visited = new Set<string>();
        let cursor: DiscussionSession | null = current;
        while (cursor && chain.length <= MAX_HISTORY_DEPTH && !visited.has(cursor.session_id)) {
          const cursorSession: DiscussionSession = cursor;
          visited.add(cursorSession.session_id);
          const result = await api.discussionMessages(cursorSession.session_id, 0, actorBotId);
          if (closed) return;
          const messages = (Array.isArray(result?.items) ? result.items : [])
            .filter((message) => message?.session_id === cursorSession.session_id)
            .sort((a, b) => a.seq - b.seq);
          chain.unshift({ session: cursorSession, messages });

          const previousId: string | null = cursorSession.previous_session_id;
          if (!previousId) break;
          let previous: DiscussionSession | null = known.get(previousId) ?? null;
          if (!previous) {
            try {
              previous = await api.discussionSession(previousId, actorBotId);
            } catch {
              previous = null;
            }
            if (closed) return;
            if (previous) known.set(previous.session_id, previous);
          }
          cursor = previous;
        }

        const reviewResult = await api.discussionReviews(current.session_id, actorBotId);
        if (closed) return;

        const currentMessages = chain.length > 0 ? chain[chain.length - 1].messages : [];
        lastSeq = currentMessages.reduce((max, message) => Math.max(max, message.seq), 0);
        failures = 0;
        setSegments(chain);
        setReviews(Array.isArray(reviewResult?.items) ? reviewResult.items : []);
        setConnection("connecting");
        setLoading(false);
        openStream(current.session_id);
      } catch (err: any) {
        if (closed) return;
        setConnection("error");
        setLoading(false);
        setError(err?.message || "讨论加载失败");
      }
    };

    void load();

    return () => {
      closed = true;
      clearReconnect();
      stopPolling();
      closeSource();
    };
  }, [projectId, actorBotId, reloadKey]);

  const refresh = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);

  const messages = useMemo(
    () => (segments.length > 0 ? segments[segments.length - 1].messages : []),
    [segments],
  );

  const timeline = useMemo<DiscussionTimelineItem[]>(() => {
    const byId = new Map<string, DiscussionSession>();
    sessions.forEach((item) => byId.set(item.session_id, item));
    segments.forEach((segment) => byId.set(segment.session.session_id, segment.session));
    const ordinal = new Map<string, number>();
    sessions.forEach((item, index) => ordinal.set(item.session_id, index + 1));

    const items: DiscussionTimelineItem[] = [];
    segments.forEach((segment, index) => {
      const round = ordinal.get(segment.session.session_id) ?? index + 1;
      const previous = segment.session.previous_session_id
        ? byId.get(segment.session.previous_session_id)
        : null;
      const comment = (previous?.resolution_comment || "").trim();
      items.push({
        type: "divider",
        key: `divider-${segment.session.session_id}`,
        text: comment ? `第 ${round} 次讨论 · 你的意见：${comment}` : `第 ${round} 次讨论`,
      });
      segment.messages.forEach((message) => items.push({ type: "message", message }));
    });
    return items;
  }, [segments, sessions]);

  return { loading, error, session, sessions, messages, timeline, reviews, connection, refresh };
}