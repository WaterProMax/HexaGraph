import { useEffect, useId, useRef, useState } from "react";
import { Alert, Button } from "antd";
import { ApiError, api } from "../../../api/client";
import type { DiscussionSession } from "../../../api/types";

export const MAX_IDEA_LENGTH = 2000;

export type IdeaComposerProps = {
  projectId: string;
  actorBotId: string;
  participantBotIds: string[];
  /** Active members of the project, including the actor. */
  memberCount: number;
  hasLeader: boolean;
  onInvite: () => void;
  onStarted: (session: DiscussionSession) => void;
};

function startErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    // The API rejects secret-looking input; never echo the payload back.
    if (err.category === "secret_in_body") return "想法里看起来有密钥，请删除后重试";
    return err.message?.trim() || "开始讨论失败，请重试";
  }
  const message = (err as { message?: unknown } | null)?.message;
  return typeof message === "string" && message.trim() ? message : "开始讨论失败，请重试";
}

/** One-line idea composer: creates a discussion session and starts it. */
export function IdeaComposer({
  projectId,
  actorBotId,
  participantBotIds,
  memberCount,
  hasLeader,
  onInvite,
  onStarted,
}: IdeaComposerProps) {
  const headingId = useId();
  const busyRef = useRef(false);
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = idea.trim();
  const blocked = memberCount < 2 || !hasLeader || !actorBotId;
  const canStart = !blocked && !busy && trimmed.length > 0;

  // A membership change invalidates the previous failure reason.
  const memberKey = participantBotIds.join(",");
  useEffect(() => {
    setError("");
  }, [memberCount, hasLeader, actorBotId, memberKey]);

  const start = async () => {
    if (!canStart || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const created = await api.createDiscussionSession(
        projectId,
        {
          leader_bot_id: actorBotId,
          participant_bot_ids: participantBotIds,
          requirement_snapshot: trimmed,
        },
        actorBotId,
      );
      await api.runDiscussion(created.session_id, actorBotId);
      onStarted(created);
    } catch (err) {
      setError(startErrorText(err));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="disc-composer glass-panel" aria-labelledby={headingId}>
      <div className="panel-heading">
        <h2 id={headingId}>发起讨论</h2>
      </div>
      <p className="disc-composer-lead">
        Bot 先各自独立出方案并互评，由 Leader 收敛成需求规格，最后交给你审批。
      </p>
      <form
        className="disc-composer-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void start();
        }}
      >
        <label className="disc-composer-field" htmlFor={`${headingId}-idea`}>
          <span className="disc-composer-label">你的想法</span>
          <textarea
            id={`${headingId}-idea`}
            className="disc-composer-input"
            aria-label="一句话想法"
            rows={3}
            maxLength={MAX_IDEA_LENGTH}
            value={idea}
            disabled={busy}
            placeholder="例如：做一个能查看空闲座位并预约的学习室网页。"
            onChange={(event) => setIdea(event.target.value)}
          />
        </label>
        <div className="disc-composer-meta">
          <span className="disc-composer-count">
            {idea.length} / {MAX_IDEA_LENGTH}
          </span>
        </div>

        {blocked ? (
          <div className="disc-composer-blocked">
            <span className="disc-composer-blocked-text" role="status">
              先邀请 Bot：项目至少需要 2 名成员并设置 Leader，才能开始讨论。
            </span>
            <Button className="disc-composer-invite" onClick={onInvite} disabled={busy}>
              去邀请
            </Button>
          </div>
        ) : (
          <p className="disc-composer-hint">提交后讨论全自动进行，中途只能暂停或终止。</p>
        )}

        {error && (
          <Alert className="disc-composer-error" type="error" showIcon role="alert" message={error} />
        )}

        <div className="disc-composer-actions">
          <Button
            type="primary"
            htmlType="submit"
            className="disc-composer-start"
            loading={busy}
            disabled={blocked || busy || trimmed.length === 0}
          >
            开始讨论
          </Button>
        </div>
      </form>
    </section>
  );
}

export default IdeaComposer;