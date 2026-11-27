import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { MonitorSnapshot } from "../../api/types";

export function useRunMonitor(runId?: string) {
  const [data, setData] = useState<MonitorSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  const refresh = useCallback(async (quiet = false) => {
    if (!runId) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    const current = ++requestId.current;
    if (!quiet) setLoading(true);
    try {
      const result = await api.monitor(runId);
      if (current !== requestId.current) return;
      if (!result || Array.isArray(result) || !result.run || !Array.isArray(result.tasks)) {
        setError("监控接口尚未返回聚合数据");
        setData(null);
        return;
      }
      setData(result);
      setError("");
    } catch (err: any) {
      if (current !== requestId.current) return;
      setError(err?.message || "监控数据加载失败");
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    requestId.current += 1;
    setData(null);
    setError("");
    setLoading(Boolean(runId));
    if (!runId) return;
    void refresh();
    const timer = window.setInterval(() => {
      void refresh(true);
    }, 2000);
    return () => {
      window.clearInterval(timer);
      requestId.current += 1;
    };
  }, [runId, refresh]);

  return { data, error, loading, refresh };
}