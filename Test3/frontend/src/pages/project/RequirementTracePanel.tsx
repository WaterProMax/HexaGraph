import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";

/** One trace link exactly as `GET /api/runs/{run_id}/trace` returns it. */
export type TraceLink = {
  from: string;
  to: string;
  kind: string;
  version: string;
};

type TraceLoadState = "loading" | "ready" | "error";

/**
 * The backend returns `TraceGraph.matrix()` as a flat list. Accept a bare list
 * and, defensively, an object that wraps the list in `links`; never throw on an
 * unexpected shape — the panel is read-only evidence, not a validator.
 */
export function normalizeTraceLinks(raw: unknown): TraceLink[] {
  const wrapped = raw as { links?: unknown } | null;
  const list = Array.isArray(raw) ? raw : Array.isArray(wrapped?.links) ? wrapped?.links : [];
  return (list as unknown[])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      from: item.from != null ? String(item.from) : "",
      to: item.to != null ? String(item.to) : "",
      kind: item.kind != null ? String(item.kind) : "",
      version: item.version != null ? String(item.version) : "",
    }))
    .filter((link) => link.from || link.to);
}

/**
 * Requirements/spec-items → tasks orchestration trace, backed by the existing
 * `GET /api/runs/{run_id}/trace` API (`TraceGraph.matrix()`). This is NOT the
 * execution-step view: step-level traces live in 执行监控.
 */
export function RequirementTracePanel({ runId }: { runId: string }) {
  const [state, setState] = useState<TraceLoadState>("loading");
  const [links, setLinks] = useState<TraceLink[]>([]);
  const requestRef = useRef(0);

  useEffect(() => {
    const request = requestRef.current + 1;
    requestRef.current = request;
    let cancelled = false;

    if (!runId) {
      setLinks([]);
      setState("ready");
      return () => {
        cancelled = true;
      };
    }

    setState("loading");
    setLinks([]);
    api
      .trace(runId)
      .then((raw: unknown) => {
        if (cancelled || requestRef.current !== request) return;
        setLinks(normalizeTraceLinks(raw));
        setState("ready");
      })
      .catch(() => {
        if (cancelled || requestRef.current !== request) return;
        setLinks([]);
        setState("error");
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <section
      className="requirement-trace"
      data-testid="requirement-trace-panel"
      aria-labelledby="requirement-trace-heading"
      aria-busy={state === "loading"}
      style={{ marginBottom: 16 }}
    >
      <div className="section-title">
        <span id="requirement-trace-heading">需求追溯</span>
        <span className="hint">需求 / 规格项 → 任务</span>
      </div>
      <p className="muted" style={{ margin: "0 0 12px" }}>
        这是需求/规格项到任务的编排追溯，执行步骤见执行监控。
      </p>

      {state === "loading" && (
        <p className="muted" role="status" data-testid="requirement-trace-loading">
          正在载入追溯链路…
        </p>
      )}

      {state === "error" && (
        <div className="well" role="alert" data-testid="requirement-trace-error" style={{ padding: "10px 12px" }}>
          暂时无法载入追溯链路，请稍后重试。
        </div>
      )}

      {state === "ready" && links.length === 0 && (
        <p className="muted" data-testid="requirement-trace-empty" style={{ margin: 0 }}>
          还没有追溯链路。任务由已批准规格物化后会出现规格项 → 任务的连线。
        </p>
      )}

      {state === "ready" && links.length > 0 && (
        <div
          className="well"
          // Hundreds of links must not push the activity stream off the page.
          style={{ padding: "4px 8px", overflow: "auto", maxHeight: 320 }}
          data-testid="requirement-trace-scroll"
        >
          <table className="disc-score-table" data-testid="requirement-trace-table">
            <caption className="muted" style={{ captionSide: "top", textAlign: "left", padding: "6px 0", fontSize: 11 }}>
              共 {links.length} 条连线
            </caption>
            <thead>
              <tr>
                <th scope="col">来源（from）</th>
                <th scope="col">去向（to）</th>
                <th scope="col">关系（kind）</th>
                <th scope="col">版本（version）</th>
              </tr>
            </thead>
            <tbody>
              {links.map((link, index) => (
                <tr key={`${link.from}-${link.to}-${link.kind}-${index}`} data-testid="requirement-trace-link">
                  <th scope="row" className="mono">
                    {link.from || "—"}
                  </th>
                  <td className="mono" style={{ textAlign: "left" }}>
                    {link.to || "—"}
                  </td>
                  <td style={{ textAlign: "left" }}>{link.kind || "—"}</td>
                  <td className="mono" style={{ textAlign: "left" }}>
                    {link.version || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}