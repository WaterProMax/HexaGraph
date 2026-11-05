import { useEffect, useState } from "react";
import { api } from "../api/client";

export function useRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<any[]>([]);
  useEffect(() => {
    if (!runId) return;
    let closed = false;
    let last = 0;
    const load = async () => {
      const hist = await api.events(runId, 0);
      if (!closed) {
        setEvents(hist);
        last = hist.at(-1)?.seq || 0;
      }
    };
    load();
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.seq > last + 1) {
        load();
        return;
      }
      last = data.seq;
      setEvents((prev) => [...prev.filter((e) => e.seq !== data.seq), data]);
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [runId]);
  return events;
}
