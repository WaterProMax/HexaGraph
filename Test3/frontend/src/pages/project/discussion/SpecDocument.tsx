import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { DiscussionSession } from "../../../api/types";
import { matchesRejectedSpec, rejectedVersions } from "./specRevision";

/**
 * Read-only renderer for the approved discussion spec.
 *
 * Extracted from the SpecViewer dialog so the same document (latest approved
 * markdown + history versions) can be shown inline on the project task view.
 * It is display-only: approval/rejection stays in SpecApprovalDialog.
 */

type HistoryEntry = {
  session: DiscussionSession;
  version: number;
  label: "已批准" | "已打回";
};

function createdTime(session: DiscussionSession): number {
  const time = Date.parse(session.created_at);
  return Number.isFinite(time) ? time : 0;
}

function hasPackage(session: DiscussionSession): boolean {
  return session.decision_package !== null && session.decision_package !== undefined;
}

function statusLabel(session: DiscussionSession): "已批准" | "已打回" | null {
  if (session.status === "approved") return "已批准";
  if (session.status === "rejected") return "已打回";
  return null;
}

export function historyEntries(sessions: DiscussionSession[]): HistoryEntry[] {
  return sessions
    .map((session, index) => ({ session, version: index + 1, label: statusLabel(session) }))
    .filter((entry): entry is HistoryEntry => hasPackage(entry.session) && entry.label !== null)
    .sort((a, b) => createdTime(b.session) - createdTime(a.session));
}

export function latestApproved(sessions: DiscussionSession[]): DiscussionSession | null {
  const approved = sessions.filter(
    (session) => session.status === "approved" && hasPackage(session),
  );
  if (approved.length === 0) return null;
  return approved.reduce((latest, session) =>
    createdTime(session) >= createdTime(latest) ? session : latest,
  );
}

/** 1-based discussion version, matching the dialog's "第 N 次讨论" label. */
export function discussionVersion(session: DiscussionSession, sessions: DiscussionSession[]): number {
  return sessions.findIndex((entry) => entry.session_id === session.session_id) + 1;
}

export type SpecDocumentProps = {
  sessions: DiscussionSession[];
  className?: string;
};

export function SpecDocument({ sessions, className }: SpecDocumentProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const latest = latestApproved(sessions);
  const history = historyEntries(sessions);

  const selected = sessions.find((session) => session.session_id === selectedId);
  const current = selected && hasPackage(selected) ? selected : latest;
  const currentVersion = current ? discussionVersion(current, sessions) : 0;
  const rejected = current ? rejectedVersions(current, sessions) : [];
  const priorFeedback =
    current?.status === "rejected" ? current.resolution_comment : rejected[0]?.resolution_comment;

  return (
    <div className={`disc-spec-document${className ? ` ${className}` : ""}`}>
      <div className="disc-spec-current" data-testid="disc-spec-current">
        {current && current.decision_package ? (
          <>
            <div className="disc-spec-meta">
              <span>版本：第 {currentVersion} 次讨论</span>
              {statusLabel(current) && (
                <span className="disc-spec-status">{statusLabel(current)}</span>
              )}
            </div>
            <div className="disc-spec-body">
              {priorFeedback && (
                <p className="disc-revision-note">
                  <strong>{current.status === "rejected" ? "驳回意见" : "上次驳回意见"}</strong>{" "}
                  {priorFeedback}
                </p>
              )}
              {current.status === "approved" && matchesRejectedSpec(current, rejected) && (
                <p className="disc-revision-note">此历史版本的正文与被打回版本相同。</p>
              )}
              <ReactMarkdown>{current.decision_package.body_md}</ReactMarkdown>
            </div>
          </>
        ) : (
          <p className="disc-dialog-empty">还没有已批准的规格</p>
        )}
      </div>

      {history.length > 0 && (
        <section className="disc-spec-history" aria-labelledby="disc-spec-history-title">
          <h3 id="disc-spec-history-title">历史版本</h3>
          <ul className="disc-spec-history-list" data-testid="disc-spec-history">
            {history.map((entry) => {
              const active = current !== null && entry.session.session_id === current.session_id;
              return (
                <li key={entry.session.session_id}>
                  <button
                    type="button"
                    className={`disc-spec-history-item${active ? " disc-spec-history-item--active" : ""}`}
                    aria-pressed={active}
                    onClick={() => setSelectedId(entry.session.session_id)}
                  >
                    <span>第 {entry.version} 次讨论</span>
                    <span
                      className={`disc-spec-history-status${
                        entry.label === "已打回" ? " disc-spec-history-status--rejected" : ""
                      }`}
                    >
                      {entry.label}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}

export default SpecDocument;