import { useEffect, useRef, useState } from "react";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  ReviewBallot,
} from "../../../api/types";
import { BotAvatar } from "../../../components/BotAvatar";
import { resolveBubbleBot } from "./MessageBubble";

export type ScorePanelProps = {
  session: DiscussionSession;
  reviews: ReviewBallot[];
  messages: DiscussionMessage[];
  bots: BotInstance[];
  busy?: boolean;
  showControls?: boolean;
  onPause: () => void;
  onResume: (skipBotIds?: string[]) => void;
  onTerminate: () => void;
};

const HARD_GATES = [
  ["coverage", "覆盖"],
  ["conflicts_closed_or_recorded", "冲突已关闭或记录"],
  ["evidence_complete", "证据完整"],
] as const;

function sumScores(scores: Record<string, number> | undefined | null): number {
  return Object.values(scores ?? {}).reduce<number>(
    (total, value) => total + (typeof value === "number" ? value : 0),
    0,
  );
}



function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatAverage(value: number): string {
  return value.toFixed(1);
}

type ProposalRow = {
  proposalId: string;
  authorId: string;
  totals: Map<string, number>;
  average: number | null;
};

export function ScorePanel({
  session,
  reviews,
  messages,
  bots,
  busy = false,
  showControls = true,
  onPause,
  onResume,
  onTerminate,
}: ScorePanelProps) {
  const botName = (botId: string) => bots.find((bot) => bot.bot_id === botId)?.display_name || botId;

  const proposalAuthor = new Map<string, string>();
  const proposalOrder: string[] = [];
  const roundOrder: string[] = [];
  for (const message of messages) {
    if (message.kind !== "proposal") continue;
    const proposalId =
      typeof message.payload?.proposal_id === "string" ? message.payload.proposal_id : "";
    if (!proposalId) continue;
    if (!proposalAuthor.has(proposalId)) {
      proposalAuthor.set(proposalId, message.bot_id || "");
      proposalOrder.push(proposalId);
    }
    const round = Number(message.payload?.round ?? message.round);
    if (round === session.current_round && !roundOrder.includes(proposalId)) {
      roundOrder.push(proposalId);
    }
  }

  const ballotsByProposal = new Map<string, Map<string, number>>();
  const reviewers: string[] = [];
  for (const ballot of reviews) {
    if (!ballotsByProposal.has(ballot.proposal_id)) {
      ballotsByProposal.set(ballot.proposal_id, new Map());
    }
    ballotsByProposal.get(ballot.proposal_id)!.set(ballot.reviewer_bot_id, sumScores(ballot.scores));
    if (!reviewers.includes(ballot.reviewer_bot_id)) reviewers.push(ballot.reviewer_bot_id);
  }

  const rowOrder = roundOrder.length > 0 ? [...roundOrder] : [...proposalOrder];
  for (const proposalId of ballotsByProposal.keys()) {
    if (!rowOrder.includes(proposalId)) rowOrder.push(proposalId);
  }

  const rows: ProposalRow[] = rowOrder.map((proposalId) => {
    const totals = ballotsByProposal.get(proposalId) ?? new Map<string, number>();
    const scored = [...totals.values()];
    const average =
      scored.length > 0 ? scored.reduce((sum, value) => sum + value, 0) / scored.length : null;
    return {
      proposalId,
      authorId: proposalAuthor.get(proposalId) || "",
      totals,
      average,
    };
  });

  const averages = rows
    .map((row) => row.average)
    .filter((value): value is number => value !== null);
  const gap =
    averages.length > 0 ? Math.max(...averages) - Math.min(...averages) : null;

  const threshold =
    typeof session.budget?.score_gap_threshold === "number"
      ? session.budget.score_gap_threshold
      : null;

  let gapClass = "is-muted";
  if (gap !== null && threshold !== null) {
    gapClass = gap <= threshold ? "is-ok" : "is-over";
  }

  const gateStates = HARD_GATES.map(([key, label]) => ({
    key,
    label,
    passed: reviews.length > 0 && reviews.every((ballot) => ballot.hard_gate_results?.[key] === true),
  }));
  const passedGates = gateStates.filter((gate) => gate.passed).length;

  const lastSystem = [...messages].reverse().find((message) => message.kind === "system");
  const failed = lastSystem?.payload?.event === "bot_failed";
  const failedBotId = failed
    ? typeof lastSystem?.payload?.bot_id === "string"
      ? lastSystem.payload.bot_id
      : lastSystem?.bot_id || ""
    : "";
  const failureCategory = failed
    ? String(
        lastSystem?.payload?.error_category ??
          lastSystem?.payload?.reason ??
          lastSystem?.payload?.detail ??
          "未知原因",
      )
    : "";

  const maxRounds = session.budget?.max_rounds;

  return (
    <section
      className="disc-score-panel"
      aria-labelledby="disc-score-heading"
      aria-busy={busy || undefined}
      data-testid="disc-score-panel"
    >
      <div className="disc-score-head">
        <h2 id="disc-score-heading" className="disc-score-title">
          评分
        </h2>
        <span className="disc-round">
          第 {session.current_round} / {maxRounds ?? "—"} 轮
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="disc-empty">还没有评分票</p>
      ) : (
        <div className="disc-score-table-wrap">
          <table className="disc-score-table">
            <thead>
              <tr>
                <th scope="col">方案作者</th>
                {reviewers.map((reviewerId) => {
                  const name = botName(reviewerId);
                  return (
                    <th scope="col" key={reviewerId} title={name}>
                      <span className="disc-score-reviewer">{name}</span>
                    </th>
                  );
                })}
                <th scope="col">平均总分</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const author = row.authorId ? botName(row.authorId) : "未知作者";
                return (
                  <tr key={row.proposalId} data-proposal-id={row.proposalId}>
                    <th scope="row">
                      <span className="disc-score-author" title={author}>{author}</span>
                      <span className="disc-score-proposal mono" title={row.proposalId}>{row.proposalId}</span>
                    </th>
                    {reviewers.map((reviewerId) => {
                      const total = row.totals.get(reviewerId);
                      return (
                        <td key={reviewerId} className="disc-score-cell">
                          {typeof total === "number" ? formatScore(total) : "—"}
                        </td>
                      );
                    })}
                    <td className="disc-score-cell disc-score-average">
                      {row.average === null ? "—" : formatAverage(row.average)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className={`disc-gap ${gapClass}`} data-testid="disc-gap">
        {gap === null ? (
          <span>分差 —</span>
        ) : threshold === null ? (
          <span>仅硬门槛</span>
        ) : (
          <span>
            分差 {formatScore(gap)} / 阈值 {formatScore(threshold)}
          </span>
        )}
      </div>

      <div className="disc-gates" data-testid="disc-gates">
        <div className="disc-gates-head">
          <span>硬门槛</span>
          <span className="disc-gates-count">
            {passedGates}/{HARD_GATES.length}
          </span>
        </div>
        <ul className="disc-gates-list">
          {gateStates.map((gate) => (
            <li
              key={gate.key}
              className={`disc-gate ${gate.passed ? "is-ok" : "is-over"}`}
              data-gate={gate.key}
            >
              <span className="disc-gate-mark" aria-hidden>
                {gate.passed ? "✓" : "✗"}
              </span>
              <span>{gate.label}</span>
              <span className="disc-gate-state">{gate.passed ? "通过" : "未通过"}</span>
            </li>
          ))}
        </ul>
      </div>

      {failed && (
        <div className="disc-failure" role="alert" data-testid="disc-bot-failed">
          <div className="disc-failure-head">
            {failedBotId ? (
              <BotAvatar
                bot={resolveBubbleBot(bots, failedBotId)}
                size={26}
                className="disc-avatar"
              />
            ) : null}
            <p className="disc-failure-text">
              Bot 调用失败：{failedBotId ? botName(failedBotId) : "该 Bot"}（{failureCategory}）
            </p>
          </div>
          <div className="disc-failure-actions">
            <button type="button" className="disc-btn" disabled={busy} onClick={() => onResume()}>
              重试
            </button>
            <button
              type="button"
              className="disc-btn disc-btn-quiet"
              disabled={busy}
              onClick={() => onResume([failedBotId])}
            >
              跳过此 Bot
            </button>
          </div>
        </div>
      )}

      {showControls && (
        <DiscussionControls session={session} busy={busy} onPause={onPause} onResume={onResume} onTerminate={onTerminate} />
      )}
    </section>
  );
}

export default ScorePanel;
export function DiscussionControls({ session, busy, onPause, onResume, onTerminate }: Pick<
  ScorePanelProps, "session" | "busy" | "onPause" | "onResume" | "onTerminate"
>) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!confirmOpen) return;
    dialogRef.current?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") setConfirmOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [confirmOpen]);

  return (
    <>
      <div className="disc-actions">
        <button
          type="button"
          className="disc-btn"
          disabled={busy}
          onClick={() => (session.paused ? onResume() : onPause())}
        >
          {session.paused ? "继续" : "暂停"}
        </button>
        <button
          type="button"
          className="disc-btn disc-btn-danger"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
        >
          终止
        </button>
      </div>

      {confirmOpen && (
        <div
          className="disc-dialog-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) setConfirmOpen(false);
          }}
        >
          <div
            className="disc-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="disc-terminate-title"
            aria-describedby="disc-terminate-desc"
            tabIndex={-1}
            ref={dialogRef}
            data-testid="disc-terminate-dialog"
          >
            <h3 id="disc-terminate-title" className="disc-dialog-title">
              终止这场讨论？
            </h3>
            <p id="disc-terminate-desc" className="disc-dialog-text">
              终止后讨论立即结束，已产生的消息和评分会保留，此操作不可撤销。
            </p>
            <div className="disc-dialog-actions">
              <button
                type="button"
                className="disc-btn disc-btn-quiet"
                onClick={() => setConfirmOpen(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="disc-btn disc-btn-danger"
                disabled={busy}
                onClick={() => {
                  setConfirmOpen(false);
                  onTerminate();
                }}
              >
                确认终止
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
