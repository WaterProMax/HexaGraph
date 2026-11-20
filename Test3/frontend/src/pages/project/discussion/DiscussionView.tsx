import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";
import type { BotInstance } from "../../../api/types";
import type { TeamMember } from "../TeamStrip";
import { ApprovalBanner } from "./ApprovalBanner";
import { DiscussionChat } from "./DiscussionChat";
import { IdeaComposer } from "./IdeaComposer";
import { ScorePanel } from "./ScorePanel";
import { SpecApprovalDialog } from "./SpecApprovalDialog";
import { SpecViewer } from "./SpecViewer";
import { StageBar } from "./StageBar";
import { deriveStage, type DiscussionStage } from "./deriveStage";
import { useDiscussionSession } from "./useDiscussionSession";

export type DiscussionViewProps = {
  projectId: string;
  /** Acting identity for every discussion request; may be empty before the team loads. */
  actorBotId: string;
  members: TeamMember[];
  bots: BotInstance[];
  onInvite: () => void;
};

/** Stages that show the two-column timeline + scoring layout. */
const CHAT_STAGES: DiscussionStage[] = [
  "independent",
  "revise",
  "review",
  "leader",
  "approval",
  "terminated",
];

export const SPEC_PREVIEW_CHARS = 240;
export const UNSEALED_BODY_TEXT = "正文尚未解封";

function actionErrorText(err: unknown): string {
  const message = (err as { message?: unknown } | null)?.message;
  return typeof message === "string" && message.trim() ? message : "操作失败，请稍后重试";
}

