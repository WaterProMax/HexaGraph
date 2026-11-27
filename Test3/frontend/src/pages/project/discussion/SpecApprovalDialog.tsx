import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { matchesRejectedSpec, rejectedVersions } from "./specRevision";
import { ApiError, api } from "../../../api/client";
import type { DiscussionSession, ReviewBallot } from "../../../api/types";

export type SpecApprovalDialogProps = {
  open: boolean;
  projectId: string;
  actorBotId: string;
  session: DiscussionSession;
  sessions?: DiscussionSession[];
  reviews: ReviewBallot[];
  onClose: () => void;
  onApproved: (updated: DiscussionSession) => void;
  onRestarted: (created: DiscussionSession) => void;
};

type ScoreRow = {
  proposalId: string;
  average: number;
  votes: number;
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "操作失败，请稍后重试";
}

function ballotTotal(ballot: ReviewBallot): number {
  return Object.values(ballot.scores ?? {}).reduce(
    (sum, score) => sum + (Number.isFinite(score) ? Number(score) : 0),
    0,
  );
}

function summaryRows(reviews: ReviewBallot[]): ScoreRow[] {
  const grouped = new Map<string, { sum: number; votes: number }>();
  for (const ballot of reviews) {
    const entry = grouped.get(ballot.proposal_id) ?? { sum: 0, votes: 0 };
    entry.sum += ballotTotal(ballot);
    entry.votes += 1;
    grouped.set(ballot.proposal_id, entry);
  }
  return [...grouped.entries()]
    .map(([proposalId, entry]) => ({
      proposalId,
      average: entry.votes ? entry.sum / entry.votes : 0,
      votes: entry.votes,
    }))
    .sort((a, b) => a.proposalId.localeCompare(b.proposalId));
}

function passedGateCount(reviews: ReviewBallot[]): number {
  const gates = new Set<string>();
  for (const ballot of reviews) {
    for (const gate of Object.keys(ballot.hard_gate_results ?? {})) gates.add(gate);
  }
  return [...gates].filter((gate) =>
    reviews.every((ballot) => ballot.hard_gate_results?.[gate] === true),
  ).length;
}

function spreadLabel(rows: ScoreRow[], threshold: number | null): string {
  if (rows.length === 0) return "分差 —";
  const averages = rows.map((row) => row.average);
  const spread = Math.max(...averages) - Math.min(...averages);
  const base = `分差 ${spread.toFixed(1)}`;
  return threshold === null ? base : `${base} / 阈值 ${threshold.toFixed(1)}`;
}

