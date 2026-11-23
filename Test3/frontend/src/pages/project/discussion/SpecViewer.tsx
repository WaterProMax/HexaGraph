import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { DiscussionSession } from "../../../api/types";
import { matchesRejectedSpec, rejectedVersions } from "./specRevision";

export type SpecViewerProps = {
  open: boolean;
  onClose: () => void;
  sessions: DiscussionSession[];
};

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

function historyEntries(sessions: DiscussionSession[]): HistoryEntry[] {
  return sessions
    .map((session, index) => ({ session, version: index + 1, label: statusLabel(session) }))
    .filter((entry): entry is HistoryEntry => hasPackage(entry.session) && entry.label !== null)
    .sort((a, b) => createdTime(b.session) - createdTime(a.session));
}

function latestApproved(sessions: DiscussionSession[]): DiscussionSession | null {
  const approved = sessions.filter(
    (session) => session.status === "approved" && hasPackage(session),
  );
  if (approved.length === 0) return null;
  return approved.reduce((latest, session) =>
    createdTime(session) >= createdTime(latest) ? session : latest,
  );
}

function shortHash(session: DiscussionSession): string {
  return (session.decision_package?.sha256 ?? "").slice(0, 8);
}

export function SpecViewer({ open, onClose, sessions }: SpecViewerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const latest = latestApproved(sessions);
  const history = historyEntries(sessions);

  useEffect(() => {
    if (open) setSelectedId(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const selected = sessions.find((session) => session.session_id === selectedId);
  const current = selected && hasPackage(selected) ? selected : latest;
  const currentVersion = current ? sessions.findIndex((session) => session === current) + 1 : 0;
  const rejected = current ? rejectedVersions(current, sessions) : [];
  const priorFeedback = current?.status === "rejected" ? current.resolution_comment : rejected[0]?.resolution_comment;

  return (
    <div
      className="disc-dialog-mask"
      data-testid="disc-spec-mask"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="disc-dialog disc-spec-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="disc-spec-title"
        data-testid="disc-spec-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="disc-dialog-head">
          <h2 id="disc-spec-title">需求规格</h2>
          <button type="button" className="disc-dialog-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="disc-spec-current" data-testid="disc-spec-current">
          {current && current.decision_package ? (
            <>
              <div className="disc-spec-meta">
                <span>版本：第 {currentVersion} 次讨论</span>
                <span className="disc-spec-hash" title={current.decision_package.sha256}>
                  摘要 {shortHash(current)}
                </span>
                {statusLabel(current) && (
                  <span className="disc-spec-status">{statusLabel(current)}</span>
                )}
              </div>
              <div className="disc-spec-body">
                {priorFeedback && (
                  <p className="disc-revision-note">
                    <strong>{current.status === "rejected" ? "驳回意见" : "上次驳回意见"}</strong> {priorFeedback}
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
                const active =
                  current !== null && entry.session.session_id === current.session_id;
                return (
                  <li key={entry.session.session_id}>
                    <button
                      type="button"
                      className={`disc-spec-history-item${
                        active ? " disc-spec-history-item--active" : ""
                      }`}
                      aria-pressed={active}
                      onClick={() => setSelectedId(entry.session.session_id)}
                    >
                      <span>第 {entry.version} 次讨论</span>
                      <span
                        className={`disc-spec-history-status${
                          entry.label === "已打回"
                            ? " disc-spec-history-status--rejected"
                            : ""
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
    </div>
  );
}

export default SpecViewer;