/** Plain-text preview of the markdown spec, capped at `SPEC_PREVIEW_CHARS`. */
export function specPreview(markdown: string): string {
  const plain = String(markdown ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/[*_>~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > SPEC_PREVIEW_CHARS ? `${plain.slice(0, SPEC_PREVIEW_CHARS)}…` : plain;
}

/**
 * Composes the whole discussion flow: progress bar, idea composer, chat + score panel,
 * approval dialog and the approved-spec summary. All state comes from the server-backed
 * `useDiscussionSession` hook; nothing is cached in browser storage.
 */
export function DiscussionView({
  projectId,
  actorBotId,
  members,
  bots,
  onInvite,
}: DiscussionViewProps) {
  const { loading, error, session, sessions, messages, timeline, reviews, connection, refresh } =
    useDiscussionSession(projectId, actorBotId);
  const stage = deriveStage(session);

  const [approvalOpen, setApprovalOpen] = useState(false);
  const [specOpen, setSpecOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const actionBusyRef = useRef(false);

  // Auto-open the approval dialog once per approval stage; a user close must not reopen it.
  const autoOpenedRef = useRef<string | null>(null);
  useEffect(() => {
    if (stage !== "approval" || !session) {
      autoOpenedRef.current = null;
      return;
    }
    if (autoOpenedRef.current === session.session_id) return;
    autoOpenedRef.current = session.session_id;
    setApprovalOpen(true);
  }, [stage, session]);

  useEffect(() => {
    if (stage !== "approval") setApprovalOpen(false);
    if (stage !== "approved") setSpecOpen(false);
  }, [stage]);

  const proposalCache = useRef(new Map<string, Promise<string>>());
  const sessionId = session?.session_id ?? "";
  const loadProposalBody = useCallback(
    (proposalId: string): Promise<string> => {
      if (!sessionId) return Promise.resolve(UNSEALED_BODY_TEXT);
      const key = `${sessionId}:${proposalId}`;
      const cached = proposalCache.current.get(key);
      if (cached) return cached;
      const pending = api
        .discussionProposals(sessionId, actorBotId)
        .then((result) => {
          const items = Array.isArray(result?.items) ? result.items : [];
          const found = items.find((item) => item?.proposal_id === proposalId);
          return found?.body_md ?? UNSEALED_BODY_TEXT;
        })
        .catch((err) => {
          proposalCache.current.delete(key);
          throw err;
        });
      proposalCache.current.set(key, pending);
      return pending;
    },
    [sessionId, actorBotId],
  );

  const withSession = async (action: (sessionId: string) => Promise<unknown>) => {
    if (!session || actionBusyRef.current) return;
    actionBusyRef.current = true;
    setActionBusy(true);
    setActionError("");
    try {
      await action(session.session_id);
      refresh();
    } catch (err) {
      setActionError(actionErrorText(err));
    } finally {
      actionBusyRef.current = false;
      setActionBusy(false);
    }
  };

  const pause = () => withSession((id) => api.pauseDiscussion(id, actorBotId));
  const resume = (skipBotIds?: string[]) =>
    withSession((id) => api.resumeDiscussion(id, { skip_bot_ids: skipBotIds }, actorBotId));
  const terminate = () => withSession((id) => api.terminateDiscussion(id, actorBotId));

  const participantBotIds = members.map((member) => member.bot_id);
  const hasLeader = members.some((member) => member.is_leader);
  const specPackage = session?.decision_package ?? null;

  return (
    <div className="disc-view" data-testid="disc-view" data-stage={stage}>
      <StageBar stage={stage} round={session?.current_round} />

      {loading && !session && (
        <p className="disc-view-status" role="status" data-testid="disc-loading">
          正在加载讨论…
        </p>
      )}
      {error && (
        <p className="disc-view-error" role="alert" data-testid="disc-error">
          讨论加载失败：{error}
        </p>
      )}
      {connection === "error" && (
        <p className="disc-connection-hint" role="status" data-testid="disc-connection-hint">
          实时连接不可用，正在尝试重连或轮询
        </p>
      )}
      {actionError && (
        <p className="disc-view-error" role="alert" data-testid="disc-action-error">
          {actionError}
        </p>
      )}

      {stage === "approval" && (
        <ApprovalBanner round={session?.current_round} onOpen={() => setApprovalOpen(true)} />
      )}

      {stage === "idea" && !loading && !error && (
        <IdeaComposer
          projectId={projectId}
          actorBotId={actorBotId}
          participantBotIds={participantBotIds}
          memberCount={members.length}
          hasLeader={hasLeader}
          onInvite={onInvite}
          onStarted={() => refresh()}
        />
      )}

      {session && CHAT_STAGES.includes(stage) && (
        <div className="disc-layout" data-testid="disc-layout">
          <DiscussionChat
            timeline={timeline}
            bots={bots}
            stage={stage}
            session={session}
            loadProposalBody={loadProposalBody}
          />
          <aside className="disc-side" aria-label="评分与操作">
            {stage === "terminated" && (
              <p className="disc-readonly-note" role="status">
                讨论已终止，消息与评分仅保留为记录。
              </p>
            )}
            <ScorePanel
              session={session}
              reviews={reviews}
              messages={messages}
              bots={bots}
              busy={actionBusy || stage === "terminated"}
              onPause={pause}
              onResume={resume}
              onTerminate={terminate}
            />
          </aside>
        </div>
      )}

      {stage === "approved" && (
        <section className="disc-spec-summary glass-panel" data-testid="disc-spec-summary">
          <div className="section-title">
            <span>需求规格已通过</span>
            {specPackage && (
              <span className="hint mono" title={specPackage.sha256}>
                摘要 {specPackage.sha256.slice(0, 8)}
              </span>
            )}
          </div>
          <p className="disc-spec-summary-text">
            {specPackage ? specPreview(specPackage.body_md) : "需求规格正文暂不可用。"}
          </p>
          <div className="disc-spec-summary-actions">
            <span className="disc-spec-waiting" role="status">
              等待任务拆解
            </span>
            <button
              type="button"
              className="disc-button-secondary"
              onClick={() => setSpecOpen(true)}
            >
              查看需求规格
            </button>
          </div>
        </section>
      )}

      {stage === "approved" && (
        <SpecViewer open={specOpen} onClose={() => setSpecOpen(false)} sessions={sessions} />
      )}

      {stage === "approval" && session && (
        <SpecApprovalDialog
          open={approvalOpen}
          projectId={projectId}
          actorBotId={actorBotId}
          session={session}
          reviews={reviews}
          onClose={() => setApprovalOpen(false)}
          onApproved={() => {
            setApprovalOpen(false);
            refresh();
          }}
          onRestarted={() => {
            setApprovalOpen(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

export default DiscussionView;