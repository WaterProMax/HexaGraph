import { useEffect, useState } from "react";
import { api } from "../api/client";

export type EventConnection = "idle" | "connecting" | "live" | "error";

export function useRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<any[]>([]);
  const [connection, setConnection] = useState<EventConnection>("idle");
  const [connectionError, setConnectionError] = useState("");

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setConnection("idle");
      setConnectionError("");
      return;
    }
    let closed = false;
    let last = 0;
    setConnection("connecting");
    setConnectionError("");
    const load = async () => {
      try {
        const hist = await api.events(runId, 0);
        if (!closed) {
          setEvents(hist);
          last = hist.at(-1)?.seq || 0;
        }
      } catch (err: any) {
        if (!closed) {
          setConnection("error");
          setConnectionError(err?.message || "事件历史加载失败");
        }
      }
    };
    load();
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onopen = () => {
      if (!closed) {
        setConnection("live");
        setConnectionError("");
      }
    };
    es.onmessage = (msg) => {
      if (closed) return;
      setConnection("live");
      setConnectionError("");
      const data = JSON.parse(msg.data);
      if (data.seq > last + 1) {
        load();
        return;
      }
      last = data.seq;
      setEvents((prev) => [...prev.filter((e) => e.seq !== data.seq), data]);
    };
    es.onerror = () => {
      if (closed) return;
      setConnection("error");
      setConnectionError("事件连接已断开，页面不再实时更新");
      es.close();
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [runId]);

  return { events, connection, connectionError };
}
