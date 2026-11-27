import { Input } from "antd";
import { useMemo } from "react";
import type { EventConnection } from "../../hooks/useRunEvents";
import { eventLabel } from "./runMonitor";
import { eventSummary, eventTaskCode, type TimelineEvent } from "./eventTimeline";

/**
 * Presentational full run-event timeline. It owns no data source so the project
 * page can render it inline (activity tab / demo workbench) with the same events
 * the monitor already subscribes to — one EventSource per screen.
 *
 * Kept testid-compatible with the original `/runs/:id/timeline` page:
 * timeline-events / timeline-event / timeline-event-label /
 * timeline-event-summary / timeline-count / timeline-empty /
 * timeline-connection-error.
 */
export type RunEventTimelineProps = {
  events: TimelineEvent[];
  connection: EventConnection;
  connectionError: string;
  reconnect: () => void;
  taskFilter: string;
  onTaskFilterChange: (value: string) => void;
  /** Dense layout for the classroom grid (smaller paddings, same content). */
  compact?: boolean;
};

export function RunEventTimeline({
  events,
  connection,
  connectionError,
  reconnect,
  taskFilter,
  onTaskFilterChange,
  compact = false,
}: RunEventTimelineProps) {
  const rows = useMemo(() => {
    const query = taskFilter.trim().toLowerCase();
    return (Array.isArray(events) ? events : [])
      .map((event) => {
        const kind = String(event.kind || "");
        return {
          event,
          taskCode: eventTaskCode(event),
          label: eventLabel(kind),
          summary: eventSummary(kind, event.payload),
        };
      })
      .filter((row) => !query || row.taskCode.toLowerCase().includes(query));
  }, [events, taskFilter]);

  return (
    <div className={`run-event-timeline${compact ? " is-compact" : ""}`} data-testid="run-event-timeline">
      {connection === "error" && (
        <div
          className="well"
          role="alert"
          data-testid="timeline-connection-error"
          style={{ padding: compact ? "6px 10px" : "10px 12px", marginBottom: compact ? 8 : 12 }}
        >
          {connectionError || "事件连接已断开"}
          <button type="button" className="chip" style={{ marginLeft: 8 }} onClick={reconnect}>
            重新连接
          </button>
        </div>
      )}

      {compact ? (
        <div className="run-event-head">
          <div className="run-event-head-main">
            <span className="run-event-title">事件时间线</span>
            <span className="hint" data-testid="timeline-count">
              共 {rows.length} 条
              {taskFilter.trim() ? `（已按 ${taskFilter.trim()} 过滤）` : ""}
            </span>
          </div>
          <Input
            allowClear
            size="small"
            className="run-event-filter-input"
            aria-label="按任务代码过滤"
            placeholder="过滤任务代码，如 T-01"
            value={taskFilter}
            onChange={(event) => onTaskFilterChange(event.target.value)}
          />
        </div>
      ) : (
        <>
          <div className="section-title">
            <span>事件时间线</span>
            <span className="hint" data-testid="timeline-count">
              共 {rows.length} 条
              {taskFilter.trim() ? `（已按 ${taskFilter.trim()} 过滤）` : ""}
            </span>
          </div>

          <label className="run-event-filter">
            <span className="muted">按任务代码过滤（事件的 subject）</span>
            <Input
              allowClear
              aria-label="按任务代码过滤"
              placeholder="按任务代码过滤，如 T-01"
              value={taskFilter}
              onChange={(event) => onTaskFilterChange(event.target.value)}
            />
          </label>
        </>
      )}

      {connection === "connecting" && (
        <p className="muted" role="status">
          正在连接事件流…
        </p>
      )}

      {rows.length === 0 ? (
        <p className="muted" data-testid="timeline-empty">
          {taskFilter.trim() ? "没有匹配该任务代码的事件。" : "暂无事件。"}
        </p>
      ) : (
        <ol
          className="activity-events"
          data-testid="timeline-events"
          style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: compact ? 4 : 6 }}
        >
          {rows.map(({ event, taskCode, label, summary }) => (
            <li
              className="event"
              key={event.seq ?? `${event.kind}-${taskCode}-${event.subject ?? ""}`}
              data-testid="timeline-event"
              data-task-code={taskCode}
            >
              <span className="seq">#{event.seq ?? "—"}</span>
              <div style={{ minWidth: 0 }}>
                <span className="kind" data-testid="timeline-event-label">
                  {label}
                </span>
                {taskCode && (
                  <span className="mono muted" style={{ marginLeft: 8 }}>
                    {taskCode}
                  </span>
                )}
                {summary && (
                  <div className="payload muted" data-testid="timeline-event-summary" title={summary}>
                    {summary}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default RunEventTimeline;