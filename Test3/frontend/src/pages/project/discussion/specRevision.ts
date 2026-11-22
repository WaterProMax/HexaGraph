import type { DiscussionSession } from "../../../api/types";

export function rejectedVersions(session: DiscussionSession, sessions: DiscussionSession[]): DiscussionSession[] {
  const byId = new Map(sessions.map((entry) => [entry.session_id, entry]));
  const visited = new Set([session.session_id]);
  const rejected: DiscussionSession[] = [];
  let previousId = session.previous_session_id;
  while (previousId && !visited.has(previousId)) {
    visited.add(previousId);
    const previous = byId.get(previousId);
    if (!previous || previous.project_id !== session.project_id) break;
    if (previous.status === "rejected" && previous.decision_package) rejected.push(previous);
    previousId = previous.previous_session_id;
  }
  return rejected;
}

export function matchesRejectedSpec(session: DiscussionSession, rejected: DiscussionSession[]): boolean {
  const body = session.decision_package?.body_md.trim().replace(/\s+/g, " ");
  return Boolean(body && rejected.some((previous) =>
    previous.decision_package?.body_md.trim().replace(/\s+/g, " ") === body,
  ));
}
