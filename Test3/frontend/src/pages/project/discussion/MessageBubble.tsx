import { useState } from "react";
import type { BotInstance, DiscussionMessage, DiscussionTimelineItem } from "../../../api/types";
import { BotAvatar } from "../../../components/BotAvatar";
import type { DiscussionStage } from "./deriveStage";

export type MessageBubbleProps = {
  item: DiscussionTimelineItem;
  bots: BotInstance[];
  stage: DiscussionStage;
  loadProposalBody: (proposalId: string) => Promise<string>;
};

type AvatarBot = Pick<BotInstance, "bot_id" | "display_name" | "role_template" | "status">;

const DIMENSIONS = [
  ["value", "用户价值"],
  ["feasibility", "可行性"],
  ["testability", "可测性"],
  ["clarity", "清晰度"],
] as const;

const HARD_GATES = [
  ["coverage", "覆盖"],
  ["conflicts_closed_or_recorded", "冲突已关闭或记录"],
  ["evidence_complete", "证据完整"],
] as const;

const LEADER_ACTIONS: Record<string, string> = {
  synthesize: "综合",
  accept: "接受",
  request_revision: "要求再改",
  submit: "提交审批",
};

const SYSTEM_EVENT_LABELS: Record<string, string> = {
  bot_failed: "Bot 调用失败",
  bot_skipped: "已跳过 Bot",
  paused: "已暂停",
  resumed: "已继续",
  terminated: "已终止",
  budget_exhausted: "已用尽预算",
};

/** Only `idea` / `independent` keep proposal bodies sealed; every later stage may reveal them. */
export function isSealedStage(stage: DiscussionStage): boolean {
  return stage === "idea" || stage === "independent";
}

export function resolveBubbleBot(bots: BotInstance[], botId: string | null | undefined): AvatarBot {
  const found = botId ? bots.find((bot) => bot.bot_id === botId) : undefined;
  if (found) return found;
  const fallbackId = botId || "unknown";
  return {
    bot_id: fallbackId,
    display_name: botId || "未知成员",
    role_template: "未知角色",
    status: "active",
  };
}

function readString(payload: Record<string, any>, key: string): string {
  const value = payload?.[key];
  return typeof value === "string" ? value : "";
}

function sumScores(scores: Record<string, unknown>): number {
  return Object.values(scores ?? {}).reduce<number>(
    (total, value) => total + (typeof value === "number" ? value : 0),
    0,
  );
}

function Divider({ text }: { text: string }) {
  return (
    <div className="disc-divider" role="separator" data-testid="disc-divider">
      <span className="disc-divider-text">{text}</span>
    </div>
  );
}

function SystemBubble({ message }: { message: DiscussionMessage }) {
  const event = readString(message.payload, "event");
  const label = SYSTEM_EVENT_LABELS[event] || "";
  const text = readString(message.payload, "text") || label || "系统提示";
  return (
    <div className="disc-system" data-testid="disc-bubble-system" data-event={event || undefined}>
      {label && (
        <span className={`disc-tag ${event === "bot_failed" ? "is-over" : "is-muted"}`}>{label}</span>
      )}
      <span className="disc-system-text">{text}</span>
    </div>
  );
}