export function SpecApprovalDialog({
  open,
  projectId,
  actorBotId,
  session,
  sessions = [],
  reviews,
  onClose,
  onApproved,
  onRestarted,
}: SpecApprovalDialogProps) {
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rejectRef = useRef<HTMLTextAreaElement | null>(null);
  const busy = approving || rejecting;

  useEffect(() => {
    if (!open) return;
    setApproving(false);
    setRejecting(false);
    setShowReject(false);
    setRejectComment("");
    setError(null);
  }, [open, session.session_id]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (showReject) rejectRef.current?.focus();
  }, [showReject]);

  const packageData = session.decision_package;
  if (!open || !packageData) return null;

  const rows = summaryRows(reviews);
  const passedGates = passedGateCount(reviews);
  const dissentCount = packageData.dissent_items?.length ?? 0;
  const threshold =
    typeof session.budget.score_gap_threshold === "number"
      ? session.budget.score_gap_threshold
      : null;
  const rejectCommentValid = rejectComment.trim().length > 0;
  const rejected = rejectedVersions(session, sessions);
  const unchanged = matchesRejectedSpec(session, rejected);
  const priorFeedback = rejected[0]?.resolution_comment;

  async function approve() {
    if (busy || unchanged) return;
    setError(null);
    setApproving(true);
    try {
      const updated = await api.resolveDiscussion(
        session.session_id,
        { decision: "approved" },
        actorBotId,
      );
      onApproved(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setApproving(false);
    }
  }

  async function rejectAndRestart() {
    const comment = rejectComment.trim();
    if (!comment || busy) return;
    setError(null);
    setRejecting(true);
    try {
      await api.resolveDiscussion(
        session.session_id,
        { decision: "rejected", comment },
        actorBotId,
      );
      const created = await api.createDiscussionSession(
        projectId,
        {
          leader_bot_id: session.leader_bot_id,
          participant_bot_ids: session.participant_bot_ids,
          requirement_snapshot: session.requirement_text,
          previous_session_id: session.session_id,
        },
        actorBotId,
      );
      await api.runDiscussion(created.session_id, actorBotId);
      onRestarted(created);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRejecting(false);
    }
  }

  return (
    <div
      className="disc-dialog-mask"
      data-testid="disc-approval-mask"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="disc-dialog disc-approval-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="disc-approval-title"
        data-testid="disc-approval-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="disc-dialog-head">
          <h2 id="disc-approval-title">需求规格待你审批</h2>
          <button type="button" className="disc-dialog-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="disc-dialog-summary" aria-label="审批摘要">
          <span className="disc-summary-chip">第 {session.current_round} 轮</span>
          <span className="disc-summary-chip">{spreadLabel(rows, threshold)}</span>
          <span className="disc-summary-chip">硬门槛 {passedGates}/3</span>
          <span className="disc-summary-chip">未解决分歧 {dissentCount} 条</span>
        </div>

        <div className="disc-dialog-body">
          {priorFeedback && <p className="disc-revision-note"><strong>上次驳回意见</strong> {priorFeedback}</p>}
          {unchanged && <p className="disc-view-error" role="alert">本版正文与被打回版本相同，请先修改需求规格。</p>}
          <ReactMarkdown>{packageData.body_md}</ReactMarkdown>
        </div>

        <details className="disc-dialog-fold" open={dissentCount > 0}>
          <summary>未解决分歧（{dissentCount}）</summary>
          {dissentCount === 0 ? (
            <p className="disc-dialog-empty">无</p>
          ) : (
            <ul className="disc-dissent-list">
              {packageData.dissent_items.map((item, index) => (
                <li key={`${index}-${item}`}>{item}</li>
              ))}
            </ul>
          )}
        </details>

        <details className="disc-dialog-fold">
          <summary>评分汇总</summary>
          {rows.length === 0 ? (
            <p className="disc-dialog-empty">还没有评分。</p>
          ) : (
            <table className="disc-score-table">
              <thead>
                <tr>
                  <th scope="col">作者</th>
                  <th scope="col">平均总分</th>
                  <th scope="col">票数</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.proposalId}>
                    <td className="disc-score-author" title={row.proposalId}>
                      {row.proposalId}
                    </td>
                    <td>{row.average.toFixed(1)}</td>
                    <td>{row.votes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </details>

        {showReject && (
          <section className="disc-reject">
            <label className="disc-reject-label" htmlFor="disc-reject-comment">
              打回意见（必填）
            </label>
            <textarea
              id="disc-reject-comment"
              ref={rejectRef}
              className="disc-reject-input"
              aria-label="打回意见"
              value={rejectComment}
              rows={3}
              disabled={busy}
              onChange={(event) => setRejectComment(event.target.value)}
            />
            <div className="disc-reject-actions">
              <button
                type="button"
                className="disc-button-secondary"
                disabled={busy}
                onClick={() => {
                  setShowReject(false);
                  setRejectComment("");
                }}
              >
                取消
              </button>
              <button
                type="button"
                className="disc-button-secondary disc-button-danger"
                disabled={!rejectCommentValid || busy}
                onClick={rejectAndRestart}
              >
                {rejecting ? "处理中…" : "确认打回并重新讨论"}
              </button>
            </div>
          </section>
        )}

        {error && (
          <p className="disc-dialog-error" role="alert">
            {error}
          </p>
        )}

        <footer className="disc-dialog-actions">
          <button
            type="button"
            className="disc-button-secondary"
            disabled={busy}
            onClick={() => setShowReject((visible) => !visible)}
          >
            打回重新讨论
          </button>
          <button
            type="button"
            className="disc-button-primary"
            disabled={busy || unchanged}
            onClick={approve}
          >
            {approving ? "提交中…" : "通过，进入设计规格"}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default SpecApprovalDialog;
