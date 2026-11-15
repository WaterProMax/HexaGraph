import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export type EventConnection = "idle" | "connecting" | "live" | "error";

export function useRunEvents(runId: string | undefined, onRecover?: () => void) {
  const [events, setEvents] = useState<any[]>([]);
  const [connection, setConnection] = useState<EventConnection>("idle");
  const [connectionError, setConnectionError] = useState("");
  const [retry, setRetry] = useState({ runId: "", attempt: 0 });
  const recoverRef = useRef(onRecover);
  recoverRef.current = onRecover;

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setConnection("idle");
      setConnectionError("");
      return;
    }
    let closed = false;
    let last = 0;
    const isReconnect = retry.runId === runId && retry.attempt > 0;
    setEvents([]);
    setConnection("connecting");
    setConnectionError("");

    const load = async (notifyRecovery = false) => {
      try {
        const hist = await api.events(runId, 0);
        if (closed) return;
        setEvents(hist);
        last = hist.at(-1)?.seq || 0;
        if (notifyRecovery) recoverRef.current?.();
      } catch (err: any) {
        if (!closed) {
          setConnection("error");
          setConnectionError(err?.message || "事件历史加载失败");
        }
      }
    };

    // 重连时等连接打开后再做全量同步，避免把网络恢复误当成同步完成。
    if (!isReconnect) void load();
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onopen = () => {
      if (closed) return;
      setConnection("live");
      setConnectionError("");
      if (isReconnect) void load(true);
    };
    es.onmessage = (msg) => {
      if (closed) return;
      setConnection("live");
      setConnectionError("");
      const data = JSON.parse(msg.data);
      if (data.seq > last + 1) {
        void load();
        return;
      }
      last = data.seq;
      setEvents((prev) => [...prev.filter((e) => e.seq !== data.seq), data]);
    };
    es.onerror = () => {
      if (closed) return;
      setConnection("error");
      setConnectionError("事件连接已断开，可重新连接并同步当前状态");
      es.close();
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [runId, retry]);

  const reconnect = useCallback(() => {
    if (!runId || connection !== "error") return;
    setRetry((previous) => ({
      runId,
      attempt: previous.runId === runId ? previous.attempt + 1 : 1,
    }));
  }, [runId, connection]);

  return { events, connection, connectionError, reconnect };
}
