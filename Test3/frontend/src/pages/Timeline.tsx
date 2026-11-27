import { useState } from "react";
import { useParams } from "react-router-dom";
import { useRunEvents } from "../hooks/useRunEvents";
import { RunEventTimeline } from "./project/RunEventTimeline";

/**
 * `/runs/:id/timeline` deep link. The presentational timeline lives in
 * RunEventTimeline and is embedded on the project main path; this route keeps
 * the same component addressable for run-detail navigation.
 */
export default function Timeline() {
  const { id } = useParams();
  const { events, connection, connectionError, reconnect } = useRunEvents(id);
  const [taskFilter, setTaskFilter] = useState("");

  return (
    <div className="stack" style={{ padding: 16 }}>
      <RunEventTimeline
        events={events}
        connection={connection}
        connectionError={connectionError}
        reconnect={reconnect}
        taskFilter={taskFilter}
        onTaskFilterChange={setTaskFilter}
      />
    </div>
  );
}

export { eventTaskCode, stepSummary, eventSummary } from "./project/eventTimeline";
export type { TimelineEvent } from "./project/eventTimeline";