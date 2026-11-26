import { useEffect, useRef, useState } from "react";
import type {
  BotInstance,
  DiscussionMessage,
  DiscussionSession,
  ReviewBallot,
} from "../../../api/types";
import { BotAvatar } from "../../../components/BotAvatar";
import { discussionControlFlags } from "./deriveStage";
import { resolveBubbleBot } from "./MessageBubble";

/** Which write request is currently in flight, for honest button labels. */
export type DiscussionPendingAction =
  | "pause"
  | "resume"
  | "intervene"
  | "end-round"
  | "start-round"
  | "terminate"
  | "supplement";

export type ScorePanelProps = {
  session: DiscussionSession;
  reviews: ReviewBallot[];
  messages: DiscussionMessage[];
  bots: BotInstance[];
  busy?: boolean;
  showControls?: boolean;
  /** Only the session leader may write; the server remains authoritative. */
  canControl?: boolean;
  pendingAction?: DiscussionPendingAction | null;
  onPause: () => void;
  onResume: (skipBotIds?: string[]) => void;
  onTerminate: () => void;
  onIntervene?: (text: string) => Promise<boolean | undefined> | boolean;
  onEndRound?: (reason: string) => Promise<boolean | undefined> | boolean;
  onStartRound?: () => void;
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
  canControl = true,
  pendingAction = null,
  onPause,
  onResume,
  onTerminate,
  onIntervene,
  onEndRound,
  onStartRound,
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
        <DiscussionControls
          session={session}
          busy={busy}
          canControl={canControl}
          pendingAction={pendingAction}
          onPause={onPause}
          onResume={onResume}
          onTerminate={onTerminate}
          onIntervene={onIntervene}
          onEndRound={onEndRound}
          onStartRound={onStartRound}
        />
      )}
    </section>
  );
}

export default ScorePanel;

/**
 * Shared focus/keyboard behaviour for the three confirmation dialogs: focus the
 * dialog when it opens, close on Escape, and keep the Escape listener scoped to
 * the open dialog. `onClose` is read through a ref so typing inside a dialog
 * field cannot re-run the focus effect (which would steal focus on every key).
 */
function useDialogKeyboard(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    ref.current?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  return ref;
}