function ProposalBubble({
  message,
  bot,
  stage,
  loadProposalBody,
}: {
  message: DiscussionMessage;
  bot: AvatarBot;
  stage: DiscussionStage;
  loadProposalBody: (proposalId: string) => Promise<string>;
}) {
  const proposalId = readString(message.payload, "proposal_id");
  const payloadRound = Number(message.payload?.round);
  const round = Number.isFinite(payloadRound) && payloadRound > 0 ? payloadRound : message.round || 1;
  const chars = typeof message.payload?.chars === "number" ? message.payload.chars : null;
  const truncated = message.payload?.truncated === true;
  const sealed = isSealedStage(stage);

  const [expanded, setExpanded] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const bodyId = `disc-proposal-body-${message.session_id}-${message.seq}`;

  async function load() {
    if (!proposalId) return;
    setLoading(true);
    setFailed(false);
    try {
      const text = await loadProposalBody(proposalId);
      setBody(typeof text === "string" ? text : "");
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (body === null && !loading && !failed) void load();
  }

  return (
    <article
      className="disc-bubble disc-bubble-proposal"
      data-testid="disc-bubble-proposal"
      data-proposal-id={proposalId || undefined}
    >
      <BotAvatar bot={bot} size={32} className="disc-avatar" />
      <div className="disc-bubble-body">
        <header className="disc-bubble-head">
          <span className="disc-bubble-author">{bot.display_name}</span>
          <span className="disc-bubble-meta">提交了方案 · 第 {round} 轮</span>
        </header>
        <div className="disc-bubble-meta-row">
          {chars !== null && <span className="disc-bubble-meta">{chars} 字</span>}
          {truncated && (
            <span className="disc-badge is-warn" title="方案正文超过长度上限，已截断">
              已截断
            </span>
          )}
        </div>
        {sealed ? (
          <p className="disc-bubble-note">已提交方案（内容已封存）</p>
        ) : (
          <div className="disc-proposal">
            <button
              type="button"
              className="disc-btn disc-btn-quiet"
              aria-expanded={expanded}
              aria-controls={bodyId}
              onClick={toggle}
              disabled={!proposalId}
            >
              {expanded ? "收起方案" : "展开方案"}
            </button>
            {expanded && (
              <div className="disc-proposal-body-wrap" id={bodyId}>
                {loading && (
                  <p className="disc-bubble-meta" role="status">
                    加载中…
                  </p>
                )}
                {!loading && failed && (
                  <button type="button" className="disc-btn disc-btn-quiet" onClick={() => void load()}>
                    正文加载失败，重试
                  </button>
                )}
                {!loading && !failed && body !== null && (
                  <pre className="disc-proposal-body" tabIndex={0} aria-label="方案正文">
                    {body}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function ReviewBubble({ message, bots }: { message: DiscussionMessage; bots: BotInstance[] }) {
  const reviewerId = readString(message.payload, "reviewer_bot_id") || message.bot_id || "";
  const reviewer = resolveBubbleBot(bots, reviewerId);
  const proposalId = readString(message.payload, "proposal_id");
  const scores = (message.payload?.scores ?? {}) as Record<string, unknown>;
  const gates = (message.payload?.hard_gate_results ?? {}) as Record<string, unknown>;
  const total =
    typeof message.payload?.total === "number" ? message.payload.total : sumScores(scores);
  const summary = readString(message.payload, "summary");

  return (
    <article className="disc-bubble disc-bubble-review" data-testid="disc-bubble-review">
      <BotAvatar bot={reviewer} size={32} className="disc-avatar" />
      <div className="disc-bubble-body">
        <header className="disc-bubble-head">
          <span className="disc-bubble-author">{reviewer.display_name}</span>
          <span className="disc-bubble-meta">
            评分 · 方案 <span className="mono">{proposalId || "—"}</span>
          </span>
          <span className="disc-score-total">
            总分 <strong>{total}</strong>
          </span>
        </header>
        <dl className="disc-score-dims">
          {DIMENSIONS.map(([key, label]) => (
            <div className="disc-score-dim" key={key}>
              <dt>{label}</dt>
              <dd>{typeof scores[key] === "number" ? String(scores[key]) : "—"}</dd>
            </div>
          ))}
        </dl>
        <ul className="disc-review-gates">
          {HARD_GATES.map(([key, label]) => {
            const passed = gates[key] === true;
            return (
              <li key={key} className={`disc-gate ${passed ? "is-ok" : "is-over"}`}>
                <span className="disc-gate-mark" aria-hidden>
                  {passed ? "✓" : "✗"}
                </span>
                <span>{label}</span>
                <span className="disc-gate-state">{passed ? "通过" : "未通过"}</span>
              </li>
            );
          })}
        </ul>
        {summary && <p className="disc-review-summary">{summary}</p>}
      </div>
    </article>
  );
}

function LeaderBubble({ message, bot }: { message: DiscussionMessage; bot: AvatarBot }) {
  const action = readString(message.payload, "action");
  const label = LEADER_ACTIONS[action] || action || "发言";
  const text = readString(message.payload, "text");
  return (
    <article
      className="disc-bubble disc-bubble-leader"
      data-testid="disc-bubble-leader"
      data-action={action || undefined}
    >
      <BotAvatar bot={bot} size={32} className="disc-avatar" />
      <div className="disc-bubble-body">
        <header className="disc-bubble-head">
          <span className="disc-bubble-author">{bot.display_name}</span>
          <span className="disc-tag is-accent">Leader · {label}</span>
        </header>
        {text ? <p className="disc-bubble-text">{text}</p> : null}
      </div>
    </article>
  );
}

export function MessageBubble({ item, bots, stage, loadProposalBody }: MessageBubbleProps) {
  if (item.type === "divider") {
    return <Divider text={item.text} />;
  }

  const { message } = item;
  const bot = resolveBubbleBot(bots, message.bot_id);

  if (message.kind === "system") {
    return <SystemBubble message={message} />;
  }
  if (message.kind === "proposal") {
    return (
      <ProposalBubble
        message={message}
        bot={bot}
        stage={stage}
        loadProposalBody={loadProposalBody}
      />
    );
  }
  if (message.kind === "review") {
    return <ReviewBubble message={message} bots={bots} />;
  }
  return <LeaderBubble message={message} bot={bot} />;
}

export default MessageBubble;