export function DiscussionControls({
  session,
  busy = false,
  canControl = true,
  pendingAction = null,
  onPause,
  onResume,
  onTerminate,
  onIntervene,
  onEndRound,
  onStartRound,
}: Pick<ScorePanelProps, "session" | "busy" | "canControl" | "pendingAction" | "onPause" | "onResume" | "onTerminate"> & {
  onIntervene?: (text: string) => Promise<boolean | undefined> | boolean;
  onEndRound?: (reason: string) => Promise<boolean | undefined> | boolean;
  onStartRound?: () => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [endOpen, setEndOpen] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  const [intervention, setIntervention] = useState("");
  const [endReason, setEndReason] = useState("");
  const confirmRef = useDialogKeyboard(confirmOpen, () => setConfirmOpen(false));
  const endRef = useDialogKeyboard(endOpen, () => setEndOpen(false));
  const startRef = useDialogKeyboard(startOpen, () => setStartOpen(false));

  const { terminal, manual, settledManual, roundsAvailable, manualPending } =
    discussionControlFlags(session);
  const pausing = Boolean(session.pause_requested) && !session.paused;
  const hasRevision = session.control_revision !== undefined;
  // A terminal discussion keeps its history and scores but offers no action.
  if (terminal) return null;
  if (!canControl) {
    return (
      <span className="disc-control-readonly" data-testid="disc-control-readonly" role="status">
        只有本场讨论的 Leader 可以操作。
      </span>
    );
  }

  const mayStartRound = settledManual && roundsAvailable && hasRevision && !busy;
  const pauseLabel =
    pendingAction === "pause"
      ? "正在请求暂停…"
      : pendingAction === "resume"
        ? "正在请求继续…"
        : pausing
          ? "正在暂停…"
          : session.paused
            ? "继续"
            : "暂停";

  return (
    <>
      {manual && (
        <div className="disc-manual-end" role="status" data-testid="disc-manual-end">
          人工结束本轮（未自动收敛、未批准）。
          {settledManual ? " 已安全停止。" : " 正在等待安全检查点完成。"}
          {settledManual && !roundsAvailable
            ? " 轮数预算已用尽，不能开始新一轮；可查看历史或补充需求。"
            : ""}
          {settledManual && !hasRevision ? " 控制版本缺失，请刷新后重试。" : ""}
        </div>
      )}
      {manualPending && (
        <div className="disc-manual-ending" role="status" data-testid="disc-manual-ending">
          正在结束本轮，等待安全检查点完成…
        </div>
      )}

      <div className="disc-actions">
        {settledManual ? (
          mayStartRound ? (
            <button
              type="button"
              className="disc-btn"
              data-testid="disc-start-round"
              disabled={busy || pendingAction === "start-round"}
              onClick={() => setStartOpen(true)}
            >
              {pendingAction === "start-round" ? "正在开始新一轮…" : "开始新一轮"}
            </button>
          ) : null
        ) : !manual && !session.decision_package ? (
          <button
            type="button"
            className="disc-btn"
            data-testid="disc-pause-resume"
            disabled={busy || pausing}
            onClick={() => (session.paused ? onResume() : onPause())}
          >
            {pauseLabel}
          </button>
        ) : null}
        {!manual && !session.decision_package && (
          <button
            type="button"
            className="disc-btn"
            data-testid="disc-end-round"
            disabled={busy}
            onClick={() => setEndOpen(true)}
          >
            结束本轮
          </button>
        )}
        <button
          type="button"
          className="disc-btn disc-btn-danger"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
        >
          终止
        </button>
      </div>

      {session.paused && !session.pause_requested && !manual && !session.decision_package && (
        <div className="disc-intervention" data-testid="disc-intervention">
          <label className="disc-composer-field">
            <span className="disc-composer-label">插话 / 调整方向（恢复后生效）</span>
            <textarea
              className="disc-composer-input"
              aria-label="讨论插话"
              rows={2}
              maxLength={2000}
              value={intervention}
              onChange={(event) => setIntervention(event.target.value)}
              placeholder="补充约束或指出需要调整的方向；不会改写已有评语。"
              disabled={busy}
            />
          </label>
          <button
            type="button"
            className="disc-btn"
            data-testid="disc-send-intervention"
            disabled={busy || !intervention.trim()}
            onClick={() => {
              const text = intervention.trim();
              if (!text) return;
              void (async () => {
                const saved = await onIntervene?.(text);
                if (saved === true) setIntervention("");
              })();
            }}
          >
            发送介入
          </button>
        </div>
      )}

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
            ref={confirmRef}
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

      {endOpen && (
        <div
          className="disc-dialog-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setEndOpen(false);
          }}
        >
          <div
            className="disc-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="disc-end-title"
            aria-describedby="disc-end-desc"
            tabIndex={-1}
            ref={endRef}
            data-testid="disc-end-round-dialog"
          >
            <h3 id="disc-end-title" className="disc-dialog-title">人工结束本轮？</h3>
            <p id="disc-end-desc" className="disc-dialog-text">
              即使分差未达标也可以结束；讨论会停在当前成果，等待人工处理。不会自动批准规格或进入执行。
            </p>
            <label className="disc-composer-field">
              <span className="disc-composer-label">结束原因（可选，最多 2000 字）</span>
              <textarea
                className="disc-composer-input"
                aria-label="结束本轮原因"
                rows={2}
                maxLength={2000}
                value={endReason}
                onChange={(event) => setEndReason(event.target.value)}
              />
            </label>
            <div className="disc-dialog-actions">
              <button type="button" className="disc-btn disc-btn-quiet" onClick={() => setEndOpen(false)}>取消</button>
              <button
                type="button"
                className="disc-btn disc-btn-danger"
                data-testid="disc-confirm-end-round"
                disabled={busy}
                onClick={() => {
                  setEndOpen(false);
                  void (async () => {
                    const saved = await onEndRound?.(endReason.trim());
                    if (saved === true) setEndReason("");
                  })();
                }}
              >
                确认结束本轮
              </button>
            </div>
          </div>
        </div>
      )}

      {startOpen && (
        <div
          className="disc-dialog-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setStartOpen(false);
          }}
        >
          <div
            className="disc-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="disc-start-title"
            aria-describedby="disc-start-desc"
            tabIndex={-1}
            ref={startRef}
            data-testid="disc-start-round-dialog"
          >
            <h3 id="disc-start-title" className="disc-dialog-title">开始新一轮？</h3>
            <p id="disc-start-desc" className="disc-dialog-text">
              这会明确开始新一轮讨论；人工结束标记会被清除，但仍不会自动批准规格。
            </p>
            <div className="disc-dialog-actions">
              <button type="button" className="disc-btn disc-btn-quiet" onClick={() => setStartOpen(false)}>取消</button>
              <button
                type="button"
                className="disc-btn"
                data-testid="disc-confirm-start-round"
                disabled={busy}
                onClick={() => {
                  setStartOpen(false);
                  onStartRound?.();
                }}
              >
                确认开始
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
